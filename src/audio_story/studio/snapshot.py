"""Read-only projections from the workflow kernel for Audio Story Studio."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from audio_story.workflows.kernel import WorkflowKernel


class StudioSnapshotService:
    """Project persisted kernel state without creating parallel UI authority."""

    def __init__(self, kernel: WorkflowKernel) -> None:
        self._kernel = kernel

    @property
    def workspace(self) -> str:
        return str(self._kernel.workspace)

    def latest(self) -> dict[str, Any]:
        connection = self._kernel.db.connection
        workflow = connection.execute(
            "SELECT * FROM workflow_runs ORDER BY updated_at DESC,id DESC LIMIT 1"
        ).fetchone()
        if workflow is None:
            return self._empty_snapshot()

        workflow_id = str(workflow["id"])
        stages = [
            self._stage(connection, row)
            for row in connection.execute(
                "SELECT * FROM stage_runs WHERE workflow_id=? ORDER BY created_at,id",
                (workflow_id,),
            )
        ]
        events = [
            {
                "sequence_no": int(row["sequence_no"]),
                "stage_id": row["stage_run_id"],
                "event_type": str(row["event_type"]),
                "payload": self._payload(str(row["payload_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in connection.execute(
                "SELECT sequence_no,stage_run_id,event_type,payload_json,created_at "
                "FROM events WHERE workflow_id=? ORDER BY sequence_no DESC LIMIT 20",
                (workflow_id,),
            )
        ]
        current_gates = self._current_gates(connection, workflow_id)
        story = self._story_metadata(connection, workflow_id)
        return {
            "schema_version": "1.0",
            "mode": "LIVE",
            "workspace": self.workspace,
            "workflow": {
                "id": workflow_id,
                "profile": str(workflow["profile"]),
                "requested_stage": str(workflow["requested_stage"]),
                "route": str(workflow["route"]),
                "status": str(workflow["status"]),
                "canonical_prompt_sha256": str(workflow["canonical_prompt_sha256"]),
                "created_at": str(workflow["created_at"]),
                "updated_at": str(workflow["updated_at"]),
            },
            "story": story,
            "stages": stages,
            "pipeline_stages": self._pipeline_stages(connection),
            "gates": current_gates,
            "gate_summary": self._gate_summary(current_gates),
            "events": events,
        }

    def _story_metadata(
        self, connection: sqlite3.Connection, workflow_id: str
    ) -> dict[str, str] | None:
        """Read display metadata from the committed Story artifact, never UI defaults."""
        row = connection.execute(
            "SELECT a.sha256 FROM stage_runs s "
            "JOIN asset_transactions t ON t.stage_run_id=s.id "
            "JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
            "JOIN artifacts a ON a.id=b.artifact_id "
            "WHERE s.workflow_id=? AND s.stage='STAGE1' AND t.basename='story.json' "
            "ORDER BY t.updated_at DESC,t.id DESC LIMIT 1",
            (workflow_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            story = json.loads(self._kernel.store.get_artifact_by_digest(str(row["sha256"])))
            meta = story["meta"]
        except (KeyError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(meta, dict):
            return None
        fields = {key: meta.get(key) for key in ("title", "series", "episode")}
        if not all(isinstance(value, str) and value.strip() for value in fields.values()):
            return None
        return {key: str(value) for key, value in fields.items()}

    def _stage(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        stage_id = str(row["id"])
        committed, total = self._kernel.progress(stage_id)
        transactions = [
            self._transaction(connection, item)
            for item in connection.execute(
                "SELECT * FROM asset_transactions WHERE stage_run_id=? ORDER BY created_at,id",
                (stage_id,),
            )
        ]
        return {
            "id": stage_id,
            "stage": str(row["stage"]),
            "status": str(row["status"]),
            "capsule_digest": str(row["capsule_digest"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "progress": {"committed": committed, "total": total},
            "transactions": transactions,
        }

    @staticmethod
    def _transaction(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        transaction_id = str(row["id"])
        calls = [
            dict(item)
            for item in connection.execute(
                "SELECT id,attempt_index,status,failure_code,started_at,finished_at,"
                "model_identity,adapter_version,duration_ms,termination_reason,request_digest,"
                "response_digest FROM generation_calls WHERE transaction_id=? "
                "ORDER BY attempt_index",
                (transaction_id,),
            )
        ]
        call = calls[-1] if calls else None
        binding = connection.execute(
            "SELECT a.id,a.sha256,a.byte_size,a.media_type,a.artifact_role,a.status,"
            "a.mutation_status FROM artifact_bindings b "
            "JOIN artifacts a ON a.id=b.artifact_id "
            "WHERE b.transaction_id=? AND b.role='COMMITTED'",
            (transaction_id,),
        ).fetchone()
        return {
            "id": transaction_id,
            "orientation": str(row["orientation"]),
            "basename": str(row["basename"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "latest_call": call,
            "calls": calls,
            "committed_artifact": dict(binding) if binding is not None else None,
        }

    @staticmethod
    def _current_gates(connection: sqlite3.Connection, workflow_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT g.id,g.stage_run_id,g.artifact_id,g.gate_id,g.detector_class,g.status,"
            "g.evidence_json,g.created_at,a.artifact_role,a.sha256 "
            "FROM gate_results g JOIN stage_runs s ON s.id=g.stage_run_id "
            "JOIN artifacts a ON a.id=g.artifact_id "
            "WHERE s.workflow_id=? AND g.is_current=1 ORDER BY g.created_at DESC,g.id",
            (workflow_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "stage_id": str(row["stage_run_id"]),
                "artifact_id": str(row["artifact_id"]),
                "artifact_role": str(row["artifact_role"]),
                "artifact_sha256": str(row["sha256"]),
                "gate_id": str(row["gate_id"]),
                "detector_class": str(row["detector_class"]),
                "status": str(row["status"]),
                "evidence": StudioSnapshotService._payload(str(row["evidence_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    @staticmethod
    def _gate_summary(gates: list[dict[str, Any]]) -> dict[str, int]:
        summary = {"total": len(gates), "pass": 0, "fail": 0, "not_verified": 0}
        for gate in gates:
            key = str(gate["status"]).lower()
            if key in summary:
                summary[key] += 1
        return summary

    @staticmethod
    def _payload(value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {"unparseable": True}

    def _empty_snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "mode": "EMPTY",
            "workspace": self.workspace,
            "workflow": None,
            "story": None,
            "stages": [],
            "pipeline_stages": [],
            "gates": [],
            "gate_summary": {"total": 0, "pass": 0, "fail": 0, "not_verified": 0},
            "events": [],
        }

    @staticmethod
    def _pipeline_stages(connection: sqlite3.Connection) -> list[dict[str, str]]:
        rows = connection.execute(
            "SELECT s.stage,s.status,s.updated_at,s.workflow_id FROM stage_runs s "
            "JOIN (SELECT stage,MAX(updated_at) updated_at FROM stage_runs GROUP BY stage) latest "
            "ON latest.stage=s.stage AND latest.updated_at=s.updated_at "
            "ORDER BY s.stage,s.id"
        ).fetchall()
        selected: dict[str, dict[str, str]] = {}
        for row in rows:
            selected[str(row["stage"])] = {
                "stage": str(row["stage"]),
                "status": str(row["status"]),
                "updated_at": str(row["updated_at"]),
                "workflow_id": str(row["workflow_id"]),
            }
        return [selected[stage] for stage in sorted(selected)]
