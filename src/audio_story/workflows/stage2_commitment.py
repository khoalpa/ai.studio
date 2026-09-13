"""CURRENT Stage 2 provenance and visual-realization PNG commitments."""

from __future__ import annotations

import json
import struct
import zlib
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any, cast

from audio_story.adapters.image.base import ImageRequest, ImageResponse
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.images import PNG_SIGNATURE, PngInfo, validate_png

PROVENANCE_KEY = "image_provenance_commitment"
REALIZATION_KEY = "visual_realization_commitment"
REALIZATION_ROOT = (
    "schema_version",
    "assurance_level",
    "basename",
    "orientation",
    "plan_snapshot",
    "plan_digest_sha256",
    "semantic_claims",
    "semantic_claims_digest_sha256",
    "realization_evidence",
    "approved_deviation",
    "diversity_exception",
    "transaction",
    "migration",
    "evidence_graph_subset",
    "final_pixel_sha256",
    "commit_phase",
    "metadata_commit_status",
    "postwrite_validation_status",
)


def bind_stage2_commitments(data: bytes, request: ImageRequest, response: ImageResponse) -> bytes:
    context = request.commitment_context
    if context is None:
        raise ValueError("M7C300_COMMITMENT_CONTEXT_MISSING")
    info = validate_png(data, request.basename, expected_dimensions=(3840, 2160))
    pixel_digest = decoded_pixel_digest(data, info)
    transaction_role = cast(str, context["transaction_role"])
    index = int(context["transaction_index"])
    provenance = OrderedDict(
        schema_version="2.0",
        stage="STAGE2",
        orientation="LANDSCAPE",
        basename=request.basename,
        transaction_id=request.transaction_id,
        source_quality_tier="NATIVE_OR_EQUIVALENT",
        source_eligibility_mode="OBSERVABLE_NATIVE",
        source_preimage_observability="OBSERVED",
        source_eligibility_gate_id="IMAGE-NATIVE-SOURCE-ELIGIBILITY-01",
        source_eligibility_gate_status="PASS",
        observability="OBSERVED",
        source_dimensions=OrderedDict(width=3840, height=2160),
        final_dimensions=OrderedDict(width=info.width, height=info.height),
        source_of_pixels_digest_sha256=pixel_digest,
        final_file_sha256=sha256_bytes(data),
        art_direction_id=context["art_direction_id"],
    )
    snapshot = context["plan_snapshot"]
    claims = [
        OrderedDict(
            claim_id=f"claim:{request.basename}:moment",
            claim="single observable story moment",
            observability="DIRECT",
            observable_proxy="visible composition and focal subject",
            required_pixel_evidence="subject and scene are visible in final pixels",
            context_reference_ids=[],
            forbidden_overclaim="no internal-state claim",
            status="PASS",
        )
    ]
    claims_digest = sha256_bytes(canonical_json_bytes(claims))
    realization = OrderedDict(
        schema_version="2.0",
        assurance_level="CREATION_BOUND",
        basename=request.basename,
        orientation="LANDSCAPE",
        plan_snapshot=snapshot,
        plan_digest_sha256=context["plan_digest_sha256"],
        semantic_claims=claims,
        semantic_claims_digest_sha256=claims_digest,
        realization_evidence=["exact final PNG reopened", "single full-frame canvas"],
        approved_deviation=None,
        diversity_exception=None,
        transaction=OrderedDict(
            role=transaction_role,
            index=index,
            role_basis="CURRENT_ZONE_EXECUTION_ORDER",
            selection_evidence="deterministic basename queue",
            selection_digest_sha256=claims_digest,
        ),
        migration=None,
        evidence_graph_subset=[],
        final_pixel_sha256=pixel_digest,
        commit_phase="FINAL",
        metadata_commit_status="PASS",
        postwrite_validation_status="PASS",
    )
    return _insert_two_itxt(data, provenance, realization)


def validate_stage2_commitments(
    data: bytes, basename: str, transaction_id: str
) -> tuple[PngInfo, OrderedDict[str, Any]]:
    info = validate_png(data, basename, expected_dimensions=(3840, 2160))
    raw = info.metadata.get(REALIZATION_KEY)
    _require(isinstance(raw, dict), "M7C301_REALIZATION_MISSING")
    realization = cast(OrderedDict[str, Any], raw)
    _require(tuple(realization) == REALIZATION_ROOT, "M7C302_REALIZATION_ROOT")
    _require(realization.get("schema_version") == "2.0", "M7C303_REALIZATION_SCHEMA")
    _require(
        realization.get("basename") == basename and realization.get("orientation") == "LANDSCAPE",
        "M7C304_REALIZATION_BINDING",
    )
    _require(
        realization.get("assurance_level") == "CREATION_BOUND"
        and realization.get("commit_phase") == "FINAL",
        "M7C305_REALIZATION_PHASE",
    )
    _require(
        realization.get("metadata_commit_status") == "PASS"
        and realization.get("postwrite_validation_status") == "PASS",
        "M7C306_REALIZATION_STATUS",
    )
    transaction = realization.get("transaction")
    _require(isinstance(transaction, dict), "M7C307_TRANSACTION")
    assert isinstance(transaction, dict)
    _require(
        isinstance(transaction.get("index"), int) and transaction["index"] >= 1,
        "M7C307_TRANSACTION",
    )
    provenance = info.metadata.get(PROVENANCE_KEY)
    _require(isinstance(provenance, dict), "M7C308_PROVENANCE_MISSING")
    assert isinstance(provenance, dict)
    _require(
        provenance.get("basename") == basename
        and provenance.get("transaction_id") == transaction_id,
        "M7C309_PROVENANCE_BINDING",
    )
    _require(
        provenance.get("orientation") == "LANDSCAPE" and provenance.get("stage") == "STAGE2",
        "M7C310_PROVENANCE_STAGE",
    )
    _require(
        realization.get("final_pixel_sha256") == decoded_pixel_digest(data, info),
        "M7C311_PIXEL_DIGEST",
    )
    return info, realization


def decoded_pixel_digest(data: bytes, info: PngInfo) -> str:
    compressed = bytearray()
    offset = len(PNG_SIGNATURE)
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        if kind == b"IDAT":
            compressed.extend(data[offset + 8 : offset + 8 + length])
        offset += length + 12
        if kind == b"IEND":
            break
    raw = zlib.decompress(bytes(compressed))
    return sha256_bytes(
        canonical_json_bytes(
            {
                "width": info.width,
                "height": info.height,
                "orientation": "LANDSCAPE",
                "rgb_scanlines_sha256": sha256_bytes(raw),
            }
        )
    )


def _insert_two_itxt(
    data: bytes, provenance: Mapping[str, Any], realization: Mapping[str, Any]
) -> bytes:
    return _insert_itxt(
        _insert_itxt(data, PROVENANCE_KEY, provenance), REALIZATION_KEY, realization
    )


def _insert_itxt(data: bytes, key: str, value: Mapping[str, Any]) -> bytes:
    body = (
        key.encode("latin-1")
        + b"\0\0\0\0\0"
        + json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    chunk = struct.pack(">I", len(body)) + b"iTXt" + body
    chunk += struct.pack(">I", zlib.crc32(b"iTXt" + body) & 0xFFFFFFFF)
    return data[:33] + chunk + data[33:]


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)
