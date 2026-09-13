"""Single-asset image transaction orchestration on the M3 kernel."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event

from audio_story.adapters.image.base import (
    DeliveryStatus,
    ImageAdapterError,
    ImageRequest,
    LocalImageAdapter,
)
from audio_story.adapters.image.resource import ImageResourceError, gpu_job
from audio_story.domain.state import CallStatus, DetectorClass, GateStatus
from audio_story.validation.canonical import sha256_bytes
from audio_story.validation.images import PngInfo, validate_image_qa
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.package_quarantine import ImageManifestEntry, validate_image_package
from audio_story.workflows.typography import TypographyError
from audio_story.workflows.typography_production import (
    ProductionTypographyConfig,
    ProductionTypographyEvidence,
    render_verified_production_cover,
)


@dataclass(frozen=True, slots=True)
class ProductionTypographyJob:
    text: str
    output_path: Path
    config: ProductionTypographyConfig


@dataclass(frozen=True, slots=True)
class ImageTransactionResult:
    status: str
    transaction_id: str
    generation_call_id: str | None
    artifact_id: str | None
    digest: str | None
    qa: PngInfo | None = None
    typography: ProductionTypographyEvidence | None = None


def generate_single_image(
    kernel: WorkflowKernel,
    stage_id: str,
    request: ImageRequest,
    adapter: LocalImageAdapter,
    *,
    owner_stage: str,
    artifact_role: str,
    cancellation: Event | None = None,
    max_attempts: int = 2,
    typography: ProductionTypographyJob | None = None,
) -> ImageTransactionResult:
    """Generate exactly one PNG, validate it, and commit only a PASS candidate."""
    cancellation = cancellation if cancellation is not None else Event()
    transaction_id = kernel.get_or_create_transaction(stage_id, owner_stage, request.basename)
    last_call_id: str | None = None
    for _ in range(max_attempts):
        call_id = kernel.begin_generation_call(
            transaction_id, sha256_bytes(_request_bytes(request))
        )
        last_call_id = call_id
        active_request = replace(
            request,
            transaction_id=transaction_id,
            generation_call_id=call_id,
        )
        try:
            _raise_if_cancelled(cancellation, adapter, call_id)
            with gpu_job():
                response = adapter.generate_image(active_request, cancellation)
            _raise_if_cancelled(cancellation, adapter, call_id)
            base_info = validate_image_qa(
                response.content,
                active_request.basename,
                expected_dimensions=(
                    active_request.requested_width,
                    active_request.requested_height,
                ),
            )
            artifact_bytes = response.content
            typography_evidence = None
            if typography is not None:
                typography_evidence = render_verified_production_cover(
                    response.content,
                    base_info.sha256,
                    typography.text,
                    typography.output_path,
                    typography.config,
                )
                artifact_bytes = typography.output_path.read_bytes()
            info = validate_image_qa(
                artifact_bytes,
                active_request.basename,
                expected_dimensions=(
                    active_request.requested_width,
                    active_request.requested_height,
                ),
            )
            validate_image_package(
                (
                    ImageManifestEntry(
                        basename=active_request.basename,
                        owner_stage=owner_stage,
                        character_id="",
                        digest=info.sha256,
                        size=len(artifact_bytes),
                        status=DeliveryStatus.AUTHORITATIVE,
                        relative_path=f"images/{active_request.basename}",
                        transaction_id=transaction_id,
                        generation_call_id=call_id,
                        evidence_digest=info.sha256,
                    ),
                ),
                (active_request.basename,),
            )
            artifact_id = kernel.register_candidate(
                call_id,
                artifact_bytes,
                "image/png",
                owner_stage,
                artifact_role=artifact_role,
                dependency_digest=active_request.workflow_digest,
            )
            kernel.record_gate(
                stage_id,
                artifact_id,
                "IMAGE_QA_GATE",
                DetectorClass.DETERMINISTIC,
                GateStatus.PASS,
                {"sha256": info.sha256, "width": info.width, "height": info.height},
                active_request.prompt_digest,
                active_request.workflow_digest,
                response.adapter_version,
                active_request.workflow_digest,
            )
            if typography_evidence is not None:
                kernel.record_gate(
                    stage_id,
                    artifact_id,
                    "TYPOGRAPHY_GATE",
                    DetectorClass.DETERMINISTIC,
                    GateStatus.PASS,
                    {
                        "base_sha256": typography_evidence.base_sha256,
                        "font_sha256": typography_evidence.font_sha256,
                        "text_sha256": typography_evidence.text_sha256,
                        "final_sha256": typography_evidence.final_sha256,
                        "width": typography_evidence.width,
                        "height": typography_evidence.height,
                        "renderer_version": typography_evidence.renderer_version,
                    },
                    active_request.prompt_digest,
                    active_request.workflow_digest,
                    typography_evidence.renderer_version,
                    typography_evidence.font_sha256,
                )
            kernel.finish_generation_call(
                call_id,
                CallStatus.FINISHED,
                info.sha256,
                model_identity=response.model_identity,
                adapter_version=response.adapter_version,
                duration_ms=response.duration_ms,
                termination_reason=response.termination_reason,
            )
            _raise_if_cancelled(cancellation, adapter, call_id)
            kernel.commit_artifact(transaction_id, artifact_id)
            return ImageTransactionResult(
                DeliveryStatus.AUTHORITATIVE,
                transaction_id,
                call_id,
                artifact_id,
                info.sha256,
                info,
                typography_evidence,
            )
        except (ImageAdapterError, ImageResourceError, TypographyError, ValueError, OSError) as exc:
            error = (
                exc
                if isinstance(exc, ImageAdapterError)
                else ImageAdapterError(exc.code, str(exc))
                if isinstance(exc, TypographyError)
                else ImageAdapterError(
                    "IMG012_OOM" if isinstance(exc, ImageResourceError) else "IMG010_QA_FAILURE",
                    str(exc),
                )
            )
            kernel.finish_generation_call(
                call_id, CallStatus.FAILED, failure_code=error.code, termination_reason=error.code
            )
            if isinstance(exc, ImageResourceError):
                with suppress(Exception):
                    adapter.unload()
            if error.code == "IMG004_CANCELLED":
                break
    return ImageTransactionResult(
        DeliveryStatus.VISUAL_GATE_FAIL, transaction_id, last_call_id, None, None
    )


def _raise_if_cancelled(
    cancellation: Event, adapter: LocalImageAdapter, generation_call_id: str
) -> None:
    if cancellation.is_set():
        try:
            adapter.cancel(generation_call_id)
        finally:
            raise ImageAdapterError("IMG004_CANCELLED", "image request cancelled")


def _request_bytes(request: ImageRequest) -> bytes:
    return "|".join(
        (
            request.basename,
            request.prompt_digest,
            request.workflow_digest,
            request.model_identity,
            str(request.seed),
            str(request.requested_width),
            str(request.requested_height),
        )
    ).encode()
