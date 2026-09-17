from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from audio_story.adapters.image import (
    DeterministicMockImageAdapter,
    ImageAdapterError,
    ImageRequest,
    ImageResponse,
    LocalImageAdapter,
)
from audio_story.domain.stage1 import Stage1Request, resolve_profile
from audio_story.domain.state import WorkflowStatus
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.images import validate_png
from audio_story.validation.stage1 import ZONE_ORDER, final_script_digest, validate_story_bytes
from audio_story.workflows import WorkflowKernel
from audio_story.workflows.image_transaction import SemanticImageGateResult
from audio_story.workflows.stage1_characters import (
    CharacterImageConfig,
    generate_character_reference,
)
from audio_story.workflows.stage1_materialization import (
    StoryQualityResult,
    finalize_production_quality,
    materialize_production_story,
)


class _ProductionFixtureAdapter(LocalImageAdapter):
    def generate_image(self, request: ImageRequest, cancellation: Event) -> ImageResponse:
        response = DeterministicMockImageAdapter().generate_image(request, cancellation)
        return ImageResponse(
            response.content,
            request.model_identity,
            "M6-COMFYUI-FIXTURE-1.0",
            0,
            request.workflow_digest,
            request.seed,
        )

    def health(self) -> dict[str, str]:
        return {"status": "READY"}

    def capabilities(self) -> dict[str, object]:
        return {"backend": "comfyui-fixture", "gpu": False}

    def cancel(self, generation_call_id: str) -> None:
        return None

    def unload(self) -> None:
        return None


