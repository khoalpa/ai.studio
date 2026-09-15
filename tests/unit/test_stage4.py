from __future__ import annotations

import json
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path

import pytest

from audio_story.domain.stage4 import Stage4Error, Stage4PackageInput
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage4 import load_stage3_package, validate_video_prompts_bytes
from audio_story.workflows.stage4_package import build_stage4_package
from audio_story.workflows.stage4_planning import (
    build_video_prompts,
    derive_timeline,
    resolve_stage4_config,
)


def _source(
    text: str = "A careful detective opens the door. She records the clue safely.",
) -> Stage4PackageInput:
    story = OrderedDict(
        schema_version="2.3",
        meta=OrderedDict(title="Test", series=None, episode=None, language="en"),
        characters=[
            OrderedDict(
                character_id="char_001",
                age=16,
                reference_asset=OrderedDict(reference_image="characters/char_001.png"),
            )
        ],
        script=[
            OrderedDict(
                item_id="item_001",
                zone="OPENING",
                speaker_id="narrator",
                voice="narrator",
                speed="1.0",
                environment="library",
                text=text,
            )
        ],
    )
    story_bytes = json.dumps(story).encode()
    members = OrderedDict(
        [
            ("story.json", story_bytes),
            ("story_validation.json", b"{}"),
            ("characters/char_001.png", b"png"),
            ("visual_plan.json", b"{}"),
            ("visual_bible.json", b"{}"),
            ("package_quality_report.json", b"{}"),
        ]
    )
    quality = OrderedDict(
        package_identity=OrderedDict(character_set_digest_sha256=sha256_bytes(b"characters"))
    )
    manifest = OrderedDict(active_profile="YOUTH_SAFE")
    return Stage4PackageInput(
        Path("source.zip"),
        sha256_bytes(b"zip"),
        sha256_bytes(b"package"),
        b"{}",
        members,
        manifest,
        story,
        OrderedDict(),
        quality,
    )


def test_config_resolves_m9_audio_decision_and_rejects_unknown() -> None:
    assert resolve_stage4_config().audio_mode == "NATIVE_DIALOGUE"
    assert resolve_stage4_config({"video_audio_mode": "SILENT"}).audio_mode == "SILENT"
    with pytest.raises(Stage4Error, match="M9B001_CONFIG"):
        resolve_stage4_config({"video_audio_mode": "AUTO"})


def test_timeline_is_sentence_bound_and_deterministic() -> None:
    source = _source()
    config = resolve_stage4_config()
    first = derive_timeline(source, config)
    assert first == derive_timeline(source, config)
    assert len(first) == 2
    assert first[0].end_word_offset == first[1].start_word_offset
    assert first[0].end_time_seconds <= first[1].start_time_seconds


def test_long_utterance_is_losslessly_segmented() -> None:
    source = _source(" ".join(f"word{i}" for i in range(60)) + ".")
    spans = derive_timeline(source, resolve_stage4_config())
    assert len(spans) > 1
    assert " ".join(span.text for span in spans) == source.story["script"][0]["text"]
    assert all(span.usable_span_seconds <= Decimal("7.950") for span in spans)


@pytest.mark.parametrize(
    "mode,root_count,clip_count",
    [("NATIVE_DIALOGUE", 8, 23), ("AMBIENCE_ONLY", 7, 22), ("SILENT", 7, 22)],
)
def test_video_prompt_schema_audio_projections(mode: str, root_count: int, clip_count: int) -> None:
    root, data = build_video_prompts(_source(), resolve_stage4_config({"video_audio_mode": mode}))
    validate_video_prompts_bytes(data)
    assert len(root) == root_count
    assert len(root["clips"][0]) == clip_count


def test_output_digest_and_character_only_reference_fail_closed() -> None:
    _, data = build_video_prompts(_source(), resolve_stage4_config())
    candidate = json.loads(data)
    candidate["clips"][0]["reference_inputs"]["character_images"] = ["landscape/cover.png"]
    candidate["validation"]["output_digest_sha256"] = None
    candidate["validation"]["output_digest_sha256"] = sha256_bytes(canonical_json_bytes(candidate))
    with pytest.raises(Stage4Error, match="M9D005_REFERENCE"):
        validate_video_prompts_bytes(
            json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode()
        )


def test_authoritative_m8_intake_and_stage4_package_are_deterministic() -> None:
    archive = Path(__file__).parents[2] / "artifacts/m8-stage3-runtime3/final/story.zip"
    if not archive.exists():
        pytest.skip("local production checkpoint is absent")
    source = load_stage3_package(
        archive,
        expected_archive_sha256="85e941ce77cd61826f30e06098118e3c2be29a3952b01f806e96ca82f8eb462e",
    )
    config = resolve_stage4_config({"video_coverage_mode": "KEY_SCENES"})
    root, video_bytes = build_video_prompts(source, config)
    first = build_stage4_package(source, video_bytes)
    second = build_stage4_package(source, video_bytes)
    assert first.zip_bytes == second.zip_bytes
    assert first.package_digest_sha256 == second.package_digest_sha256
    assert 0 < root["project"]["clip_count"] <= 120
    assert len(source.members) == 26
    with pytest.raises(Stage4Error, match="M9A001_ARCHIVE_AUTHORITY"):
        load_stage3_package(archive, expected_archive_sha256="a" * 64)


def test_full_story_requires_large_projection_confirmation() -> None:
    archive = Path(__file__).parents[2] / "artifacts/m8-stage3-runtime3/final/story.zip"
    if not archive.exists():
        pytest.skip("local production checkpoint is absent")
    source = load_stage3_package(archive)
    with pytest.raises(Stage4Error, match="M9B020_DURATION_CONFIRMATION_REQUIRED"):
        build_video_prompts(source, resolve_stage4_config())
