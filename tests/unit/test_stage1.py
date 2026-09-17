from __future__ import annotations

import copy
import zipfile
from collections import OrderedDict

import pytest

from audio_story.domain.stage1 import Stage1Error, Stage1Request, resolve_profile
from audio_story.validation.stage1 import (
    ordered_json_bytes,
    validate_anchor_bytes,
    validate_character_assets,
    validate_generated_segment_language,
    validate_production_script_content,
    validate_report_bytes,
    validate_script_language,
    validate_serialized_dialogue,
    validate_story_bytes,
)
from audio_story.workflows.stage1 import (
    _build_report,
    _build_story,
    _build_story_bible,
    _narrative_architecture_instruction,
    _segment_novelty_instruction,
)
from audio_story.workflows.stage1_package import (
    build_manifest,
    build_series_anchor,
    build_story_zip,
)


@pytest.mark.parametrize("profile", ["YOUTH_SAFE", "ADULT_STANDARD", "SERIAL_DETECTIVE"])
def test_profile_router(profile: str) -> None:
    assert resolve_profile(profile, "vi").profile == profile


def test_production_content_rejects_placeholder_script() -> None:
    with pytest.raises(Stage1Error, match="S140_PLACEHOLDER_SCRIPT"):
        validate_production_script_content([{"text": "câu 1 chuyện chuyện chuyện."}])


def test_script_language_matches_the_selected_dropdown_language() -> None:
    validate_script_language([{"text": "Mưa nhẹ rơi trên mái nhà."}], "vi")
    validate_script_language([{"text": "Gentle rain fell on the roof."}], "en")

    with pytest.raises(Stage1Error, match="S167_LANGUAGE_MISMATCH"):
        validate_script_language([{"text": "欢迎来到故事世界。"}], "vi")
    with pytest.raises(Stage1Error, match="S167_LANGUAGE_MISMATCH"):
        validate_script_language([{"text": "Mưa nhẹ rơi trên mái nhà."}], "en")


def test_generated_segment_language_fails_before_a_wrong_language_segment_can_commit() -> None:
    validate_generated_segment_language("Mưa nhẹ rơi trên mái nhà.", "vi")
    validate_generated_segment_language("Gentle rain fell on the roof.", "en")

    with pytest.raises(Stage1Error, match="S167_LANGUAGE_MISMATCH"):
        validate_generated_segment_language("欢迎来到故事世界。", "vi")
    with pytest.raises(Stage1Error, match="S167_LANGUAGE_MISMATCH"):
        validate_generated_segment_language("Gentle rain fell on the roof.", "vi")


def test_segment_novelty_cues_change_between_segments_and_retries() -> None:
    initial = _segment_novelty_instruction("GREETING", 3, 3, "vi")
    retry = _segment_novelty_instruction("GREETING", 3, 3, "vi", variation=1)
    next_segment = _segment_novelty_instruction("GREETING", 3, 4, "vi")

    assert "Nam" not in initial
    assert initial != retry
    assert initial != next_segment


def test_story_bible_does_not_repeat_one_plan_beat_into_every_zone() -> None:
    plan = OrderedDict(payload=OrderedDict(premise="Một tiền đề.", beats=["Một beat duy nhất."]))

    bible = _build_story_bible(plan, "vi")

    assert bible.count("Một beat duy nhất.") == 1
    assert "OPENING: develop this zone's canonical progression role" in bible


@pytest.mark.parametrize("language", ["vi", "en"])
def test_story_bible_includes_the_causal_climax_and_consequence_contract(language: str) -> None:
    plan = OrderedDict(payload=OrderedDict(premise="A premise.", beats=["A setup."]))

    bible = _build_story_bible(plan, language)
    contract = _narrative_architecture_instruction(language)

    assert contract in bible
    assert "CLIMAX" in contract
    assert "FALLING" in contract
    required_phrase = "irreversible" if language == "en" else "không thể rút lại"
    assert required_phrase in contract


def test_production_content_rejects_repetitive_script() -> None:
    with pytest.raises(Stage1Error, match="S141_REPETITIVE_SCRIPT"):
        validate_production_script_content([{"text": "la la la la la la la la."}])


