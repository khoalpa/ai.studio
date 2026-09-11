from __future__ import annotations

from pathlib import Path

import pytest

from audio_story.domain.state import (
    CallStatus,
    DetectorClass,
    GateStatus,
    StageStatus,
    WorkflowStatus,
)
from audio_story.workflows import KernelError, WorkflowKernel

PROMPT = "4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27"
CAPSULE = "a" * 64


def _kernel(tmp_path: Path) -> tuple[WorkflowKernel, str, str]:
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("YOUTH_SAFE", "STAGE1", "CREATE", PROMPT, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE1", CAPSULE)
    kernel.transition_stage(stage, StageStatus.GENERATING)
    return kernel, workflow, stage


def _candidate(
    kernel: WorkflowKernel, stage: str, payload: bytes = b"asset"
) -> tuple[str, str, str]:
    transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "cover.png")
    call = kernel.begin_generation_call(transaction, "c" * 64)
    artifact = kernel.register_candidate(
        call,
        payload,
        "image/png",
        "STAGE1",
        artifact_role="CHARACTER_ASSET",
        dependency_digest="d" * 64,
    )
    kernel.finish_generation_call(call, CallStatus.FINISHED, "e" * 64)
    return transaction, call, artifact


def _pass_gate(kernel: WorkflowKernel, stage: str, artifact: str) -> None:
    kernel.record_gate(
        stage,
        artifact,
        "VALIDATE",
        DetectorClass.DETERMINISTIC,
        GateStatus.PASS,
        {"ok": True},
        PROMPT,
        CAPSULE,
        "1.0",
    )


def test_transaction_retry_commit_progress_events_and_restart(tmp_path: Path) -> None:
    kernel, workflow, stage = _kernel(tmp_path)
    transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "cover.png")
    assert kernel.get_or_create_transaction(stage, "LANDSCAPE", "cover.png") == transaction
    first_call = kernel.begin_generation_call(transaction, "c" * 64)
    kernel.finish_generation_call(first_call, CallStatus.TIMED_OUT, failure_code="TIMEOUT")
    second_call = kernel.begin_generation_call(transaction, "c" * 64)
    assert second_call != first_call
    artifact = kernel.register_candidate(second_call, b"final", "image/png", "STAGE1")
    kernel.finish_generation_call(second_call, CallStatus.FINISHED, "d" * 64)
    assert kernel.progress(stage) == (0, 1)
    _pass_gate(kernel, stage, artifact)
    assert kernel.commit_artifact(transaction, artifact) == artifact
    assert kernel.commit_artifact(transaction, artifact) == artifact
    assert kernel.progress(stage) == (1, 1)
    events = kernel.db.connection.execute(
        "SELECT sequence_no,payload_json,payload_digest FROM events WHERE workflow_id=? ORDER BY sequence_no",
        (workflow,),
    ).fetchall()
    assert [row["sequence_no"] for row in events] == list(range(1, len(events) + 1))
    from audio_story.validation.canonical import sha256_bytes

    assert all(
        sha256_bytes(row["payload_json"].encode()) == row["payload_digest"] for row in events
    )
    kernel.close()
    reopened = WorkflowKernel(tmp_path)
    assert reopened.progress(stage) == (1, 1)
    assert reopened.inspect_workflow(workflow)["canonical_prompt_sha256"] == PROMPT
    reopened.close()


def test_double_commit_different_bytes_and_read_only_mutation_are_rejected(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction, _, artifact = _candidate(kernel, stage, b"one")
    _pass_gate(kernel, stage, artifact)
    kernel.commit_artifact(transaction, artifact)
    other_transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "other.png")
    call = kernel.begin_generation_call(other_transaction, "c" * 64)
    other = kernel.register_candidate(call, b"two", "image/png", "STAGE1")
    with pytest.raises(KernelError, match="different bytes"):
        kernel.commit_artifact(transaction, other)
    with pytest.raises(KernelError) as caught:
        kernel.quarantine_artifact(artifact, stage)
    assert caught.value.code == "RK009_READ_ONLY_MUTATION"
    kernel.close()


