from __future__ import annotations

from pathlib import Path

import pytest

from audio_story.artifacts.store import FaultPoint, StoreError
from audio_story.domain.state import (
    CallStatus,
    DetectorClass,
    GateStatus,
    RecoveryCode,
    TransactionStatus,
    WorkflowStatus,
)
from audio_story.workflows import KernelError, WorkflowKernel
from audio_story.workflows.recovery import cleanup_orphan_temps, recover

PROMPT = "4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27"


def _pass_gate(
    kernel: WorkflowKernel, stage: str, artifact: str, dependency: str | None = None
) -> None:
    kernel.record_gate(
        stage,
        artifact,
        "VALIDATE",
        DetectorClass.DETERMINISTIC,
        GateStatus.PASS,
        {"ok": True},
        PROMPT,
        "a" * 64,
        "1.0",
        dependency,
    )


def _active(tmp_path: Path) -> tuple[WorkflowKernel, str, str, str, str]:
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("YOUTH_SAFE", "STAGE1", "CREATE", PROMPT, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE1", "a" * 64)
    transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "cover.png")
    call = kernel.begin_generation_call(transaction, "c" * 64)
    return kernel, workflow, stage, transaction, call


def test_recovery_marks_interrupted_call_and_transaction_without_progress(tmp_path: Path) -> None:
    kernel, workflow, stage, transaction, call = _active(tmp_path)
    kernel.close()
    reopened = WorkflowKernel(tmp_path)
    codes = {decision.code for decision in recover(reopened, workflow)}
    assert RecoveryCode.CALL_INTERRUPTED in codes
    assert RecoveryCode.TRANSACTION_INTERRUPTED in codes
    assert reopened.progress(stage) == (0, 1)
    assert (
        reopened.db.connection.execute(
            "SELECT status FROM generation_calls WHERE id=?", (call,)
        ).fetchone()[0]
        == CallStatus.TIMED_OUT
    )
    assert (
        reopened.db.connection.execute(
            "SELECT status FROM asset_transactions WHERE id=?", (transaction,)
        ).fetchone()[0]
        == TransactionStatus.FAILED_RETRYABLE
    )
    reopened.close()


def test_recovery_detects_store_orphan_after_rename_and_db_failure(tmp_path: Path) -> None:
    kernel, workflow, _, _, call = _active(tmp_path)
    with pytest.raises(StoreError):
        kernel.register_candidate(
            call, b"rename-orphan", "image/png", "STAGE1", fault=FaultPoint.AFTER_RENAME
        )
    with pytest.raises(KernelError):
        kernel.register_candidate(
            call, b"db-orphan", "image/png", "STAGE1", fail_before_db_commit=True
        )
    decisions = recover(kernel, workflow)
    assert sum(item.code is RecoveryCode.STORE_ORPHAN_FOUND for item in decisions) >= 2
    kernel.close()


def test_temp_orphan_is_deferred_then_cleaned(tmp_path: Path) -> None:
    kernel, workflow, _, _, call = _active(tmp_path)
    with pytest.raises(StoreError):
        kernel.register_candidate(
            call, b"temp", "image/png", "STAGE1", fault=FaultPoint.AFTER_TEMP_WRITE
        )
    assert any(
        item.code is RecoveryCode.TEMP_ORPHAN_QUARANTINED for item in recover(kernel, workflow)
    )
    assert cleanup_orphan_temps(kernel, older_than_seconds=0)
    kernel.close()


def test_missing_and_mismatched_committed_files_block_after_restart(tmp_path: Path) -> None:
    kernel, workflow, stage, transaction, call = _active(tmp_path)
    artifact = kernel.register_candidate(call, b"published", "image/png", "STAGE1")
    kernel.finish_generation_call(call, CallStatus.FINISHED)
    _pass_gate(kernel, stage, artifact)
    kernel.commit_artifact(transaction, artifact)
    row = kernel.db.connection.execute(
        "SELECT relative_path FROM artifacts WHERE id=?", (artifact,)
    ).fetchone()
    path = kernel.workspace / row["relative_path"]
    path.unlink()
    kernel.close()
    reopened = WorkflowKernel(tmp_path)
    assert RecoveryCode.DB_FILE_MISSING in {item.code for item in recover(reopened, workflow)}
    assert (
        reopened.db.connection.execute(
            "SELECT status FROM asset_transactions WHERE id=?", (transaction,)
        ).fetchone()[0]
        == TransactionStatus.FAILED_BLOCKING
    )
    reopened.close()


def test_digest_mismatch_and_stale_gate_are_detected(tmp_path: Path) -> None:
    kernel, workflow, stage, transaction, call = _active(tmp_path)
    artifact = kernel.register_candidate(
        call, b"published", "image/png", "STAGE1", dependency_digest="current"
    )
    kernel.finish_generation_call(call, CallStatus.FINISHED)
    _pass_gate(kernel, stage, artifact, "stale")
    kernel.commit_artifact(transaction, artifact)
    row = kernel.db.connection.execute(
        "SELECT relative_path FROM artifacts WHERE id=?", (artifact,)
    ).fetchone()
    (kernel.workspace / row["relative_path"]).write_bytes(b"tampered")
    codes = {item.code for item in recover(kernel, workflow)}
    assert RecoveryCode.DIGEST_MISMATCH in codes
    assert RecoveryCode.STALE_GATE in codes
    assert kernel.progress(stage) == (0, 1)
    kernel.close()


def test_clean_recovery_records_no_action(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("YOUTH_SAFE", "STAGE1", "CREATE", PROMPT, "b" * 64)
    assert recover(kernel, workflow)[0].code is RecoveryCode.CLEAN
    kernel.close()


def test_disk_write_failure_creates_no_database_artifact(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    kernel, _, _, _, call = _active(tmp_path)

    def fail_write(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("disk full")

    monkeypatch.setattr(kernel.store, "put", fail_write)
    with pytest.raises(OSError, match="disk full"):
        kernel.register_candidate(call, b"bytes", "image/png", "STAGE1")
    assert kernel.db.connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
    kernel.close()
