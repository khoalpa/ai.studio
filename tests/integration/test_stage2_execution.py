from __future__ import annotations

from pathlib import Path
from threading import Event

from audio_story.adapters.image import (
    DeterministicMockImageAdapter,
    ImageAdapterError,
    ImageRequest,
    ImageResponse,
)
from audio_story.adapters.llm.mock import DeterministicMockAdapter
from audio_story.domain.stage1 import Stage1Request
from audio_story.domain.state import WorkflowStatus
from audio_story.validation.stage2 import load_stage1_package, validate_stage2_progress_bytes
from audio_story.workflows import Stage1Service, WorkflowKernel
from audio_story.workflows.stage2_execution import Stage2ZoneExecutor
from audio_story.workflows.stage2_planning import build_stage2_zone_plan


class _FailDevelopmentOnce(DeterministicMockImageAdapter):
    def __init__(self) -> None:
        self.failed = False

    def generate_image(self, request: ImageRequest, cancellation: Event) -> ImageResponse:
        if request.basename == "development.png" and not self.failed:
            self.failed = True
            raise ImageAdapterError("IMG099_TEST_FAILURE", "injected targeted repair fixture")
        return super().generate_image(request, cancellation)


def test_stage2_mock_queue_resumes_and_repairs_only_failed_basename(tmp_path: Path) -> None:
    canonical = Path(__file__).parents[2] / "canonical" / "ChatGPT_prompt_v3.16.13.txt"
    kernel = WorkflowKernel(tmp_path)
    stage1 = Stage1Service(kernel, DeterministicMockAdapter(), canonical).start(
        Stage1Request("YOUTH_SAFE", duration_minutes=12, duration_confirmed=True, test_mode=True)
    )
    assert stage1.package_path is not None
    source = load_stage1_package(stage1.package_path, test_mode=True)
    plan = build_stage2_zone_plan(source)
    workflow = kernel.create_workflow("YOUTH_SAFE", "STAGE2", "CREATE", "a" * 64, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE2", "c" * 64)
    progress = tmp_path / "outputs" / workflow / "stage_image_progress.json"
    adapter = _FailDevelopmentOnce()
    executor = Stage2ZoneExecutor(kernel, stage, source, plan, adapter, progress)

    interrupted = executor.execute_all()
    assert interrupted.status == "IN_PROGRESS"
    assert interrupted.committed_count == 3
    assert interrupted.next_pending_basename == "development.png"
    exposed = validate_stage2_progress_bytes(progress.read_bytes())
    assert exposed["committed_count"] == 3
    assert exposed["failed_count"] == 0

    completed = executor.execute_all()
    assert completed.status == "READY_FOR_AGGREGATE_GATES"
    assert completed.committed_count == 10
    assert completed.next_pending_basename is None
    assert completed.progress_path is None
    rows = kernel.db.connection.execute(
        "SELECT basename,status FROM asset_transactions WHERE stage_run_id=? ORDER BY created_at",
        (stage,),
    ).fetchall()
    assert [row["basename"] for row in rows] == list(plan.execution_queue)
    assert all(row["status"] == "COMMITTED" for row in rows)
    attempts = kernel.db.connection.execute(
        "SELECT COUNT(*) FROM generation_calls g "
        "JOIN asset_transactions t ON t.id=g.transaction_id "
        "WHERE t.stage_run_id=? AND t.basename='development.png'",
        (stage,),
    ).fetchone()[0]
    assert attempts == 2
    assert (
        kernel.db.connection.execute(
            "SELECT COUNT(*) FROM artifact_bindings b "
            "JOIN asset_transactions t ON t.id=b.transaction_id "
            "WHERE t.stage_run_id=? AND b.role='COMMITTED'",
            (stage,),
        ).fetchone()[0]
        == 10
    )
    kernel.close()
