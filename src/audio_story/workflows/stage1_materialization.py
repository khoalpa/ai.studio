"""Materialize a production Stage 1 story from validated blueprint and image authority."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from PIL import Image

from audio_story.domain.stage1 import ProfileContract, Stage1Request
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage1 import (
    final_script_digest,
    ordered_json_bytes,
    validate_character_assets,
    validate_story_bytes,
    word_count,
)
from audio_story.workflows.image_transaction import ImageTransactionResult
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.stage1_package import PROMPT_VERSION


@dataclass(frozen=True, slots=True)
class StoryQualityResult:
    status: str
    evidence: dict[str, Any]
    model_identity: str
    adapter_version: str


def materialize_production_story(
    kernel: WorkflowKernel,
    blueprint: dict[str, Any],
    image_results: list[ImageTransactionResult],
    request: Stage1Request,
    contract: ProfileContract,
) -> tuple[OrderedDict[str, Any], OrderedDict[str, bytes], bytes]:
    """Build and validate story.json without asserting semantic quality completion."""
    if blueprint["title"] != request.title:
        raise ValueError("serialize blueprint title does not match the confirmed request")
    characters = blueprint["characters"]
    if len(characters) != len(image_results):
        raise ValueError("character image result count does not match blueprint")
    assets: OrderedDict[str, bytes] = OrderedDict()
    materialized_characters: list[OrderedDict[str, Any]] = []
    for character, result in zip(characters, image_results, strict=True):
        if result.status != "AUTHORITATIVE" or result.digest is None:
            raise ValueError("character image is not authoritative")
        authority = kernel.db.connection.execute(
            "SELECT delivery_status,gate_status,immutable FROM image_artifact_authority "
            "WHERE artifact_sha256=?",
            (result.digest,),
        ).fetchone()
        if authority is None or tuple(authority) != ("AUTHORITATIVE", "PASS", 1):
            raise ValueError("character image authority is not current PASS and immutable")
        data = kernel.store.bind_authoritative_artifact(result.digest)
        character_id = str(character["character_id"])
        path = f"characters/{character_id}.png"
        assets[path] = data
        pixel_digest = decoded_pixel_sha256(data)
        identity_lock = sha256_bytes(
            canonical_json_bytes(
                {
                    "character_id": character_id,
                    "description": character["description"],
                    "pixel_sha256": pixel_digest,
                }
            )
        )
        value = OrderedDict(character)
        value["reference_asset"] = OrderedDict(
            schema_version="1.0",
            reference_image=path,
            file_sha256=result.digest,
            pixel_sha256=pixel_digest,
            dimensions=OrderedDict(width=1536, height=2048),
            identity_lock=f"identity:{character_id}:{identity_lock}",
            validation_status="PASS",
        )
        materialized_characters.append(value)
    script = blueprint["script"]
    commitment = _unverified_commitment(script, contract)
    story = OrderedDict(
        schema_version="2.3",
        meta=OrderedDict(
            title=request.title,
            series=request.series or request.title,
            episode=request.episode,
            author="Katarina",
            channel=contract.channel,
            target=contract.audience,
            length_min=contract.min_minutes,
            length_max=contract.max_minutes,
            language=request.language,
            genre=contract.genre,
            audience=contract.audience,
            tone="production blueprint pending independent quality closure",
            tags=["audio", "story", "offline", "stage1", contract.profile.value.lower()],
            story_quality_commitment=commitment,
        ),
        characters=materialized_characters,
        outline=blueprint["outline"],
        script=script,
    )
    validate_character_assets(story, assets, test_mode=False)
    story_bytes = ordered_json_bytes(story)
    validate_story_bytes(story_bytes, contract)
    return story, assets, story_bytes


def decoded_pixel_sha256(data: bytes) -> str:
    with Image.open(BytesIO(data)) as image:
        pixels = image.convert("RGBA").tobytes()
        dimensions = f"{image.width}x{image.height}:RGBA:".encode()
    return hashlib.sha256(dimensions + pixels).hexdigest()


def finalize_production_quality(
    story: OrderedDict[str, Any],
    assets: OrderedDict[str, bytes],
    result: StoryQualityResult,
) -> bytes:
    """Validate independent semantic evidence, finalize commitment, and revalidate bytes."""
    if result.status != "PASS":
        raise ValueError("production story quality assessment did not pass")
    if "mock" in result.model_identity.casefold() or "mock" in result.adapter_version.casefold():
        raise ValueError("mock semantic evidence is not allowed in production")
    evidence = result.evidence
    script = story["script"]
    script_digest = final_script_digest(script)
    asset_set_digest = sha256_bytes(
        canonical_json_bytes([[path, sha256_bytes(data)] for path, data in assets.items()])
    )
    if evidence.get("final_script_text_digest_sha256") != script_digest:
        raise ValueError("quality evidence is not bound to the final script")
    if evidence.get("character_asset_set_digest_sha256") != asset_set_digest:
        raise ValueError("quality evidence is not bound to the character asset set")
    quality = evidence.get("quality")
    engagement = evidence.get("engagement")
    if not isinstance(quality, dict) or not isinstance(engagement, dict):
        raise ValueError("quality evidence score objects are required")
    for key in ("final_story_quality_score", "progression_score"):
        if not isinstance(quality.get(key), int) or not 0 <= quality[key] <= 10:
            raise ValueError(f"quality evidence {key} is invalid")
    for scores, label, expected_count in (
        (quality.get("dimension_scores"), "quality", 8),
        (engagement.get("dimension_scores"), "engagement", 5),
    ):
        if (
            not isinstance(scores, list)
            or len(scores) != expected_count
            or any(not isinstance(score, int) or not 0 <= score <= 2 for score in scores)
        ):
            raise ValueError(
                f"{label} dimension_scores must contain {expected_count} values in 0..2"
            )
    if (
        not isinstance(engagement.get("engagement_score"), int)
        or not 0 <= engagement["engagement_score"] <= 10
    ):
        raise ValueError("quality evidence engagement_score is invalid")
    evidence_digest = sha256_bytes(canonical_json_bytes(evidence))
    commitment = story["meta"]["story_quality_commitment"]
    commitment["committed_quality_metrics"] = OrderedDict(
        final_story_quality_score=quality["final_story_quality_score"],
        progression_score=quality["progression_score"],
        engagement_score=engagement["engagement_score"],
        quality_dimension_scores=list(quality["dimension_scores"]),
        engagement_dimension_scores=list(engagement["dimension_scores"]),
    )
    commitment["committed_quality_metrics_digest_sha256"] = sha256_bytes(
        canonical_json_bytes(commitment["committed_quality_metrics"])
    )
    commitment["planning_claims"] = OrderedDict(
        story_intent={"status": "PASS"},
        causal_architecture={"status": "PASS"},
        engagement_design={"status": "PASS"},
        refinement_closure={"status": "PASS"},
        evidence_graph_digest_sha256=evidence_digest,
    )
    commitment["planning_claims_digest_sha256"] = sha256_bytes(
        canonical_json_bytes(commitment["planning_claims"])
    )
    commitment["semantic_quality_status"] = "PASS"
    commitment["semantic_evidence_digest_sha256"] = evidence_digest
    commitment["semantic_model_identity"] = result.model_identity
    commitment["semantic_adapter_version"] = result.adapter_version
    commitment["commitment_digest_sha256"] = None
    commitment["commitment_digest_sha256"] = sha256_bytes(canonical_json_bytes(commitment))
    return ordered_json_bytes(story)


def _unverified_commitment(
    script: list[dict[str, Any]], contract: ProfileContract
) -> OrderedDict[str, Any]:
    metrics = OrderedDict(
        total_words=word_count(script),
        estimated_duration_minutes=word_count(script) / contract.target_wpm,
        script_item_count=len(script),
    )
    return OrderedDict(
        schema_version="1.1",
        created_by_prompt_version=PROMPT_VERSION,
        final_script_text_digest_sha256=final_script_digest(script),
        recomputable_metrics=metrics,
        recomputable_metrics_digest_sha256=sha256_bytes(canonical_json_bytes(metrics)),
        semantic_quality_status="NOT_VERIFIED",
        commitment_digest_sha256=None,
    )
