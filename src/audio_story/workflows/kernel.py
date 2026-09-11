"""Application service for workflow state, transactions and artifacts."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from audio_story.artifacts.store import ArtifactStore, FaultPoint
from audio_story.domain.state import (
    ArtifactStatus,
    CallStatus,
    DetectorClass,
    GateStatus,
    MutationStatus,
    StageStatus,
    TransactionStatus,
    WorkflowStatus,
)
from audio_story.domain.state_machine import transition_stage, transition_workflow
from audio_story.persistence import Database
from audio_story.validation.canonical import canonical_json_bytes, digest_json, sha256_bytes


class KernelError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


OWNER_STAGE_BY_ROLE = {
    "STORY": "STAGE1",
    "STORY_VALIDATION": "STAGE1",
    "CHARACTER_ASSET": "STAGE1",
    "STAGE1_MANIFEST": "STAGE1",
    "LANDSCAPE": "STAGE2",
    "VISUAL_PLAN": "STAGE2",
    "VISUAL_BIBLE": "STAGE2",
    "STAGE2_MANIFEST": "STAGE2",
    "PORTRAIT": "STAGE3",
    "PACKAGE_QUALITY_REPORT": "STAGE3",
    "STAGE3_MANIFEST": "STAGE3",
    "VIDEO_PROMPTS": "STAGE4",
    "STAGE4_MANIFEST": "STAGE4",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class WorkflowKernel:
    def __init__(self, workspace: Path, *, busy_timeout_ms: int = 5_000) -> None:
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        migrations = Path(__file__).parents[3] / "migrations"
        self.db = Database(self.workspace / "runtime.sqlite3", migrations, busy_timeout_ms)
        self.store = ArtifactStore(self.workspace)

    def close(self) -> None:
        self.db.close()

    def create_workflow(
        self, profile: str, stage: str, route: str, canonical_digest: str, config_digest: str
    ) -> str:
        workflow_id = uuid.uuid4().hex
        now = utc_now()
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO workflow_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    workflow_id,
                    now,
                    now,
                    profile,
                    stage,
                    route,
                    WorkflowStatus.CREATED,
                    canonical_digest,
                    config_digest,
                ),
            )
            self._event(
                connection,
                workflow_id,
                None,
                "WORKFLOW_CREATED",
                {"status": WorkflowStatus.CREATED},
            )
        return workflow_id

    def transition_workflow(self, workflow_id: str, target: WorkflowStatus) -> None:
        with self.db.transaction() as connection:
            row = self._one(
                connection, "SELECT status FROM workflow_runs WHERE id=?", (workflow_id,)
            )
            status = transition_workflow(WorkflowStatus(row["status"]), target)
            connection.execute(
                "UPDATE workflow_runs SET status=?, updated_at=? WHERE id=?",
                (status, utc_now(), workflow_id),
            )
            self._event(
                connection,
                workflow_id,
                None,
                "STATE_TRANSITIONED",
                {"entity": "workflow", "status": status},
            )

    def start_stage(self, workflow_id: str, stage: str, capsule_digest: str) -> str:
        stage_id = uuid.uuid4().hex
        now = utc_now()
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO stage_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (stage_id, workflow_id, stage, StageStatus.PREFLIGHT, capsule_digest, now, now),
            )
            self._event(connection, workflow_id, stage_id, "STAGE_STARTED", {"stage": stage})
        return stage_id

    def transition_stage(self, stage_id: str, target: StageStatus) -> None:
        with self.db.transaction() as connection:
            row = self._one(
                connection, "SELECT workflow_id,status FROM stage_runs WHERE id=?", (stage_id,)
            )
            status = transition_stage(StageStatus(row["status"]), target)
            connection.execute(
                "UPDATE stage_runs SET status=?, updated_at=? WHERE id=?",
                (status, utc_now(), stage_id),
            )
            event = (
                "STAGE_PASSED"
                if status is StageStatus.PASS
                else "STAGE_FAILED"
                if status is StageStatus.FAIL
                else "STATE_TRANSITIONED"
            )
            self._event(
                connection,
                row["workflow_id"],
                stage_id,
                event,
                {"entity": "stage", "status": status},
            )

    def get_or_create_transaction(self, stage_id: str, orientation: str, basename: str) -> str:
        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM asset_transactions WHERE stage_run_id=? AND orientation=? AND basename=?",
                (stage_id, orientation, basename),
            ).fetchone()
            if row:
                return str(row["id"])
            transaction_id = uuid.uuid4().hex
            now = utc_now()
            connection.execute(
                "INSERT INTO asset_transactions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    transaction_id,
                    stage_id,
                    orientation,
                    basename,
                    TransactionStatus.PENDING,
                    now,
                    now,
                ),
            )
            return transaction_id

    def begin_generation_call(
        self,
        transaction_id: str,
        request_digest: str,
        *,
        model_identity: str | None = None,
        adapter_version: str | None = None,
    ) -> str:
        call_id = uuid.uuid4().hex
        with self.db.transaction() as connection:
            transaction = self._one(
                connection,
                "SELECT status FROM asset_transactions WHERE id=?",
                (transaction_id,),
            )
            running = connection.execute(
                "SELECT 1 FROM generation_calls WHERE transaction_id=? AND status=?",
                (transaction_id, CallStatus.RUNNING),
            ).fetchone()
            if (
                transaction["status"]
                not in {
                    TransactionStatus.PENDING,
                    TransactionStatus.FAILED_RETRYABLE,
                }
                or running
            ):
                raise KernelError(
                    "RK018_TRANSACTION_NOT_CALLABLE",
                    "transaction is terminal or already has a running generation call",
                )
            attempt = connection.execute(
                "SELECT COALESCE(MAX(attempt_index),0)+1 FROM generation_calls WHERE transaction_id=?",
                (transaction_id,),
            ).fetchone()[0]
            now = utc_now()
            connection.execute(
                "INSERT INTO generation_calls(id,transaction_id,attempt_index,request_digest,status,started_at,model_identity,adapter_version) VALUES (?,?,?,?,?,?,?,?)",
                (
                    call_id,
                    transaction_id,
                    attempt,
                    request_digest,
                    CallStatus.RUNNING,
                    now,
                    model_identity,
                    adapter_version,
                ),
            )
            connection.execute(
                "UPDATE asset_transactions SET status=?,updated_at=? WHERE id=?",
                (TransactionStatus.IN_PROGRESS, now, transaction_id),
            )
            workflow_id, stage_id = self._workflow_for_transaction(connection, transaction_id)
            self._event(
                connection,
                workflow_id,
                stage_id,
                "GENERATION_CALL_STARTED",
                {"call_id": call_id, "attempt_index": attempt},
            )
        return call_id

    def finish_generation_call(
        self,
        call_id: str,
        status: CallStatus,
        response_digest: str | None = None,
        failure_code: str | None = None,
        *,
        model_identity: str | None = None,
        adapter_version: str | None = None,
        duration_ms: int | None = None,
        termination_reason: str | None = None,
    ) -> None:
        if status is CallStatus.RUNNING:
            raise KernelError("RK008_INVALID_CALL_FINISH", "call cannot finish as RUNNING")
        with self.db.transaction() as connection:
            row = self._one(
                connection, "SELECT transaction_id FROM generation_calls WHERE id=?", (call_id,)
            )
            connection.execute(
                "UPDATE generation_calls SET status=?,response_digest=?,failure_code=?,finished_at=?,model_identity=COALESCE(?,model_identity),adapter_version=COALESCE(?,adapter_version),duration_ms=?,termination_reason=? WHERE id=?",
                (
                    status,
                    response_digest,
                    failure_code,
                    utc_now(),
                    model_identity,
                    adapter_version,
                    duration_ms,
                    termination_reason,
                    call_id,
                ),
            )
            if status in {CallStatus.FAILED, CallStatus.TIMED_OUT}:
                connection.execute(
                    "UPDATE asset_transactions SET status=?,updated_at=? WHERE id=?",
                    (TransactionStatus.FAILED_RETRYABLE, utc_now(), row["transaction_id"]),
                )
            workflow_id, stage_id = self._workflow_for_transaction(
                connection, row["transaction_id"]
            )
            self._event(
                connection,
                workflow_id,
                stage_id,
                "GENERATION_CALL_FINISHED",
                {"call_id": call_id, "status": status},
            )

    def register_candidate(
        self,
        call_id: str,
        data: bytes,
        media_type: str,
        owner_stage: str,
        artifact_role: str = "ARCHIVE",
        dependency_digest: str | None = None,
        fault: FaultPoint | None = None,
        fail_before_db_commit: bool = False,
    ) -> str:
        row = self._one(
            self.db.connection,
            "SELECT s.stage FROM generation_calls g JOIN asset_transactions t ON t.id=g.transaction_id JOIN stage_runs s ON s.id=t.stage_run_id WHERE g.id=?",
            (call_id,),
        )
        if row["stage"] != owner_stage:
            raise KernelError(
                "RK014_OWNER_STAGE_MISMATCH", "candidate owner does not match active stage"
            )
        expected_owner = OWNER_STAGE_BY_ROLE.get(artifact_role)
        if expected_owner is not None and expected_owner != owner_stage:
            raise KernelError(
                "RK015_ROLE_OWNER_MISMATCH", "artifact role is not owned by the active stage"
            )
        stored = self.store.put(data, fault)
        if fail_before_db_commit:
            raise KernelError(
                "RK900_INJECTED_DB_FAILURE", "store committed before injected DB failure"
            )
        artifact_id = uuid.uuid4().hex
        with self.db.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM artifacts WHERE sha256=?", (stored.digest,)
            ).fetchone()
            if existing:
                artifact_id = str(existing["id"])
            else:
                connection.execute(
                    "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        artifact_id,
                        stored.digest,
                        stored.relative_path,
                        stored.byte_size,
                        media_type,
                        artifact_role,
                        owner_stage,
                        ArtifactStatus.WORKING,
                        MutationStatus.MUTABLE,
                        dependency_digest,
                        utc_now(),
                    ),
                )
            connection.execute(
                "UPDATE generation_calls SET candidate_artifact_id=? WHERE id=?",
                (artifact_id, call_id),
            )
            row = self._one(
                connection, "SELECT transaction_id FROM generation_calls WHERE id=?", (call_id,)
            )
            workflow_id, stage_id = self._workflow_for_transaction(
                connection, row["transaction_id"]
            )
            self._event(
                connection,
                workflow_id,
                stage_id,
                "CANDIDATE_WRITTEN",
                {"artifact_id": artifact_id, "sha256": stored.digest},
            )
        return artifact_id

    def commit_artifact(self, transaction_id: str, artifact_id: str) -> str:
        with self.db.transaction() as connection:
            transaction = self._one(
                connection,
                "SELECT stage_run_id,status FROM asset_transactions WHERE id=?",
                (transaction_id,),
            )
            artifact = self._one(connection, "SELECT * FROM artifacts WHERE id=?", (artifact_id,))
            existing = connection.execute(
                "SELECT artifact_id FROM artifact_bindings WHERE transaction_id=? AND role='COMMITTED'",
                (transaction_id,),
            ).fetchone()
            if existing:
                if existing["artifact_id"] == artifact_id:
                    return artifact_id
                raise KernelError(
                    "RK010_DIFFERENT_DOUBLE_COMMIT", "transaction already committed different bytes"
                )
            if artifact["mutation_status"] == MutationStatus.READ_ONLY:
                raise KernelError(
                    "RK009_READ_ONLY_MUTATION",
                    "read-only artifact cannot be committed by this stage",
                )
            candidate = connection.execute(
                "SELECT 1 FROM generation_calls WHERE transaction_id=? AND candidate_artifact_id=?",
                (transaction_id, artifact_id),
            ).fetchone()
            if candidate is None:
                raise KernelError(
                    "RK019_ARTIFACT_TRANSACTION_MISMATCH",
                    "artifact is not a candidate produced for this transaction",
                )
            if artifact["status"] != ArtifactStatus.VALIDATED:
                raise KernelError(
                    "RK017_CANDIDATE_NOT_VALIDATED", "candidate is not validated for commit"
                )
            gate_counts = connection.execute(
                "SELECT COUNT(*) history, SUM(CASE WHEN is_current=1 AND status='PASS' THEN 1 ELSE 0 END) current_pass, SUM(CASE WHEN is_current=1 AND status NOT IN ('PASS','NOT_APPLICABLE') THEN 1 ELSE 0 END) current_blocking FROM gate_results WHERE artifact_id=?",
                (artifact_id,),
            ).fetchone()
            if gate_counts["history"] and (
                not gate_counts["current_pass"] or gate_counts["current_blocking"]
            ):
                raise KernelError(
                    "RK016_GATE_NOT_CURRENT_PASS", "artifact has no usable current PASS evidence"
                )
            data = self.store.read(artifact["relative_path"])
            if sha256_bytes(data) != artifact["sha256"]:
                raise KernelError(
                    "RK011_ARTIFACT_DIGEST_MISMATCH", "store bytes do not match artifact digest"
                )
            connection.execute(
                "INSERT INTO artifact_bindings VALUES (?,?,?,?,?)",
                (uuid.uuid4().hex, transaction_id, artifact_id, "COMMITTED", utc_now()),
            )
            connection.execute(
                "UPDATE artifacts SET status=?,mutation_status=? WHERE id=?",
                (ArtifactStatus.PUBLISHED, MutationStatus.READ_ONLY, artifact_id),
            )
            connection.execute(
                "UPDATE asset_transactions SET status=?,updated_at=? WHERE id=?",
                (TransactionStatus.COMMITTED, utc_now(), transaction_id),
            )
            stage = self._one(
                connection,
                "SELECT workflow_id FROM stage_runs WHERE id=?",
                (transaction["stage_run_id"],),
            )
            self._event(
                connection,
                stage["workflow_id"],
                transaction["stage_run_id"],
                "ARTIFACT_COMMITTED",
                {"artifact_id": artifact_id},
            )
        return artifact_id

    def quarantine_artifact(self, artifact_id: str, stage_id: str) -> None:
        with self.db.transaction() as connection:
            artifact = self._one(
                connection, "SELECT mutation_status FROM artifacts WHERE id=?", (artifact_id,)
            )
            if artifact["mutation_status"] == MutationStatus.READ_ONLY:
                raise KernelError("RK009_READ_ONLY_MUTATION", "published artifact is immutable")
            connection.execute(
                "UPDATE artifacts SET status=? WHERE id=?",
                (ArtifactStatus.QUARANTINED, artifact_id),
            )
            stage = self._one(
                connection, "SELECT workflow_id FROM stage_runs WHERE id=?", (stage_id,)
            )
            self._event(
                connection,
                stage["workflow_id"],
                stage_id,
                "ARTIFACT_QUARANTINED",
                {"artifact_id": artifact_id},
            )

    def record_gate(
        self,
        stage_id: str,
        artifact_id: str,
        gate_id: str,
        detector: DetectorClass,
        status: GateStatus,
        evidence: dict[str, Any],
        canonical_digest: str,
        capsule_digest: str,
        rule_version: str,
        dependency_digest: str | None = None,
    ) -> str:
        gate_id_value = uuid.uuid4().hex
        payload = canonical_json_bytes(evidence).decode("utf-8")
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE gate_results SET is_current=0 WHERE artifact_id=? AND gate_id=? AND is_current=1",
                (artifact_id, gate_id),
            )
            connection.execute(
                "INSERT INTO gate_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    gate_id_value,
                    stage_id,
                    artifact_id,
                    gate_id,
                    detector,
                    status,
                    payload,
                    digest_json(evidence),
                    canonical_digest,
                    capsule_digest,
                    rule_version,
                    dependency_digest,
                    1,
                    utc_now(),
                ),
            )
            if status is GateStatus.PASS:
                connection.execute(
                    "UPDATE artifacts SET status=? WHERE id=? AND mutation_status=?",
                    (ArtifactStatus.VALIDATED, artifact_id, MutationStatus.MUTABLE),
                )
            stage = self._one(
                connection, "SELECT workflow_id FROM stage_runs WHERE id=?", (stage_id,)
            )
            self._event(
                connection,
                stage["workflow_id"],
                stage_id,
                "GATE_RECORDED",
                {"gate_id": gate_id, "status": status},
            )
        return gate_id_value

    def mark_dependency_stale(self, artifact_id: str, dependency_digest: str) -> int:
        with self.db.transaction() as connection:
            cursor = connection.execute(
                "UPDATE gate_results SET is_current=0 WHERE artifact_id=? AND is_current=1 AND COALESCE(dependency_digest,'')<>?",
                (artifact_id, dependency_digest),
            )
            return cursor.rowcount

    def progress(self, stage_id: str) -> tuple[int, int]:
        row = self.db.connection.execute(
            "SELECT COUNT(*) total, SUM(CASE WHEN t.status=? AND (NOT EXISTS(SELECT 1 FROM artifact_bindings b JOIN gate_results g ON g.artifact_id=b.artifact_id WHERE b.transaction_id=t.id) OR EXISTS(SELECT 1 FROM artifact_bindings b JOIN gate_results g ON g.artifact_id=b.artifact_id WHERE b.transaction_id=t.id AND g.is_current=1 AND g.status='PASS')) THEN 1 ELSE 0 END) committed FROM asset_transactions t WHERE stage_run_id=?",
            (TransactionStatus.COMMITTED, stage_id),
        ).fetchone()
        return int(row["committed"] or 0), int(row["total"])

    def inspect_workflow(self, workflow_id: str) -> dict[str, Any]:
        workflow = dict(
            self._one(self.db.connection, "SELECT * FROM workflow_runs WHERE id=?", (workflow_id,))
        )
        workflow["stages"] = [
            dict(row)
            for row in self.db.connection.execute(
                "SELECT * FROM stage_runs WHERE workflow_id=? ORDER BY created_at,id",
                (workflow_id,),
            )
        ]
        return workflow

    def acquire_lease(self, workspace_id: str, owner_id: str, ttl_seconds: int = 30) -> None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=ttl_seconds)
        with self.db.transaction() as connection:
            row = connection.execute(
                "SELECT owner_id,expires_at FROM workspace_leases WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
            if (
                row
                and row["owner_id"] != owner_id
                and datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")) > now
            ):
                raise KernelError("RK012_LEASE_CONFLICT", "workspace has an active owner")
            connection.execute(
                "INSERT INTO workspace_leases VALUES (?,?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET owner_id=excluded.owner_id,expires_at=excluded.expires_at,updated_at=excluded.updated_at",
                (workspace_id, owner_id, expires.isoformat().replace("+00:00", "Z"), utc_now()),
            )

    def _event(
        self,
        connection: sqlite3.Connection,
        workflow_id: str,
        stage_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence_no),0)+1 FROM events WHERE workflow_id=?", (workflow_id,)
        ).fetchone()[0]
        payload_json = canonical_json_bytes(payload).decode("utf-8")
        connection.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                workflow_id,
                stage_id,
                sequence,
                event_type,
                payload_json,
                sha256_bytes(payload_json.encode()),
                utc_now(),
            ),
        )

    def _workflow_for_transaction(
        self, connection: sqlite3.Connection, transaction_id: str
    ) -> tuple[str, str]:
        row = self._one(
            connection,
            "SELECT s.workflow_id,s.id stage_id FROM asset_transactions t JOIN stage_runs s ON s.id=t.stage_run_id WHERE t.id=?",
            (transaction_id,),
        )
        return str(row["workflow_id"]), str(row["stage_id"])

    @staticmethod
    def _one(
        connection: sqlite3.Connection, query: str, parameters: tuple[Any, ...]
    ) -> sqlite3.Row:
        row = connection.execute(query, parameters).fetchone()
        if row is None:
            raise KernelError("RK013_NOT_FOUND", "requested kernel entity does not exist")
        return cast(sqlite3.Row, row)
