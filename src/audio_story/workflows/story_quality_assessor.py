"""Fail-closed validation for offline story-quality assessor evidence."""

from __future__ import annotations

from threading import Event
from typing import Any

from audio_story.adapters.llm.base import LocalLLMAdapter
from audio_story.adapters.llm.models import GenerationKind, GenerationRequest, PromptCapsule
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.workflows.stage1_materialization import StoryQualityResult

ASSESSOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "status",
        "final_story_quality_score",
        "progression_score",
        "engagement_score",
        "quality_dimension_scores",
        "engagement_dimension_scores",
    ],
    "properties": {
        "status": {"type": "string", "enum": ["PASS", "FAIL"]},
        "final_story_quality_score": {"type": "integer", "minimum": 0, "maximum": 10},
        "progression_score": {"type": "integer", "minimum": 0, "maximum": 10},
        "engagement_score": {"type": "integer", "minimum": 0, "maximum": 10},
        "quality_dimension_scores": {
            "type": "array",
            "minItems": 8,
            "maxItems": 8,
            "items": {"type": "integer", "minimum": 0, "maximum": 2},
        },
        "engagement_dimension_scores": {
            "type": "array",
            "minItems": 5,
            "maxItems": 5,
            "items": {"type": "integer", "minimum": 0, "maximum": 2},
        },
    },
    "additionalProperties": False,
}


def assess_story(
    adapter: LocalLLMAdapter,
    story_context: bytes,
    *,
    script_digest: str,
    asset_set_digest: str,
    model_identity: str = "llama.cpp-local",
    adapter_version: str = "1.0",
) -> StoryQualityResult:
    request = GenerationRequest(
        capsule=PromptCapsule(story_context, sha256_bytes(story_context)),
        instruction="Return JSON only. Assess story quality and engagement; do not infer hidden facts.",
        kind=GenerationKind.STRUCTURED,
        max_output_tokens=512,
        json_schema=ASSESSOR_SCHEMA,
        temperature=0.0,
        top_p=1.0,
    )
    response = adapter.generate_structured(request, Event())
    import json

    raw = json.loads(response.content)
    evidence = {
        "status": raw["status"],
        "final_script_text_digest_sha256": script_digest,
        "character_asset_set_digest_sha256": asset_set_digest,
        "quality": {
            "final_story_quality_score": raw["final_story_quality_score"],
            "progression_score": raw["progression_score"],
            "dimension_scores": raw["quality_dimension_scores"],
        },
        "engagement": {
            "engagement_score": raw["engagement_score"],
            "dimension_scores": raw["engagement_dimension_scores"],
        },
    }
    return validate_assessor_evidence(
        evidence,
        script_digest=script_digest,
        asset_set_digest=asset_set_digest,
        model_identity=response.model_identity or model_identity,
        adapter_version=response.adapter_version or adapter_version,
    )


def validate_assessor_evidence(
    evidence: dict[str, Any],
    *,
    script_digest: str,
    asset_set_digest: str,
    model_identity: str,
    adapter_version: str,
) -> StoryQualityResult:
    """Accept only bounded, digest-bound PASS evidence from a local assessor."""
    if evidence.get("final_script_text_digest_sha256") != script_digest:
        raise ValueError("assessor evidence script digest mismatch")
    if evidence.get("character_asset_set_digest_sha256") != asset_set_digest:
        raise ValueError("assessor evidence asset digest mismatch")
    quality = evidence.get("quality")
    engagement = evidence.get("engagement")
    if not isinstance(quality, dict) or not isinstance(engagement, dict):
        raise ValueError("assessor evidence score objects are required")
    if any(
        not isinstance(quality.get(key), int) or not 7 <= quality[key] <= 10
        for key in ("final_story_quality_score", "progression_score")
    ):
        raise ValueError("assessor quality threshold failed")
    if (
        not isinstance(engagement.get("engagement_score"), int)
        or not 7 <= engagement["engagement_score"] <= 10
    ):
        raise ValueError("assessor engagement threshold failed")
    for scores, count in (
        (quality.get("dimension_scores"), 8),
        (engagement.get("dimension_scores"), 5),
    ):
        if (
            not isinstance(scores, list)
            or len(scores) != count
            or any(not isinstance(score, int) or score < 1 or score > 2 for score in scores)
        ):
            raise ValueError("assessor dimension threshold failed")
    if evidence.get("status") != "PASS":
        raise ValueError("assessor status is not PASS")
    evidence = dict(evidence)
    evidence["evidence_digest_sha256"] = sha256_bytes(canonical_json_bytes(evidence))
    return StoryQualityResult("PASS", evidence, model_identity, adapter_version)
