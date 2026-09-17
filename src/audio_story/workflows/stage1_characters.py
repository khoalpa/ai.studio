"""Production Stage 1 character-reference generation and metadata binding."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from audio_story.adapters.image import (
    ImageAdapterError,
    ImageRequest,
    ImageResponse,
    LocalImageAdapter,
)
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.images import (
    PNG_SIGNATURE,
    managed_upscale_evidence,
    validate_image_qa,
    validate_png,
)
from audio_story.workflows.image_transaction import (
    ImageTransactionResult,
    SemanticImageGateResult,
    generate_single_image,
)
from audio_story.workflows.kernel import WorkflowKernel


@dataclass(frozen=True, slots=True)
class CharacterImageConfig:
    adapter: LocalImageAdapter
    workflow_digest: str
    model_identity: str
    timeout_seconds: float = 300.0
    semantic_assessor: Callable[[bytes, ImageRequest], SemanticImageGateResult] | None = None


def generate_character_reference(
    kernel: WorkflowKernel,
    stage_id: str,
    character: dict[str, Any],
    capsule_digest: str,
    seed: int,
    config: CharacterImageConfig,
) -> ImageTransactionResult:
    """Generate and authority-bind one exact 1536x2048 character PNG."""
    backend = str(config.adapter.capabilities().get("backend", ""))
    if "mock" in backend.casefold() or "mock" in config.model_identity.casefold():
        raise ImageAdapterError(
            "IMG017_TEST_BACKEND_PRODUCTION_PATH",
            "test image backends cannot generate production character references",
        )
    if config.semantic_assessor is None:
        raise ImageAdapterError(
            "IMG020_SEMANTIC_GATE_REQUIRED",
            "production character references require a semantic assessor",
        )
    character_id = str(character["character_id"])
    existing = kernel.db.connection.execute(
        "SELECT t.id transaction_id,b.artifact_id,a.sha256,g.id generation_call_id "
        "FROM asset_transactions t "
        "JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
        "JOIN artifacts a ON a.id=b.artifact_id "
        "JOIN generation_calls g ON g.candidate_artifact_id=a.id AND g.transaction_id=t.id "
        "WHERE t.stage_run_id=? AND t.basename=? AND t.status='COMMITTED' "
        "ORDER BY g.attempt_index DESC LIMIT 1",
        (stage_id, f"{character_id}.png"),
    ).fetchone()
    if existing is not None:
        data = kernel.store.get_artifact_by_digest(str(existing["sha256"]))
        info = validate_image_qa(data, f"{character_id}.png", expected_dimensions=(1536, 2048))
        return ImageTransactionResult(
            "AUTHORITATIVE",
            str(existing["transaction_id"]),
            str(existing["generation_call_id"]),
            str(existing["artifact_id"]),
            info.sha256,
            info,
        )
    description = str(character["description"])
    prompt = (
        "solo portrait of exactly one person, one character only, full body visible head "
        "to feet, centered neutral standing pose, plain background, "
        "consistent facial identity, no text, no watermark; "
        f"name: {character['name']}; age: {character['age']}; role: {character['role']}; "
        f"description: {description}"
    )
    negative = (
        "text, watermark, logo, two people, multiple people, duplicate person, "
        "character sheet, side-by-side figures, cropped head, cropped feet, blurry"
    )
    request = ImageRequest(
        f"{character_id}.png",
        sha256_bytes(prompt.encode("utf-8")),
        config.workflow_digest,
        config.model_identity,
        seed,
        1,
        1536,
        2048,
        "PNG",
        config.timeout_seconds,
        "pending",
        "pending",
        {
            "positive_prompt": prompt,
            "negative_prompt": negative,
            "character_id": character_id,
        },
    )
    return generate_single_image(
        kernel,
        stage_id,
        request,
        config.adapter,
        owner_stage="STAGE1",
        artifact_role="CHARACTER_ASSET",
        # SDXL can occasionally produce a duplicate figure despite a single-person
        # prompt.  A rejected candidate is never bound; give this independent,
        # seed-varied generation one final bounded chance before Stage 1 fails.
        max_attempts=3,
        metadata_binder=bind_character_metadata,
        character_id=character_id,
        semantic_assessor=config.semantic_assessor,
        retry_seed_step=1,
    )


def bind_character_metadata(data: bytes, request: ImageRequest, response: ImageResponse) -> bytes:
    """Replace generic runtime metadata with exact production character provenance."""
    context = request.commitment_context or {}
    character_id = context.get("character_id")
    if not isinstance(character_id, str) or not character_id.startswith("char_"):
        raise ValueError("character_id is required for production character metadata")
    info = validate_png(data, request.basename, expected_dimensions=(1536, 2048))
    managed = managed_upscale_evidence(info, (1536, 2048))
    provenance: dict[str, Any] = {
        "provenance": "PRODUCTION_M5P_COMFYUI",
        "character_id": character_id,
        "model_identity": response.model_identity,
        "adapter_version": response.adapter_version,
        "prompt_digest": request.prompt_digest,
        "workflow_digest": request.workflow_digest,
        "seed": request.seed,
        "transaction_id": request.transaction_id,
        "generation_call_id": request.generation_call_id,
    }
    if managed is not None:
        provenance["managed_upscale"] = managed
    metadata = canonical_json_bytes(provenance)
    replacement = _png_chunk(b"tEXt", b"audio_story\0" + metadata)
    output = bytearray(PNG_SIGNATURE)
    offset = len(PNG_SIGNATURE)
    inserted = False
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + length + 12
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        is_audio_story = kind == b"tEXt" and payload.startswith(b"audio_story\0")
        if not is_audio_story:
            output.extend(data[offset:end])
        if kind == b"IHDR" and not inserted:
            output.extend(replacement)
            inserted = True
        offset = end
    if not inserted:
        raise ValueError("PNG has no IHDR")
    return bytes(output)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )
