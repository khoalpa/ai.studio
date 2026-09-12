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
        self.store = ArtifactStore(self.workspace, self.db.connection)

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

    def record_cross_file_result(
        self,
        transaction_id: str,
        generation_call_id: str,
        artifact_id: str,
        *,
        status: str,
        error_code: str | None,
        dependency_digest: str,
        evidence_digest: str,
        package_identity: str | None = None,
    ) -> str:
        """Persist an idempotent cross-file result and fail closed on rejection."""
        allowed = {"PASS", "REJECTED", "STALE", "QUARANTINED"}
        if status not in allowed:
            raise KernelError("RK020_CROSS_FILE_STATUS", "invalid cross-file result status")
        key = sha256_bytes(
            canonical_json_bytes(
                {
                    "transaction_id": transaction_id,
                    "generation_call_id": generation_call_id,
                    "artifact_id": artifact_id,
                    "package_identity": package_identity,
                    "status": status,
                    "error_code": error_code,
                    "dependency_digest": dependency_digest,
                    "evidence_digest": evidence_digest,
                }
            )
        )
        with self.db.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM cross_file_gate_results WHERE idempotency_key=?", (key,)
            ).fetchone()
            if existing is not None:
                return str(existing["id"])
            workflow_id, stage_id = self._workflow_for_transaction(connection, transaction_id)
            call = self._one(
                connection,
                "SELECT transaction_id,status FROM generation_calls WHERE id=?",
                (generation_call_id,),
            )
            if call["transaction_id"] != transaction_id:
                raise KernelError(
                    "RK049_CALL_TRANSACTION_MISMATCH", "call belongs to another transaction"
                )
            result_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO cross_file_gate_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    result_id,
                    key,
                    workflow_id,
                    stage_id,
                    transaction_id,
                    generation_call_id,
                    artifact_id,
                    package_identity,
                    status,
                    error_code,
                    dependency_digest,
                    evidence_digest,
                    utc_now(),
                ),
            )
            if status != "PASS":
                connection.execute(
                    "UPDATE gate_results SET is_current=0 WHERE artifact_id=? AND is_current=1",
                    (artifact_id,),
                )
                connection.execute(
                    "UPDATE artifacts SET status=? WHERE id=? AND mutation_status=?",
                    (ArtifactStatus.QUARANTINED, artifact_id, MutationStatus.MUTABLE),
                )
                artifact = self._one(
                    connection, "SELECT sha256 FROM artifacts WHERE id=?", (artifact_id,)
                )
                connection.execute(
                    "UPDATE image_artifact_authority SET quarantine_code=?,delivery_status='QUARANTINED',gate_status=? WHERE artifact_sha256=?",
                    (error_code, status, artifact["sha256"]),
                )
                connection.execute(
                    "UPDATE generation_calls SET status=?,failure_code=?,finished_at=? WHERE id=? AND status=?",
                    (
                        CallStatus.FAILED,
                        error_code,
                        utc_now(),
                        generation_call_id,
                        CallStatus.RUNNING,
                    ),
                )
                connection.execute(
                    "UPDATE asset_transactions SET status=?,updated_at=? WHERE id=? AND status<>?",
                    (
                        TransactionStatus.FAILED_RETRYABLE,
                        utc_now(),
                        transaction_id,
                        TransactionStatus.COMMITTED,
                    ),
                )
            self._event(
                connection,
                workflow_id,
                stage_id,
                "CROSS_FILE_GATE_RECORDED",
                {"artifact_id": artifact_id, "error_code": error_code, "status": status},
            )
            return result_id

    def create_image_package(
        self,
        transaction_id: str,
        generation_call_id: str,
        *,
        authority_set_digest: str,
        manifest_digest: str,
        dependency_digest: str,
        evidence_digest: str,
        supersedes_id: str | None = None,
    ) -> str:
        """Create a persisted package candidate with fresh transaction/call lineage."""
        package_id = uuid.uuid4().hex
        now = utc_now()
        with self.db.transaction() as connection:
            workflow_id, stage_id = self._workflow_for_transaction(connection, transaction_id)
            call = self._one(
                connection,
                "SELECT transaction_id FROM generation_calls WHERE id=?",
                (generation_call_id,),
            )
            if call["transaction_id"] != transaction_id:
                raise KernelError(
                    "RK049_CALL_TRANSACTION_MISMATCH", "call belongs to another transaction"
                )
            if supersedes_id is not None:
                previous = self._one(
                    connection,
                    "SELECT package_transaction_id,status FROM image_packages WHERE id=?",
                    (supersedes_id,),
                )
                if previous["package_transaction_id"] == transaction_id:
                    raise KernelError(
                        "RK021_PACKAGE_LINEAGE_REUSE", "republish requires a new transaction"
                    )
            connection.execute(
                "INSERT INTO image_packages(id,package_transaction_id,generation_call_id,artifact_id,authority_set_digest,manifest_digest,zip_digest,dependency_digest,evidence_digest,status,supersedes_id,superseded_by_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    package_id,
                    transaction_id,
                    generation_call_id,
                    None,
                    authority_set_digest,
                    manifest_digest,
                    None,
                    dependency_digest,
                    evidence_digest,
                    "CANDIDATE",
                    supersedes_id,
                    None,
                    now,
                    now,
                ),
            )
            self._event(
                connection,
                workflow_id,
                stage_id,
                "IMAGE_PACKAGE_CANDIDATE",
                {"package_id": package_id},
            )
        return package_id

    def pass_image_package(self, package_id: str, artifact_id: str, zip_digest: str) -> None:
        with self.db.transaction() as connection:
            package = self._one(
                connection,
                "SELECT package_transaction_id,status FROM image_packages WHERE id=?",
                (package_id,),
            )
            if package["status"] != "CANDIDATE":
                raise KernelError("RK022_PACKAGE_STATE", "only a candidate package can pass")
            workflow_id, stage_id = self._workflow_for_transaction(
                connection, package["package_transaction_id"]
            )
            artifact = self._one(
                connection, "SELECT byte_size FROM artifacts WHERE id=?", (artifact_id,)
            )
            connection.execute(
                "UPDATE image_packages SET artifact_id=?,zip_digest=?,zip_size=?,status='PASS',updated_at=? WHERE id=?",
                (artifact_id, zip_digest, artifact["byte_size"], utc_now(), package_id),
            )
            self._event(
                connection, workflow_id, stage_id, "IMAGE_PACKAGE_PASS", {"package_id": package_id}
            )

    def publish_image_package(self, package_id: str) -> None:
        with self.db.transaction() as connection:
            package = self._one(
                connection,
                "SELECT package_transaction_id,status,supersedes_id FROM image_packages WHERE id=?",
                (package_id,),
            )
            if package["status"] != "PASS":
                raise KernelError("RK022_PACKAGE_STATE", "only a PASS package can publish")
            workflow_id, stage_id = self._workflow_for_transaction(
                connection, package["package_transaction_id"]
            )
            connection.execute(
                "UPDATE image_packages SET status='PUBLISHED',updated_at=? WHERE id=?",
                (utc_now(), package_id),
            )
            if package["supersedes_id"] is not None:
                connection.execute(
                    "UPDATE image_packages SET status='SUPERSEDED',superseded_by_id=?,updated_at=? WHERE id=? AND status IN ('STALE','QUARANTINED','PUBLISHED')",
                    (package_id, utc_now(), package["supersedes_id"]),
                )
            self._event(
                connection,
                workflow_id,
                stage_id,
                "IMAGE_PACKAGE_PUBLISHED",
                {"package_id": package_id},
            )

    def finalize_image_package_publication(
        self,
        package_id: str,
        relative_path: str,
        byte_size: int,
        *,
        fault_stage: str | None = None,
    ) -> None:
        """Commit publication metadata and lifecycle event atomically."""
        with self.db.transaction() as connection:
            package = self._one(
                connection,
                "SELECT package_transaction_id,status,supersedes_id FROM image_packages WHERE id=?",
                (package_id,),
            )
            if package["status"] != "PASS":
                raise KernelError("RK022_PACKAGE_STATE", "only a PASS package can publish")
            workflow_id, stage_id = self._workflow_for_transaction(
                connection, package["package_transaction_id"]
            )
            connection.execute(
                "UPDATE image_packages SET status='PUBLISHED',published_relative_path=?,zip_size=?,updated_at=? WHERE id=?",
                (relative_path, byte_size, utc_now(), package_id),
            )
            if fault_stage == "AFTER_LIFECYCLE":
                raise KernelError("RK900_INJECTED_FAILURE", fault_stage)
            if package["supersedes_id"] is not None:
                connection.execute(
                    "UPDATE image_packages SET status='SUPERSEDED',superseded_by_id=?,updated_at=? WHERE id=? AND status IN ('STALE','QUARANTINED','PUBLISHED')",
                    (package_id, utc_now(), package["supersedes_id"]),
                )
            if fault_stage == "AFTER_SUPERSESSION":
                raise KernelError("RK900_INJECTED_FAILURE", fault_stage)
            self._event(
                connection,
                workflow_id,
                stage_id,
                "IMAGE_PACKAGE_PUBLISHED",
                {"package_id": package_id, "relative_path": relative_path},
            )
            if fault_stage == "AFTER_EVENT":
                raise KernelError("RK900_INJECTED_FAILURE", fault_stage)

    def register_image_package_target(self, package_id: str, relative_path: str) -> None:
        """Persist the intended canonical path before filesystem publication."""
        with self.db.transaction() as connection:
            package = self._one(
                connection,
                "SELECT status,published_relative_path FROM image_packages WHERE id=?",
                (package_id,),
            )
            if package["status"] != "PASS":
                raise KernelError("RK022_PACKAGE_STATE", "only a PASS package can set its target")
            existing = package["published_relative_path"]
            if existing is not None and existing != relative_path:
                raise KernelError("RK029_PACKAGE_TARGET_MISMATCH", "package target is immutable")
            connection.execute(
                "UPDATE image_packages SET published_relative_path=?,updated_at=? WHERE id=?",
                (relative_path, utc_now(), package_id),
            )

    def quarantine_image_package(self, package_id: str, error_code: str) -> None:
        with self.db.transaction() as connection:
            package = self._one(
                connection,
                "SELECT package_transaction_id,status FROM image_packages WHERE id=?",
                (package_id,),
            )
            if package["status"] not in {"CANDIDATE", "PASS", "STALE"}:
                raise KernelError(
                    "RK022_PACKAGE_STATE", "package cannot be quarantined from current state"
                )
            workflow_id, stage_id = self._workflow_for_transaction(
                connection, package["package_transaction_id"]
            )
            connection.execute(
                "UPDATE image_packages SET status='QUARANTINED',updated_at=? WHERE id=?",
                (utc_now(), package_id),
            )
            self._event(
                connection,
                workflow_id,
                stage_id,
                "IMAGE_PACKAGE_QUARANTINED",
                {"package_id": package_id, "error_code": error_code},
            )

    def quarantine_image_package_recovery(self, package_id: str, error_code: str) -> None:
        """Fail closed when persisted publication bytes are absent or corrupt."""
        with self.db.transaction() as connection:
            package = self._one(
                connection,
                "SELECT package_transaction_id,status FROM image_packages WHERE id=?",
                (package_id,),
            )
            if package["status"] == "QUARANTINED":
                return
            workflow_id, stage_id = self._workflow_for_transaction(
                connection, package["package_transaction_id"]
            )
            connection.execute(
                "UPDATE image_packages SET status='QUARANTINED',updated_at=? WHERE id=?",
                (utc_now(), package_id),
            )
            self._event(
                connection,
                workflow_id,
                stage_id,
                "IMAGE_PACKAGE_RECOVERY_QUARANTINED",
                {"package_id": package_id, "error_code": error_code},
            )

    def mark_image_packages_stale(self, authority_set_digest: str, error_code: str) -> int:
        """Persist stale propagation without deleting history or package bytes."""
        with self.db.transaction() as connection:
            rows = connection.execute(
                "SELECT id,package_transaction_id,artifact_id FROM image_packages WHERE authority_set_digest=? AND status IN ('CANDIDATE','PASS','PUBLISHED')",
                (authority_set_digest,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE image_packages SET status='STALE',updated_at=? WHERE id=?",
                    (utc_now(), row["id"]),
                )
                if row["artifact_id"] is not None:
                    connection.execute(
                        "UPDATE gate_results SET is_current=0 WHERE artifact_id=? AND is_current=1",
                        (row["artifact_id"],),
                    )
                workflow_id, stage_id = self._workflow_for_transaction(
                    connection, row["package_transaction_id"]
                )
                self._event(
                    connection,
                    workflow_id,
                    stage_id,
                    "IMAGE_PACKAGE_STALE",
                    {"package_id": row["id"], "error_code": error_code},
                )
            return len(rows)

    def recover_image_package_supersession(self, package_id: str) -> str:
        """Atomically repair a published successor's missing predecessor backlink."""
        with self.db.transaction() as connection:
            package = self._one(
                connection,
                "SELECT package_transaction_id,status,supersedes_id FROM image_packages WHERE id=?",
                (package_id,),
            )
            if package["status"] != "PUBLISHED" or package["supersedes_id"] is None:
                raise KernelError(
                    "RK038_SUPERSESSION_NOT_RECOVERABLE",
                    "package is not a published successor",
                )
            predecessor = self._one(
                connection,
                "SELECT status,superseded_by_id FROM image_packages WHERE id=?",
                (package["supersedes_id"],),
            )
            if (
                predecessor["status"] == "SUPERSEDED"
                and predecessor["superseded_by_id"] == package_id
            ):
                return "SUPERSEDED"
            if predecessor["status"] not in {"STALE", "QUARANTINED", "PUBLISHED"}:
                raise KernelError(
                    "RK039_SUPERSESSION_CONFLICT", "predecessor state cannot be superseded"
                )
            workflow_id, stage_id = self._workflow_for_transaction(
                connection, package["package_transaction_id"]
            )
            connection.execute(
                "UPDATE image_packages SET status='SUPERSEDED',superseded_by_id=?,updated_at=? WHERE id=?",
                (package_id, utc_now(), package["supersedes_id"]),
            )
            self._event(
                connection,
                workflow_id,
                stage_id,
                "IMAGE_PACKAGE_SUPERSESSION_RECOVERED",
                {"package_id": package_id, "supersedes_id": package["supersedes_id"]},
            )
            return "SUPERSEDED"

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