def _stage(kernel: WorkflowKernel) -> str:
    workflow = kernel.create_workflow("ADULT_STANDARD", "STAGE1", "CREATE", "a" * 64, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    return kernel.start_stage(workflow, "STAGE1", "c" * 64)


def test_character_reference_is_metadata_bound_authoritative_and_idempotent(
    tmp_path: Path,
) -> None:
    kernel = WorkflowKernel(tmp_path)
    stage = _stage(kernel)
    character = {
        "character_id": "char_001",
        "name": "An",
        "age": 30,
        "role": "protagonist",
        "description": "A careful investigator in a dark blue coat.",
    }

    def assessor(data: bytes, request: ImageRequest) -> SemanticImageGateResult:
        return SemanticImageGateResult(
            "PASS",
            {"image_sha256": hashlib.sha256(data).hexdigest(), "person_count": 1},
            "fixture-vlm",
            "1.0",
        )

    prompts: list[dict[str, Any]] = []

    class RecordingAdapter(_ProductionFixtureAdapter):
        def generate_image(self, request: ImageRequest, cancellation: Event) -> ImageResponse:
            prompts.append(request.commitment_context or {})
            return super().generate_image(request, cancellation)

    config = CharacterImageConfig(RecordingAdapter(), "d" * 64, "sdxl-local", 10, assessor)
    first = generate_character_reference(kernel, stage, character, "c" * 64, 17, config)
    second = generate_character_reference(kernel, stage, character, "c" * 64, 17, config)
    assert first.digest == second.digest
    assert len(prompts) == 1
    assert "exactly one person" in str(prompts[0]["positive_prompt"])
    assert "multiple people" in str(prompts[0]["negative_prompt"])
    assert first.transaction_id == second.transaction_id
    assert first.digest is not None
    info = validate_png(
        kernel.store.get_artifact_by_digest(first.digest),
        "char_001.png",
        expected_dimensions=(1536, 2048),
        required_metadata_key="audio_story",
    )
    assert info.metadata["audio_story"]["character_id"] == "char_001"
    assert info.metadata["audio_story"]["provenance"] == "PRODUCTION_M5P_COMFYUI"
    authority = kernel.db.connection.execute(
        "SELECT delivery_status,gate_status,immutable FROM image_artifact_authority"
    ).fetchone()
    assert tuple(authority) == ("AUTHORITATIVE", "PASS", 1)
    assert {
        row[0]
        for row in kernel.db.connection.execute(
            "SELECT gate_id FROM gate_results WHERE artifact_id=?", (first.artifact_id,)
        )
    } == {"IMAGE_QA_GATE", "CHARACTER_SEMANTIC_GATE"}
    kernel.close()


def test_character_semantic_fail_retries_with_new_seed_and_never_binds(
    tmp_path: Path,
) -> None:
    kernel = WorkflowKernel(tmp_path)
    stage = _stage(kernel)
    seeds: list[int] = []

    def reject(data: bytes, request: ImageRequest) -> SemanticImageGateResult:
        seeds.append(request.seed)
        return SemanticImageGateResult(
            "FAIL",
            {"image_sha256": hashlib.sha256(data).hexdigest(), "person_count": 2},
            "fixture-vlm",
            "1.0",
        )

    result = generate_character_reference(
        kernel,
        stage,
        {
            "character_id": "char_001",
            "name": "An",
            "age": 30,
            "role": "protagonist",
            "description": "Investigator.",
        },
        "c" * 64,
        17,
        CharacterImageConfig(_ProductionFixtureAdapter(), "d" * 64, "sdxl-local", 10, reject),
    )
    assert result.status == "VISUAL_GATE_FAIL"
    assert seeds == [17, 18, 19]
    assert kernel.db.connection.execute("SELECT COUNT(*) FROM artifact_bindings").fetchone()[0] == 0
    assert [
        row[0]
        for row in kernel.db.connection.execute(
            "SELECT failure_code FROM generation_calls ORDER BY attempt_index"
        )
    ] == [
        "IMG018_SEMANTIC_GATE_FAIL",
        "IMG018_SEMANTIC_GATE_FAIL",
        "IMG018_SEMANTIC_GATE_FAIL",
    ]
    kernel.close()


def test_character_invalid_vlm_output_finishes_call_and_retries(tmp_path: Path) -> None:
    from audio_story.studio.vlm import VlmAssessmentError

    kernel = WorkflowKernel(tmp_path)
    stage = _stage(kernel)
    calls = 0

    def assessor(data: bytes, request: ImageRequest) -> SemanticImageGateResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise VlmAssessmentError("VLM005_INVALID_OUTPUT", "invalid model output")
        return SemanticImageGateResult(
            "PASS",
            {"image_sha256": hashlib.sha256(data).hexdigest(), "person_count": 1},
            "fixture-vlm",
            "1.0",
        )

    result = generate_character_reference(
        kernel,
        stage,
        {
            "character_id": "char_001",
            "name": "An",
            "age": 30,
            "role": "protagonist",
            "description": "Investigator.",
        },
        "c" * 64,
        17,
        CharacterImageConfig(_ProductionFixtureAdapter(), "d" * 64, "sdxl-local", 10, assessor),
    )

    assert result.status == "AUTHORITATIVE"
    assert calls == 2
    rows = kernel.db.connection.execute(
        "SELECT status,failure_code FROM generation_calls ORDER BY attempt_index"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("FAILED", "VLM005_INVALID_OUTPUT"),
        ("FINISHED", None),
    ]
    kernel.close()


def test_materialize_story_binds_authority_pixels_and_passes_current_validator(
    tmp_path: Path,
) -> None:
    kernel = WorkflowKernel(tmp_path)
    stage = _stage(kernel)
    character = {
        "character_id": "char_001",
        "name": "An",
        "age": 30,
        "role": "protagonist",
        "description": "A careful investigator in a dark blue coat.",
    }

    def assessor(data: bytes, request: ImageRequest) -> SemanticImageGateResult:
        return SemanticImageGateResult(
            "PASS",
            {"image_sha256": hashlib.sha256(data).hexdigest(), "person_count": 1},
            "fixture-vlm",
            "1.0",
        )

    image = generate_character_reference(
        kernel,
        stage,
        character,
        "c" * 64,
        17,
        CharacterImageConfig(_ProductionFixtureAdapter(), "d" * 64, "sdxl-local", 10, assessor),
    )
    script = []
    for index in range(60):
        zone = ZONE_ORDER[min(index * len(ZONE_ORDER) // 60, len(ZONE_ORDER) - 1)]
        script.append(
            {
                "zone": zone,
                "environment": "none",
                "voice": "NARRATOR",
                "speed": "NORMAL",
                "lang": "VI",
                "text": " ".join(["story"] * 92) + ".",
            }
        )
    request = Stage1Request(
        "ADULT_STANDARD",
        duration_minutes=25,
        duration_confirmed=True,
        title="Production Story",
    )
    contract = resolve_profile(request.profile, request.language)
    story, assets, story_bytes = materialize_production_story(
        kernel,
        {
            "title": request.title,
            "characters": [character],
            "outline": {zone.lower(): f"{zone.title()} begins." for zone in ZONE_ORDER},
            "script": script,
        },
        [image],
        request,
        contract,
    )
    assert validate_story_bytes(story_bytes, contract)
    reference = story["characters"][0]["reference_asset"]
    assert reference["file_sha256"] == image.digest
    assert reference["pixel_sha256"] != reference["file_sha256"]
    assert list(assets) == ["characters/char_001.png"]
    assert story["meta"]["story_quality_commitment"]["semantic_quality_status"] == "NOT_VERIFIED"
    asset_set_digest = sha256_bytes(
        canonical_json_bytes([[path, sha256_bytes(data)] for path, data in assets.items()])
    )
    quality = StoryQualityResult(
        "PASS",
        {
            "final_script_text_digest_sha256": final_script_digest(story["script"]),
            "character_asset_set_digest_sha256": asset_set_digest,
            "quality": {
                "dimension_scores": [2] * 8,
                "final_story_quality_score": 8,
                "progression_score": 8,
            },
            "engagement": {"dimension_scores": [2] * 5, "engagement_score": 8},
            "findings": ["fixture evidence"],
        },
        "fixture-story-assessor",
        "1.0",
    )
    final_bytes = finalize_production_quality(story, assets, quality)
    assert validate_story_bytes(final_bytes, contract)
    commitment = story["meta"]["story_quality_commitment"]
    assert commitment["semantic_quality_status"] == "PASS"
    assert commitment["semantic_evidence_digest_sha256"] == sha256_bytes(
        canonical_json_bytes(quality.evidence)
    )
    kernel.close()


def test_quality_evidence_must_bind_exact_script_and_character_set() -> None:
    story = {
        "script": [
            {
                "text": "Complete sentence.",
            }
        ],
        "meta": {"story_quality_commitment": {}},
    }
    with pytest.raises(ValueError, match="final script"):
        finalize_production_quality(
            story,
            {},
            StoryQualityResult(
                "PASS",
                {
                    "final_script_text_digest_sha256": "0" * 64,
                    "character_asset_set_digest_sha256": sha256_bytes(canonical_json_bytes([])),
                },
                "fixture",
                "1.0",
            ),
        )


def test_character_reference_rejects_mock_backend(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path)
    stage = _stage(kernel)
    with pytest.raises(ImageAdapterError, match="IMG017_TEST_BACKEND_PRODUCTION_PATH"):
        generate_character_reference(
            kernel,
            stage,
            {
                "character_id": "char_001",
                "name": "An",
                "age": 30,
                "role": "protagonist",
                "description": "Investigator.",
            },
            "c" * 64,
            17,
            CharacterImageConfig(DeterministicMockImageAdapter(), "d" * 64, "mock"),
        )
    kernel.close()