@pytest.mark.parametrize(
    ("profile", "code"),
    [
        (None, "S101_MISSING_PROFILE"),
        ("BAD", "S102_INVALID_PROFILE"),
        ("YOUTH_SAFE+ADULT_STANDARD", "S103_CONFLICTING_PROFILE"),
    ],
)
def test_profile_router_rejects_invalid(profile: str | None, code: str) -> None:
    with pytest.raises(Stage1Error, match=code):
        resolve_profile(profile, "vi")


def _fixture() -> tuple[dict[str, object], OrderedDict[str, bytes]]:
    from audio_story.domain.stage1 import Stage1Request

    return _build_story(
        Stage1Request("YOUTH_SAFE", duration_minutes=12, duration_confirmed=True, test_mode=True),
        resolve_profile("YOUTH_SAFE", "vi"),
    )


def test_story_report_and_package_contract(tmp_path) -> None:
    story, assets = _fixture()
    story_bytes = ordered_json_bytes(story)
    parsed = validate_story_bytes(story_bytes, resolve_profile("YOUTH_SAFE", "vi"))
    assert validate_character_assets(story, assets, test_mode=True)
    report = _build_report(story, story_bytes, assets, resolve_profile("YOUTH_SAFE", "vi"))
    report_bytes = ordered_json_bytes(report)
    validate_report_bytes(report_bytes, story_bytes, parsed)
    members = OrderedDict([("story.json", story_bytes), ("story_validation.json", report_bytes)])
    members.update(assets)
    manifest = build_manifest("YOUTH_SAFE", story_bytes, members)
    archive = tmp_path / "story.zip"
    first = build_story_zip(archive, manifest, members)
    second = build_story_zip(tmp_path / "second.zip", manifest, members)
    assert first == second
    with zipfile.ZipFile(archive) as package:
        assert package.namelist() == ["workflow_manifest.json", *members]


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda value: value.update(schema_version="2.2"), "S120_STORY_SCHEMA"),
        (lambda value: value["script"][0].update(zone="ENDING"), "S124_ZONE_ORDER"),
        (lambda value: value["script"][0].update(text="unfinished"), "S128_INCOMPLETE_SENTENCE"),
        (
            lambda value: value["script"][0].update(text="beat map leaked."),
            "S123_INTERNAL_FIELD_LEAK",
        ),
        (
            lambda value: value["characters"][0]["reference_asset"].update(
                reference_image="characters/wrong.png"
            ),
            "S127_CHARACTER_BINDING",
        ),
    ],
)
def test_story_negative_paths(mutator, code: str) -> None:  # type: ignore[no-untyped-def]
    story, _ = _fixture()
    candidate = copy.deepcopy(story)
    mutator(candidate)
    with pytest.raises(Stage1Error, match=code):
        validate_story_bytes(ordered_json_bytes(candidate), resolve_profile("YOUTH_SAFE", "vi"))


def test_report_rejects_wrong_order_and_not_verified() -> None:
    story, assets = _fixture()
    story_bytes = ordered_json_bytes(story)
    report = _build_report(story, story_bytes, assets, resolve_profile("YOUTH_SAFE", "vi"))
    report["gates"][0]["status"] = "NOT_VERIFIED"
    with pytest.raises(Stage1Error, match="S133_REPORT_NOT_VERIFIED"):
        validate_report_bytes(ordered_json_bytes(report), story_bytes, story)
    legacy = OrderedDict(reversed(list(report.items())))
    with pytest.raises(Exception, match="DJ012_FIELD_ORDER"):
        validate_report_bytes(ordered_json_bytes(legacy), story_bytes, story)


def test_strict_story_duplicate_and_trailing_data() -> None:
    story, _ = _fixture()
    data = ordered_json_bytes(story)
    duplicate = data.replace(
        b'{"schema_version":"2.3",', b'{"schema_version":"2.3","schema_version":"2.3",', 1
    )
    with pytest.raises(Exception, match="DJ004_DUPLICATE_KEY"):
        validate_story_bytes(duplicate, resolve_profile("YOUTH_SAFE", "vi"))
    with pytest.raises(Exception, match="DJ008_TRAILING_DATA"):
        validate_story_bytes(data + b" true", resolve_profile("YOUTH_SAFE", "vi"))


