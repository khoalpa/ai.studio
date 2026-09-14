from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from audio_story.adapters.image import (
    DeterministicMockImageAdapter,
    ImageRequest,
    ImageResourceError,
)
from audio_story.adapters.ocr import LocalOcrAdapter, OcrEvidence, OcrRequest
from audio_story.domain.state import CallStatus, WorkflowStatus
from audio_story.workflows import WorkflowKernel
from audio_story.workflows.image_transaction import (
    ProductionOcrJob,
    ProductionTypographyJob,
    SemanticImageGateResult,
    generate_single_image,
)
from audio_story.workflows.typography_production import ProductionTypographyConfig

FONT = Path(r"C:\Windows\Fonts\DejaVuSans.ttf")
FONT_SHA256 = "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954"


class _TwoPhaseOcr(LocalOcrAdapter):
    def __init__(self, final_text: str = "Chuyện kể") -> None:
        self.calls = 0
        self.final_text = final_text

    def inspect(
        self, request: OcrRequest, image_bytes: bytes, cancellation: Event | None = None
    ) -> OcrEvidence:
        self.calls += 1
        text = "" if self.calls == 1 else self.final_text
        return OcrEvidence(
            text,
            0.9,
            (0, 0, 1, 1),
            "test-ocr",
            str(self.calls) * 64,
            normalized_result_digest=__import__("hashlib").sha256(text.encode()).hexdigest(),
            page_identity=request.page_identity,
        )