def test_rejected_candidate_and_stale_gate_do_not_increase_progress(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction, _, artifact = _candidate(kernel, stage)
    kernel.record_gate(
        stage,
        artifact,
        "PNG",
        DetectorClass.DETERMINISTIC,
        GateStatus.PASS,
        {"ok": True},
        PROMPT,
        CAPSULE,
        "1.0",
        "old",
    )
    assert kernel.mark_dependency_stale(artifact, "new") == 1
    assert kernel.db.connection.execute("SELECT is_current FROM gate_results").fetchone()[0] == 0
    with pytest.raises(KernelError) as caught:
        kernel.commit_artifact(transaction, artifact)
    assert caught.value.code == "RK016_GATE_NOT_CURRENT_PASS"
    kernel.quarantine_artifact(artifact, stage)
    assert kernel.progress(stage) == (0, 1)
    assert transaction
    kernel.close()


def test_owner_mismatch_and_invalid_call_finish_fail_before_publish(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "cover.png")
    call = kernel.begin_generation_call(transaction, "c" * 64)
    with pytest.raises(KernelError) as caught:
        kernel.register_candidate(call, b"bad", "image/png", "STAGE2")
    assert caught.value.code == "RK014_OWNER_STAGE_MISMATCH"
    with pytest.raises(KernelError) as caught:
        kernel.register_candidate(
            call, b"bad-role", "image/png", "STAGE1", artifact_role="PORTRAIT"
        )
    assert caught.value.code == "RK015_ROLE_OWNER_MISMATCH"
    with pytest.raises(KernelError) as caught:
        kernel.finish_generation_call(call, CallStatus.RUNNING)
    assert caught.value.code == "RK008_INVALID_CALL_FINISH"
    kernel.close()


def test_workspace_lease_detects_conflict_and_allows_stale_takeover(tmp_path: Path) -> None:
    first = WorkflowKernel(tmp_path)
    second = WorkflowKernel(tmp_path)
    first.acquire_lease("workspace", "owner-a", 30)
    with pytest.raises(KernelError) as caught:
        second.acquire_lease("workspace", "owner-b", 30)
    assert caught.value.code == "RK012_LEASE_CONFLICT"
    first.db.connection.execute(
        "UPDATE workspace_leases SET expires_at='2000-01-01T00:00:00Z' WHERE workspace_id='workspace'"
    )
    second.acquire_lease("workspace", "owner-b", 30)
    first.close()
    second.close()


def test_store_dedup_and_commit_digest_mismatch_are_guarded(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction, _, artifact = _candidate(kernel, stage, b"same")
    second_transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "second.png")
    second_call = kernel.begin_generation_call(second_transaction, "f" * 64)
    duplicate = kernel.register_candidate(second_call, b"same", "image/png", "STAGE1")
    assert duplicate == artifact
    _pass_gate(kernel, stage, artifact)
    row = kernel.db.connection.execute(
        "SELECT relative_path FROM artifacts WHERE id=?", (artifact,)
    ).fetchone()
    (kernel.workspace / row["relative_path"]).write_bytes(b"tampered")
    with pytest.raises(KernelError) as caught:
        kernel.commit_artifact(transaction, artifact)
    assert caught.value.code == "RK011_ARTIFACT_DIGEST_MISMATCH"
    kernel.close()


def test_unvalidated_candidate_cannot_commit(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction, _, artifact = _candidate(kernel, stage)
    with pytest.raises(KernelError) as caught:
        kernel.commit_artifact(transaction, artifact)
    assert caught.value.code == "RK017_CANDIDATE_NOT_VALIDATED"
    kernel.close()


def test_two_instances_claim_same_logical_transaction(tmp_path: Path) -> None:
    first, _, stage = _kernel(tmp_path)
    second = WorkflowKernel(tmp_path)
    first_id = first.get_or_create_transaction(stage, "LANDSCAPE", "shared.png")
    second_id = second.get_or_create_transaction(stage, "LANDSCAPE", "shared.png")
    assert second_id == first_id
    first.close()
    second.close()


def test_call_and_commit_enforce_transaction_lineage(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    first_transaction, _, first_artifact = _candidate(kernel, stage, b"first")
    second_transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "second.png")
    second_call = kernel.begin_generation_call(second_transaction, "d" * 64)
    second_artifact = kernel.register_candidate(
        second_call,
        b"second",
        "image/png",
        "STAGE1",
        artifact_role="CHARACTER_ASSET",
    )
    kernel.finish_generation_call(second_call, CallStatus.FINISHED, "e" * 64)
    _pass_gate(kernel, stage, first_artifact)
    _pass_gate(kernel, stage, second_artifact)

    with pytest.raises(KernelError) as caught:
        kernel.commit_artifact(first_transaction, second_artifact)
    assert caught.value.code == "RK019_ARTIFACT_TRANSACTION_MISMATCH"

    kernel.commit_artifact(first_transaction, first_artifact)
    with pytest.raises(KernelError) as caught:
        kernel.begin_generation_call(first_transaction, "f" * 64)
    assert caught.value.code == "RK018_TRANSACTION_NOT_CALLABLE"

    active_transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "active.png")
    kernel.begin_generation_call(active_transaction, "a" * 64)
    with pytest.raises(KernelError) as caught:
        kernel.begin_generation_call(active_transaction, "b" * 64)
    assert caught.value.code == "RK018_TRANSACTION_NOT_CALLABLE"
    kernel.close()
