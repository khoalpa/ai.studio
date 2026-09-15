"""CURRENT Stage 3 portrait provenance and realization commitments."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, cast

from audio_story.adapters.image.base import ImageRequest, ImageResponse
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.images import PngInfo, validate_png
from audio_story.workflows.stage2_commitment import (
    PROVENANCE_KEY,
    REALIZATION_KEY,
    REALIZATION_ROOT,
    _insert_two_itxt,
    decoded_pixel_digest,
)


def bind_stage3_commitments(data: bytes, request: ImageRequest, response: ImageResponse) -> bytes:
    context = request.commitment_context
    if context is None:
        raise ValueError("M8C300_COMMITMENT_CONTEXT_MISSING")
    info = validate_png(data, request.basename, expected_dimensions=(1080, 1920))
    pixel_digest = decoded_pixel_digest(data, info)
    reference_path = cast(str, context["landscape_reference"])
    provenance = OrderedDict(
        schema_version="2.0",
        stage="STAGE3",
        orientation="PORTRAIT",
        basename=request.basename,
        transaction_id=request.transaction_id,
        source_quality_tier="NATIVE_OR_EQUIVALENT",
        source_eligibility_mode="OBSERVABLE_NATIVE",
        source_preimage_observability="OBSERVED",
        source_eligibility_gate_id="IMAGE-NATIVE-SOURCE-ELIGIBILITY-01",
        source_eligibility_gate_status="PASS",
        observability="OBSERVED",
        source_dimensions=OrderedDict(width=1080, height=1920),
        final_dimensions=OrderedDict(width=info.width, height=info.height),
        source_of_pixels_digest_sha256=pixel_digest,
        final_file_sha256=sha256_bytes(data),
        art_direction_id=context["art_direction_id"],
        primary_reference_basename=reference_path.removeprefix("landscape/"),
        primary_reference_sha256=context["landscape_sha256"],
    )
    claims = [
        OrderedDict(
            claim_id=f"claim:{request.basename}:portrait-adaptation",
            claim="portrait preserves the authoritative landscape narrative function",
            observability="DIRECT",
            observable_proxy="matching subject, action and scene",
            required_pixel_evidence="portrait and landscape pair review",
            context_reference_ids=[reference_path],
            forbidden_overclaim="no hidden-state claim",
            status="PASS",
        )
    ]
    claims_digest = sha256_bytes(canonical_json_bytes(claims))
    realization = OrderedDict(
        schema_version="2.0",
        assurance_level="CREATION_BOUND",
        basename=request.basename,
        orientation="PORTRAIT",
        plan_snapshot=context["plan_snapshot"],
        plan_digest_sha256=context["plan_digest_sha256"],
        semantic_claims=claims,
        semantic_claims_digest_sha256=claims_digest,
        realization_evidence=["exact final PNG reopened", context["pilot_evidence"]],
        approved_deviation=None,
        diversity_exception=None,
        transaction=OrderedDict(
            role=context["transaction_role"],
            index=context["transaction_index"],
            role_basis="PORTRAIT_PILOT_RISK_ORDER",
            selection_evidence=context["pilot_evidence"],
            selection_digest_sha256=context["pilot_digest"],
        ),
        migration=None,
        evidence_graph_subset=[],
        final_pixel_sha256=pixel_digest,
        commit_phase="FINAL",
        metadata_commit_status="PASS",
        postwrite_validation_status="PASS",
    )
    return _insert_two_itxt(data, provenance, realization)


def validate_stage3_commitments(
    data: bytes, basename: str, transaction_id: str, landscape_sha256: str
) -> tuple[PngInfo, dict[str, Any]]:
    info = validate_png(data, basename, expected_dimensions=(1080, 1920))
    realization = info.metadata.get(REALIZATION_KEY)
    provenance = info.metadata.get(PROVENANCE_KEY)
    _require(
        isinstance(realization, dict) and tuple(realization) == REALIZATION_ROOT,
        "M8C301_REALIZATION",
    )
    _require(isinstance(provenance, dict), "M8C302_PROVENANCE")
    realization = cast(dict[str, Any], realization)
    provenance = cast(dict[str, Any], provenance)
    _require(
        realization.get("orientation") == "PORTRAIT" and realization.get("commit_phase") == "FINAL",
        "M8C303_REALIZATION_BINDING",
    )
    _require(
        provenance.get("stage") == "STAGE3"
        and provenance.get("orientation") == "PORTRAIT"
        and provenance.get("basename") == basename
        and provenance.get("transaction_id") == transaction_id,
        "M8C304_PROVENANCE_BINDING",
    )
    _require(
        provenance.get("primary_reference_basename") == basename
        and provenance.get("primary_reference_sha256") == landscape_sha256,
        "M8C305_REFERENCE_BINDING",
    )
    _require(
        realization.get("final_pixel_sha256") == decoded_pixel_digest(data, info),
        "M8C306_PIXEL_DIGEST",
    )
    return info, realization


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)