def test_single_image_transaction_commits_only_after_png_qa(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("ADULT_STANDARD", "STAGE2", "CREATE", "a" * 64, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE2", "c" * 64)
    request = ImageRequest(
        "landscape_0001.png", "d" * 64, "e" * 64, "mock", 4, 1, 32, 16, "PNG", 1, "tx", "call"
    )
    result = generate_single_image(
        kernel,
        stage,
        request,
        DeterministicMockImageAdapter(),
        owner_stage="STAGE2",
        artifact_role="LANDSCAPE",
    )
    assert result.status == "AUTHORITATIVE"
    assert result.artifact_id is not None
    assert kernel.progress(stage) == (1, 1)
    assert kernel.db.connection.execute("SELECT COUNT(*) FROM artifact_bindings").fetchone()[0] == 1
    authority = kernel.db.connection.execute(
        "SELECT delivery_status,gate_status,immutable FROM image_artifact_authority"
    ).fetchone()
    assert tuple(authority) == ("AUTHORITATIVE", "PASS", 1)
    kernel.close()


@pytest.mark.skipif(not FONT.is_file(), reason="pinned production font is unavailable")
def test_single_image_transaction_commits_verified_typography_artifact(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path / "runtime")
    workflow = kernel.create_workflow("ADULT_STANDARD", "STAGE2", "CREATE", "a" * 64, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE2", "c" * 64)
    output = tmp_path / "work" / "cover.png"
    result = generate_single_image(
        kernel,
        stage,
        ImageRequest(
            "landscape_0001.png", "d" * 64, "e" * 64, "mock", 4, 1, 256, 256, "PNG", 1, "tx", "call"
        ),
        DeterministicMockImageAdapter(),
        owner_stage="STAGE2",
        artifact_role="LANDSCAPE",
        typography=ProductionTypographyJob(
            "Chuyện kể",
            output,
            ProductionTypographyConfig(
                FONT,
                FONT_SHA256,
                "DejaVu Sans OS-installed",
                "PROJECT_OWNER_CONFIRMED",
                20,
                24,
            ),
        ),
    )

    assert result.status == "AUTHORITATIVE"
    assert result.typography is not None
    assert result.digest == result.typography.final_sha256
    assert output.read_bytes() == kernel.store.read(
        kernel.db.connection.execute(
            "SELECT relative_path FROM artifacts WHERE id=?", (result.artifact_id,)
        ).fetchone()[0]
    )
    assert {
        row[0]
        for row in kernel.db.connection.execute(
            "SELECT gate_id FROM gate_results WHERE artifact_id=? AND is_current=1",
            (result.artifact_id,),
        )
    } == {"IMAGE_QA_GATE", "TYPOGRAPHY_GATE"}
    assert kernel.progress(stage) == (1, 1)
    kernel.close()


@pytest.mark.skipif(not FONT.is_file(), reason="pinned production font is unavailable")
def test_typography_failure_cannot_bind_or_advance_transaction(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path / "runtime")
    workflow = kernel.create_workflow("ADULT_STANDARD", "STAGE2", "CREATE", "a" * 64, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE2", "c" * 64)
    result = generate_single_image(
        kernel,
        stage,
        ImageRequest(
            "landscape_0001.png", "d" * 64, "e" * 64, "mock", 4, 1, 128, 128, "PNG", 1, "tx", "call"
        ),
        DeterministicMockImageAdapter(),
        owner_stage="STAGE2",
        artifact_role="LANDSCAPE",
        max_attempts=1,
        typography=ProductionTypographyJob(
            "A title that cannot fit inside this deliberately tiny image",
            tmp_path / "work" / "cover.png",
            ProductionTypographyConfig(
                FONT,
                FONT_SHA256,
                "DejaVu Sans OS-installed",
                "PROJECT_OWNER_CONFIRMED",
                64,
                48,
            ),
        ),
    )

    assert result.status == "VISUAL_GATE_FAIL"
    assert kernel.progress(stage) == (0, 1)
    assert kernel.db.connection.execute("SELECT COUNT(*) FROM artifact_bindings").fetchone()[0] == 0
    assert (
        kernel.db.connection.execute("SELECT failure_code FROM generation_calls").fetchone()[0]
        == "TYPO001_TEXT_LAYOUT"
    )
    kernel.close()


@pytest.mark.skipif(not FONT.is_file(), reason="pinned production font is unavailable")
def test_two_phase_ocr_is_required_before_typography_commit(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path / "runtime")
    workflow = kernel.create_workflow("ADULT_STANDARD", "STAGE2", "CREATE", "a" * 64, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE2", "c" * 64)
    ocr = _TwoPhaseOcr()
    result = generate_single_image(
        kernel,
        stage,
        ImageRequest(
            "cover.png", "d" * 64, "e" * 64, "mock", 4, 1, 256, 256, "PNG", 1, "tx", "call"
        ),
        DeterministicMockImageAdapter(),
        owner_stage="STAGE2",
        artifact_role="LANDSCAPE",
        typography=ProductionTypographyJob(
            "Chuyện kể",
            tmp_path / "cover.png",
            ProductionTypographyConfig(
                FONT, FONT_SHA256, "DejaVu Sans OS-installed", "PROJECT_OWNER_CONFIRMED", 20, 24
            ),
        ),
        ocr=ProductionOcrJob(ocr, ("vie",), "Chuyện kể", 0.8),
    )

    failure = kernel.db.connection.execute(
        "SELECT failure_code FROM generation_calls WHERE id=?", (result.generation_call_id,)
    ).fetchone()[0]
    assert result.status == "AUTHORITATIVE", failure
    assert ocr.calls == 2 and result.base_ocr is not None and result.final_ocr is not None
    assert {
        row[0]
        for row in kernel.db.connection.execute(
            "SELECT gate_id FROM gate_results WHERE artifact_id=?", (result.artifact_id,)
        )
    } == {"IMAGE_QA_GATE", "TYPOGRAPHY_GATE", "OCR_GATE"}
    kernel.close()


class _OomAdapter(DeterministicMockImageAdapter):
    def __init__(self, *, unload_fails: bool = False) -> None:
        self.unload_fails = unload_fails
        self.calls: list[str] = []

    def generate_image(self, request: ImageRequest, cancellation: Event):  # type: ignore[no-untyped-def]
        self.calls.append(request.generation_call_id)
        raise ImageResourceError("injected OOM")

    def unload(self) -> None:
        if self.unload_fails:
            raise RuntimeError("injected unload failure")


class _CancelAfterResponseAdapter(DeterministicMockImageAdapter):
    def __init__(self, cancellation: Event) -> None:
        self.cancellation = cancellation
        self.cancelled_call: str | None = None

    def generate_image(self, request: ImageRequest, cancellation: Event):  # type: ignore[no-untyped-def]
        response = super().generate_image(request, cancellation)
        self.cancellation.set()
        return response

    def cancel(self, generation_call_id: str) -> None:
        self.cancelled_call = generation_call_id


@pytest.mark.parametrize("unload_fails", [False, True])
def test_oom_retry_exhaustion_closes_calls_and_releases_gpu_semaphore(
    tmp_path: Path, unload_fails: bool
) -> None:
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("ADULT_STANDARD", "STAGE2", "CREATE", "a" * 64, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE2", "c" * 64)
    adapter = _OomAdapter(unload_fails=unload_fails)
    result = generate_single_image(
        kernel,
        stage,
        ImageRequest(
            "landscape_0001.png", "d" * 64, "e" * 64, "mock", 4, 1, 32, 16, "PNG", 1, "tx", "call"
        ),
        adapter,
        owner_stage="STAGE2",
        artifact_role="LANDSCAPE",
        max_attempts=2,
    )
    assert result.status == "VISUAL_GATE_FAIL"
    assert len(adapter.calls) == 2 and len(set(adapter.calls)) == 2
    rows = kernel.db.connection.execute(
        "SELECT status,failure_code FROM generation_calls ORDER BY attempt_index"
    ).fetchall()
    assert [(row["status"], row["failure_code"]) for row in rows] == [
        (CallStatus.FAILED, "IMG012_OOM"),
        (CallStatus.FAILED, "IMG012_OOM"),
    ]
    assert kernel.progress(stage) == (0, 1)
    with __import__("audio_story.adapters.image", fromlist=["gpu_job"]).gpu_job():
        pass
    kernel.close()


def test_semantic_gate_retry_pass_commits_authority(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("ADULT_STANDARD", "STAGE1", "CREATE", "a" * 64, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE1", "c" * 64)
    outcomes = iter(("FAIL", "PASS"))

    def assess(data: bytes, request: ImageRequest) -> SemanticImageGateResult:
        status = next(outcomes)
        return SemanticImageGateResult(
            status,
            {"image_sha256": __import__("hashlib").sha256(data).hexdigest()},
            "mock-vlm",
            "test",
        )

    result = generate_single_image(
        kernel,
        stage,
        ImageRequest(
            "character_0001.png", "d" * 64, "e" * 64, "mock", 4, 1, 32, 16, "PNG", 1, "tx", "call"
        ),
        DeterministicMockImageAdapter(),
        owner_stage="STAGE1",
        artifact_role="CHARACTER_ASSET",
        max_attempts=2,
        semantic_assessor=assess,
    )
    assert result.status == "AUTHORITATIVE"
    assert kernel.progress(stage) == (1, 1)
    rows = kernel.db.connection.execute(
        "SELECT status,failure_code FROM generation_calls ORDER BY attempt_index"
    ).fetchall()
    assert [(row["status"], row["failure_code"]) for row in rows] == [
        (CallStatus.FAILED, "IMG018_SEMANTIC_GATE_FAIL"),
        (CallStatus.FINISHED, None),
    ]
    kernel.close()


@pytest.mark.parametrize("when", ["before_request", "after_response", "before_binding"])
def test_cancellation_never_binds_or_advances_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("ADULT_STANDARD", "STAGE2", "CREATE", "a" * 64, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE2", "c" * 64)
    cancellation = Event()
    adapter: DeterministicMockImageAdapter
    if when == "before_request":
        cancellation.set()
        adapter = DeterministicMockImageAdapter()
    elif when == "after_response":
        adapter = _CancelAfterResponseAdapter(cancellation)
    else:
        adapter = DeterministicMockImageAdapter()
        original = kernel.record_gate

        def record_then_cancel(*args: object, **kwargs: object) -> str:
            gate = original(*args, **kwargs)  # type: ignore[arg-type]
            cancellation.set()
            return gate

        monkeypatch.setattr(kernel, "record_gate", record_then_cancel)
    result = generate_single_image(
        kernel,
        stage,
        ImageRequest(
            "landscape_0001.png", "d" * 64, "e" * 64, "mock", 4, 1, 32, 16, "PNG", 1, "tx", "call"
        ),
        adapter,
        owner_stage="STAGE2",
        artifact_role="LANDSCAPE",
        cancellation=cancellation,
    )
    assert result.status == "VISUAL_GATE_FAIL"
    assert kernel.progress(stage) == (0, 1)
    assert kernel.db.connection.execute("SELECT COUNT(*) FROM artifact_bindings").fetchone()[0] == 0
    assert (
        kernel.db.connection.execute(
            "SELECT COUNT(*) FROM generation_calls "
            "WHERE status=? AND failure_code='IMG004_CANCELLED'",
            (CallStatus.FAILED,),
        ).fetchone()[0]
        == 1
    )
    kernel.close()