def test_character_asset_binding_and_production_firewall() -> None:
    story, assets = _fixture()
    with pytest.raises(Stage1Error, match="S143_TEST_ASSET_PRODUCTION_PATH"):
        validate_character_assets(story, assets, test_mode=False)
    missing = OrderedDict(list(assets.items())[1:])
    with pytest.raises(Stage1Error, match="S127_CHARACTER_BINDING"):
        validate_character_assets(story, missing, test_mode=True)
    swapped = OrderedDict(reversed(list(assets.items())))
    with pytest.raises(Stage1Error, match="S127_CHARACTER_BINDING"):
        validate_character_assets(story, swapped, test_mode=True)


@pytest.mark.parametrize(
    ("owner", "expected", "voice"),
    [("NAM", "MALE", "FEMALE"), ("NU", "FEMALE", "MALE"), ("NAM", "MALE", "NARRATOR")],
)
def test_direct_speech_rejects_wrong_or_narrator_voice(
    owner: str, expected: str, voice: str
) -> None:
    script = [
        {
            "speaker_id": "WRONG_INTERNAL",
            "voice": voice,
            "text": f"{owner} nói: “Tôi đã thấy dấu vết.”",
        }
    ]
    with pytest.raises(Stage1Error, match="S134_DIALOGUE_VOICE"):
        validate_serialized_dialogue(script, {owner: expected})


def test_reported_speech_is_not_direct_and_same_voice_requires_audio_visible_cue() -> None:
    validate_serialized_dialogue(
        [
            {
                "speaker_id": "NARRATOR",
                "voice": "NARRATOR",
                "text": "Người kể thuật lại “An sẽ đến”.",
            }
        ],
        {},
    )
    ambiguous = [
        {"speaker_id": "WRONG_INTERNAL", "voice": "FEMALE", "text": "An nói: “Tôi đồng ý.”"},
        {"speaker_id": "BINH", "voice": "FEMALE", "text": "“Chúng ta đi thôi.”"},
    ]
    with pytest.raises(Stage1Error, match="S135_DIALOGUE_AMBIGUITY"):
        validate_serialized_dialogue(ambiguous, {"An": "FEMALE", "Bình": "FEMALE"})
    clear = [
        ambiguous[0],
        {**ambiguous[1], "speaker_id": "WRONG_INTERNAL", "text": "Bình đáp: “Chúng ta đi thôi.”"},
    ]
    assert (
        validate_serialized_dialogue(clear, {"An": "FEMALE", "Bình": "FEMALE"})[
            "same_voice_owner_switch_count"
        ]
        == 1
    )


def test_serial_anchor_contract_and_binding() -> None:
    request = Stage1Request(
        "SERIAL_DETECTIVE", duration_minutes=35, duration_confirmed=True, test_mode=True
    )
    story, _ = _build_story(request, resolve_profile("SERIAL_DETECTIVE", "vi"))
    data = build_series_anchor(story)
    validate_anchor_bytes(data, story)
    wrong = data.replace(b'"3.2.0"', b'"3.1.0"', 1)
    with pytest.raises(Stage1Error, match="S144_ANCHOR_SCHEMA"):
        validate_anchor_bytes(wrong, story)
    mutated = copy.deepcopy(story)
    mutated["meta"]["series"] = "Khác"
    with pytest.raises(Stage1Error, match="S145_ANCHOR_BINDING"):
        validate_anchor_bytes(data, mutated)
    wrong_character = data.replace(b'"char_001"', b'"char_999"', 1)
    with pytest.raises(Stage1Error, match="S146_ANCHOR_CHARACTER"):
        validate_anchor_bytes(wrong_character, story)
    wrong_state = data.replace(
        b'"status":"active","part_index":1', b'"status":"invalid","part_index":1', 1
    )
    with pytest.raises(Stage1Error, match="S148_ANCHOR_CONTINUITY"):
        validate_anchor_bytes(wrong_state, story)


def test_anchor_package_applicability() -> None:
    story, assets = _fixture()
    story_bytes = ordered_json_bytes(story)
    members = OrderedDict(story=story_bytes)
    with pytest.raises(Stage1Error, match="S147_ANCHOR_APPLICABILITY"):
        build_manifest("SERIAL_DETECTIVE", story_bytes, members)
    members["series_anchor.json"] = b"{}"
    with pytest.raises(Stage1Error, match="S147_ANCHOR_APPLICABILITY"):
        build_manifest("YOUTH_SAFE", story_bytes, members)
