from __future__ import annotations

import json
from pathlib import Path
from threading import Event

import pytest

from audio_story.adapters.llm import (
    AdapterPolicy,
    DeterministicMockAdapter,
    LLMAdapterError,
    PromptCapsule,
    StructuredGenerationService,
)
from audio_story.adapters.llm.base import LLMAdapterError as BackendError
from audio_story.domain.state import CallStatus, WorkflowStatus
from audio_story.validation.validate_story_runtime import RESULT_ORDER
from audio_story.workflows import WorkflowKernel
from audio_story.workflows.recovery import recover

PROMPT = "4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27"
CAPSULE = PromptCapsule(b'{"active":"capsule"}', "a" * 64)


def _valid_result() -> bytes:
    value = {
        "schema_version": "1.0",
        "validator_name": "mock",
        "validator_version": "1.0",
        "validator_source": "M4_TEST",
        "canonical_prompt_sha256": PROMPT,
        "invocation": {},
        "input_bindings": [],
        "overall_status": "PASS",
        "checks": [],
        "findings": [],
        "evidence_digests": [],
        "result_digest": "",
        "result_self_reopen_status": "NOT_APPLICABLE",
    }
    return json.dumps(value, separators=(",", ":")).encode()


def _wrong_order_result() -> bytes:
    value = json.loads(_valid_result())
    return json.dumps(dict(reversed(tuple(value.items()))), separators=(",", ":")).encode()


def _kernel(tmp_path: Path) -> tuple[WorkflowKernel, str, str, str]:
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("YOUTH_SAFE", "STAGE1", "CREATE", PROMPT, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE1", CAPSULE.digest)
    transaction = kernel.get_or_create_transaction(
        stage, "NONE", "deterministic_validation_result.json"
    )
    return kernel, workflow, stage, transaction


def _run(
    service: StructuredGenerationService,
    transaction: str,
    stage: str,
    *,
    cancellation: Event | None = None,
    requested_output_tokens: int | None = None,
) -> str:
    return service.generate_and_commit(
        transaction,
        stage,
        "STAGE1",
        "ARCHIVE",
        "deterministic_validation_result.json",
        CAPSULE,
        "produce validation evidence",
        PROMPT,
        "YOUTH_SAFE",
        "CREATE",
        RESULT_ORDER,
        cancellation,
        requested_output_tokens,
    )


def test_validated_output_commits_with_call_metadata_and_lineage(tmp_path: Path) -> None:
    kernel, _, stage, transaction = _kernel(tmp_path)
    service = StructuredGenerationService(
        kernel, DeterministicMockAdapter(responses=[_valid_result()])
    )
    artifact = _run(service, transaction, stage)
    assert kernel.progress(stage) == (1, 1)
    row = kernel.db.connection.execute("SELECT * FROM generation_calls").fetchone()
    assert row["response_digest"]
    assert row["model_identity"] == "mock-local-deterministic"
    assert row["adapter_version"] == "1.0"
    assert row["duration_ms"] == 0
    assert row["termination_reason"] == "COMPLETED"
    binding = kernel.db.connection.execute(
        "SELECT artifact_id FROM artifact_bindings WHERE transaction_id=?", (transaction,)
    ).fetchone()
    assert binding["artifact_id"] == artifact
    kernel.close()


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema_version":"1.0"',
        b'{"schema_version":"1.0","schema_version":"1.0"}',
        b'{"schema_version":"1.0","x":NaN}',
        b'{"schema_version":"1.0","x":Infinity}',
        _valid_result() + b" trailing",
        _valid_result().replace(b'"1.0"', b'"9.9"', 1),
        _wrong_order_result(),
        b'{"schema_version":"1.0"}',
    ],
)
def test_invalid_structured_output_never_commits_or_increases_progress(
    tmp_path: Path, payload: bytes
) -> None:
    kernel, _, stage, transaction = _kernel(tmp_path)
    service = StructuredGenerationService(
        kernel,
        DeterministicMockAdapter(responses=[payload, payload]),
        AdapterPolicy(max_attempts=2),
    )
    with pytest.raises(LLMAdapterError) as caught:
        _run(service, transaction, stage)
    assert caught.value.code == "LLM005_RETRY_EXHAUSTED"
    assert kernel.progress(stage) == (0, 1)
    assert kernel.db.connection.execute("SELECT COUNT(*) FROM artifact_bindings").fetchone()[0] == 0
    assert kernel.db.connection.execute("SELECT COUNT(*) FROM generation_calls").fetchone()[0] == 2
    kernel.close()


