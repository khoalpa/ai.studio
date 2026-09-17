from __future__ import annotations

import json

import pytest

from audio_story.adapters.llm.mock import DeterministicMockAdapter
from audio_story.workflows.story_quality_assessor import assess_story, validate_assessor_evidence

SCRIPT_DIGEST = "a" * 64
ASSET_DIGEST = "b" * 64


def _evidence() -> dict[str, object]:
    return {
        "status": "PASS",
        "final_script_text_digest_sha256": SCRIPT_DIGEST,
        "character_asset_set_digest_sha256": ASSET_DIGEST,
        "quality": {
            "final_story_quality_score": 8,
            "progression_score": 7,
            "dimension_scores": [1] * 8,
        },
        "engagement": {"engagement_score": 9, "dimension_scores": [2] * 5},
    }


def test_local_story_assessor_returns_digest_bound_pass() -> None:
    response = {
        "status": "PASS",
        "final_story_quality_score": 8,
        "progression_score": 7,
        "engagement_score": 9,
        "quality_dimension_scores": [1] * 8,
        "engagement_dimension_scores": [2] * 5,
    }
    adapter = DeterministicMockAdapter(responses=[json.dumps(response).encode()])
    result = assess_story(
        adapter,
        b"local story context",
        script_digest=SCRIPT_DIGEST,
        asset_set_digest=ASSET_DIGEST,
    )
    assert result.status == "PASS"
    assert result.evidence["evidence_digest_sha256"]
    assert result.model_identity == adapter.model_identity


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("final_script_text_digest_sha256", "x"), "script digest"),
        (("character_asset_set_digest_sha256", "x"), "asset digest"),
        (("quality", None), "score objects"),
        (("quality.final_story_quality_score", 6), "quality threshold"),
        (("engagement.engagement_score", 6), "engagement threshold"),
        (("quality.dimension_scores", [1] * 7), "dimension threshold"),
        (("status", "FAIL"), "status is not PASS"),
    ],
)
def test_story_assessor_rejects_untrusted_evidence(
    mutation: tuple[str, object], message: str
) -> None:
    evidence = _evidence()
    path, value = mutation
    if "." in path:
        parent, child = path.split(".")
        target = evidence[parent]
        assert isinstance(target, dict)
        target[child] = value
    else:
        evidence[path] = value
    with pytest.raises(ValueError, match=message):
        validate_assessor_evidence(
            evidence,
            script_digest=SCRIPT_DIGEST,
            asset_set_digest=ASSET_DIGEST,
            model_identity="local-model",
            adapter_version="1.0",
        )
