"""Deterministic reconciliation after interrupted workflow execution."""

from __future__ import annotations

from pathlib import Path

from audio_story.domain.state import CallStatus, RecoveryCode, ResumeDecision, TransactionStatus
from audio_story.validation.canonical import sha256_bytes
from audio_story.workflows.kernel import WorkflowKernel


def recover(kernel: WorkflowKernel, workflow_id: str) -> tuple[ResumeDecision, ...]:
    decisions: list[ResumeDecision] = []
    with kernel.db.transaction() as connection:
        kernel._event(connection, workflow_id, None, "RESUME_STARTED", {})
        for temporary in kernel.store.orphan_temps():
            decisions.append(
                ResumeDecision(
                    RecoveryCode.TEMP_ORPHAN_QUARANTINED,
                    temporary.name,
                    "DEFERRED_CLEANUP",
                )
            )

        bound_paths = {
            str(row["relative_path"])
            for row in connection.execute("SELECT relative_path FROM artifacts")
        }
        for path in kernel.store.root.glob("*/*"):
            relative = path.relative_to(kernel.workspace).as_posix()
            if path.is_file() and relative not in bound_paths:
                decisions.append(
                    ResumeDecision(RecoveryCode.STORE_ORPHAN_FOUND, relative, "PRESERVE_UNBOUND")
                )

        rows = connection.execute(
            "SELECT a.id,a.sha256,a.relative_path,b.transaction_id FROM artifacts a LEFT JOIN artifact_bindings b ON b.artifact_id=a.id AND b.role='COMMITTED'"
        ).fetchall()
        for row in rows:
            path = kernel.workspace / row["relative_path"]
            if not path.is_file():
                decisions.append(
                    ResumeDecision(RecoveryCode.DB_FILE_MISSING, row["id"], "BLOCK_TRANSACTION")
                )
                if row["transaction_id"]:
                    connection.execute(
                        "UPDATE asset_transactions SET status=? WHERE id=?",
                        (TransactionStatus.FAILED_BLOCKING, row["transaction_id"]),
                    )
                cursor = connection.execute(
                    "UPDATE gate_results SET is_current=0 WHERE artifact_id=?", (row["id"],)
                )
                if cursor.rowcount:
                    decisions.append(
                        ResumeDecision(RecoveryCode.STALE_GATE, row["id"], "MARK_STALE")
                    )
            elif sha256_bytes(path.read_bytes()) != row["sha256"]:
                decisions.append(
                    ResumeDecision(RecoveryCode.DIGEST_MISMATCH, row["id"], "BLOCK_TRANSACTION")
                )
                if row["transaction_id"]:
                    connection.execute(
                        "UPDATE asset_transactions SET status=? WHERE id=?",
                        (TransactionStatus.FAILED_BLOCKING, row["transaction_id"]),
                    )
                cursor = connection.execute(
                    "UPDATE gate_results SET is_current=0 WHERE artifact_id=?", (row["id"],)
                )
                if cursor.rowcount:
                    decisions.append(
                        ResumeDecision(RecoveryCode.STALE_GATE, row["id"], "MARK_STALE")
                    )

        running_calls = connection.execute(
            "SELECT g.id,g.transaction_id FROM generation_calls g JOIN asset_transactions t ON t.id=g.transaction_id JOIN stage_runs s ON s.id=t.stage_run_id WHERE s.workflow_id=? AND g.status=?",
            (workflow_id, CallStatus.RUNNING),
        ).fetchall()
        for row in running_calls:
            connection.execute(
                "UPDATE generation_calls SET status=?,failure_code=?,finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (CallStatus.TIMED_OUT, "RECOVERED_INTERRUPTED_CALL", row["id"]),
            )
            decisions.append(
                ResumeDecision(RecoveryCode.CALL_INTERRUPTED, row["id"], "MARK_TIMED_OUT")
            )

        transactions = connection.execute(
            "SELECT t.id FROM asset_transactions t JOIN stage_runs s ON s.id=t.stage_run_id WHERE s.workflow_id=? AND t.status=?",
            (workflow_id, TransactionStatus.IN_PROGRESS),
        ).fetchall()
        for row in transactions:
            connection.execute(
                "UPDATE asset_transactions SET status=? WHERE id=?",
                (TransactionStatus.FAILED_RETRYABLE, row["id"]),
            )
            decisions.append(
                ResumeDecision(
                    RecoveryCode.TRANSACTION_INTERRUPTED,
                    row["id"],
                    "MARK_FAILED_RETRYABLE",
                )
            )

        stale = connection.execute(
            "SELECT g.id FROM gate_results g JOIN artifacts a ON a.id=g.artifact_id WHERE g.is_current=1 AND COALESCE(g.dependency_digest,'')<>COALESCE(a.dependency_digest,'')"
        ).fetchall()
        for row in stale:
            connection.execute("UPDATE gate_results SET is_current=0 WHERE id=?", (row["id"],))
            decisions.append(ResumeDecision(RecoveryCode.STALE_GATE, row["id"], "MARK_STALE"))

        if not decisions:
            decisions.append(ResumeDecision(RecoveryCode.CLEAN, workflow_id, "NO_ACTION"))
        kernel._event(
            connection,
            workflow_id,
            None,
            "RESUME_COMPLETED",
            {"decisions": [decision.code for decision in decisions]},
        )
    return tuple(decisions)


def cleanup_orphan_temps(kernel: WorkflowKernel, older_than_seconds: float) -> tuple[Path, ...]:
    import time

    cutoff = time.time() - older_than_seconds
    removed = []
    for path in kernel.store.orphan_temps():
        if path.stat().st_mtime <= cutoff:
            path.unlink()
            removed.append(path)
    return tuple(removed)