def test_not_verified_schema_cannot_publish(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("YOUTH_SAFE", "STAGE1", "CREATE", PROMPT, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE1", CAPSULE.digest)
    transaction = kernel.get_or_create_transaction(stage, "NONE", "story.json")
    service = StructuredGenerationService(
        kernel,
        DeterministicMockAdapter(responses=[b'{"schema_version":"2.3"}']),
        AdapterPolicy(max_attempts=1),
    )
    with pytest.raises(LLMAdapterError):
        service.generate_and_commit(
            transaction,
            stage,
            "STAGE1",
            "STORY",
            "story.json",
            CAPSULE,
            "story",
            PROMPT,
            "YOUTH_SAFE",
            "CREATE",
        )
    assert kernel.progress(stage) == (0, 1)
    kernel.close()


def test_budget_cancellation_retry_and_restart_recovery(tmp_path: Path) -> None:
    kernel, workflow, stage, transaction = _kernel(tmp_path)
    too_small = StructuredGenerationService(
        kernel, DeterministicMockAdapter(), AdapterPolicy(max_context_chars=4)
    )
    with pytest.raises(LLMAdapterError) as caught:
        _run(too_small, transaction, stage)
    assert caught.value.code == "LLM002_CONTEXT_BUDGET"

    service = StructuredGenerationService(
        kernel, DeterministicMockAdapter(), AdapterPolicy(max_output_tokens=4)
    )
    with pytest.raises(LLMAdapterError) as caught:
        _run(service, transaction, stage, requested_output_tokens=5)
    assert caught.value.code == "LLM013_TOKEN_BUDGET"

    cancelled = Event()
    cancelled.set()
    with pytest.raises(LLMAdapterError) as caught:
        _run(service, transaction, stage, cancellation=cancelled)
    assert caught.value.code == "LLM004_CANCELLED"
    kernel.close()

    reopened = WorkflowKernel(tmp_path)
    decisions = recover(reopened, workflow)
    assert all(decision.code.value != "RK_CALL_INTERRUPTED" for decision in decisions)
    assert reopened.progress(stage) == (0, 1)
    reopened.close()


def test_backend_failure_retries_are_exhausted_without_artifact(tmp_path: Path) -> None:
    kernel, _, stage, transaction = _kernel(tmp_path)
    failures = [
        BackendError("LLM003_TIMEOUT", "timeout"),
        BackendError("LLM006_BACKEND_FAILURE", "crash"),
    ]
    service = StructuredGenerationService(
        kernel, DeterministicMockAdapter(failures=failures), AdapterPolicy(max_attempts=2)
    )
    with pytest.raises(LLMAdapterError) as caught:
        _run(service, transaction, stage)
    assert caught.value.code == "LLM005_RETRY_EXHAUSTED"
    assert kernel.db.connection.execute("SELECT COUNT(*) FROM generation_calls").fetchone()[0] == 2
    assert kernel.db.connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
    assert kernel.progress(stage) == (0, 1)
    kernel.close()


def test_restart_between_generation_and_validation_is_recoverable(tmp_path: Path) -> None:
    kernel, workflow, stage, transaction = _kernel(tmp_path)
    call = kernel.begin_generation_call(
        transaction, "c" * 64, model_identity="mock-local", adapter_version="1.0"
    )
    kernel.register_candidate(
        call,
        _valid_result(),
        "application/json",
        "STAGE1",
        artifact_role="ARCHIVE",
        dependency_digest=CAPSULE.digest,
    )
    kernel.close()

    reopened = WorkflowKernel(tmp_path)
    decisions = recover(reopened, workflow)
    assert any(decision.code.value == "RK_CALL_INTERRUPTED" for decision in decisions)
    row = reopened.db.connection.execute(
        "SELECT status FROM generation_calls WHERE id=?", (call,)
    ).fetchone()
    assert row["status"] == CallStatus.TIMED_OUT
    assert reopened.progress(stage) == (0, 1)
    reopened.close()


def test_capsule_and_canonical_binding_mismatch_fails_before_call(tmp_path: Path) -> None:
    kernel, _, stage, transaction = _kernel(tmp_path)
    service = StructuredGenerationService(kernel, DeterministicMockAdapter())
    with pytest.raises(LLMAdapterError) as caught:
        service.generate_and_commit(
            transaction,
            stage,
            "STAGE1",
            "ARCHIVE",
            "deterministic_validation_result.json",
            PromptCapsule(CAPSULE.canonical_bytes, "f" * 64),
            "instruction",
            PROMPT,
            "YOUTH_SAFE",
            "CREATE",
            RESULT_ORDER,
        )
    assert caught.value.code == "LLM012_BINDING_MISMATCH"
    assert kernel.db.connection.execute("SELECT COUNT(*) FROM generation_calls").fetchone()[0] == 0
    kernel.close()


def test_unexpected_backend_exception_closes_call_and_allows_retry_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, _, stage, transaction = _kernel(tmp_path)
    adapter = DeterministicMockAdapter()

    def crash(*args: object, **kwargs: object) -> object:
        raise RuntimeError("unexpected backend crash")

    monkeypatch.setattr(DeterministicMockAdapter, "generate_structured", crash)
    service = StructuredGenerationService(kernel, adapter, AdapterPolicy(max_attempts=1))
    with pytest.raises(LLMAdapterError) as caught:
        _run(service, transaction, stage)
    assert caught.value.code == "LLM005_RETRY_EXHAUSTED"
    row = kernel.db.connection.execute(
        "SELECT status,failure_code FROM generation_calls"
    ).fetchone()
    assert row["status"] == CallStatus.FAILED
    assert row["failure_code"] == "LLM014_EXECUTION_FAILURE"
    kernel.close()
