import pytest

from audio_story.validation.stage1 import ZONE_ORDER, has_terminal_sentence_punctuation
from audio_story.validation.strict_json import OrderedObject
from audio_story.workflows.stage1_zone_generation import (
    aggregate_zone_payloads,
    is_repetitive_story_text,
    repetition_similarity,
    validate_story_repetition,
    validate_zone_payload,
)


def test_near_duplicate_story_text_is_rejected_across_locations() -> None:
    left = "Chiếc đèn đường chợt nhấp nháy khi trời bắt đầu tối gần cổng trường."
    right = "Chiếc đèn đường chợt nhấp nháy khi trời bắt đầu tối trong hành lang thư viện."

    assert repetition_similarity(left, right) >= 0.82
    assert is_repetitive_story_text(right, left)


def test_distinct_causal_follow_up_is_not_rejected_as_repetition() -> None:
    first = "Lan mở lá thư và nhận ra chữ viết là của người anh đã xa nhà."
    follow_up = "Cô quyết định đến bến xe trước hoàng hôn để tìm người đưa thư trong bức ảnh."

    assert not is_repetitive_story_text(follow_up, first)


def test_assembled_story_gate_rejects_repeated_item_in_different_zone() -> None:
    script = [
        {"text": "Chiếc đèn đường chợt nhấp nháy khi trời bắt đầu tối gần cổng trường."},
        {"text": "Chiếc đèn đường chợt nhấp nháy khi trời bắt đầu tối trong hành lang thư viện."},
    ]

    with pytest.raises(ValueError, match="closely repeats"):
        validate_story_repetition(script)  # type: ignore[arg-type]


def _zone(zone: str, start: int = 1) -> OrderedObject:
    return OrderedObject(
        [
            ("schema_version", "1.0"),
            ("zone", zone),
            ("status", "PASS"),
            (
                "items",
                [
                    OrderedObject(
                        [
                            ("item_id", f"raw_{start + i}"),
                            ("speaker_id", "narrator"),
                            ("voice", "narrator"),
                            ("speed", "1.0"),
                            ("environment", "room"),
                            ("text", f"Sentence {start + i}."),
                        ]
                    )
                    for i in range(5)
                ],
            ),
        ]
    )


def test_aggregate_zone_payloads_reorders_ids_and_zones() -> None:
    zones = {zone: _zone(zone, i * 5) for i, zone in enumerate(ZONE_ORDER)}
    story = aggregate_zone_payloads("Title", [], "Premise", "Ending", zones, language="en")
    assert len(story["script"]) == 40
    assert list(story["outline"]) == [zone.lower() for zone in ZONE_ORDER]
    assert "premise" not in story["outline"]
    assert list(story["script"][0]) == ["zone", "environment", "voice", "speed", "lang", "text"]
    assert story["script"][0] == {
        "zone": "GREETING",
        "environment": "none",
        "voice": "NARRATOR",
        "speed": "NORMAL",
        "lang": "EN",
        "text": "Sentence 0.",
    }
    assert [item["zone"] for item in story["script"]][::5] == list(ZONE_ORDER)


def test_zone_payload_rejects_wrong_count() -> None:
    value = _zone(ZONE_ORDER[0])
    value["items"] = value["items"][:4]
    with pytest.raises(ValueError, match="item count"):
        validate_zone_payload(value, ZONE_ORDER[0])


def test_aggregate_requires_canonical_zone_order() -> None:
    zones = {zone: _zone(zone) for zone in reversed(ZONE_ORDER)}
    with pytest.raises(ValueError, match="canonical order"):
        aggregate_zone_payloads("Title", [], "Premise", "Ending", zones)


def test_zone_payload_enforces_word_budget() -> None:
    value = _zone(ZONE_ORDER[0])
    with pytest.raises(ValueError, match="below its word budget"):
        validate_zone_payload(value, ZONE_ORDER[0], minimum_words=20, maximum_words=30)
    for item in value["items"]:
        item["text"] = "one two three four."
    assert validate_zone_payload(value, ZONE_ORDER[0], minimum_words=20, maximum_words=20) is value
    with pytest.raises(ValueError, match="exceeds its word budget"):
        validate_zone_payload(value, ZONE_ORDER[0], minimum_words=1, maximum_words=19)


def test_zone_payload_accepts_cjk_terminal_sentence_punctuation() -> None:
    value = _zone(ZONE_ORDER[0])
    for item in value["items"]:
        item["text"] = "欢迎来到故事世界。"

    story = aggregate_zone_payloads(
        "Title",
        [],
        "Premise",
        "Ending",
        {zone: value if zone == ZONE_ORDER[0] else _zone(zone) for zone in ZONE_ORDER},
    )

    assert story["outline"]["greeting"] == "欢迎来到故事世界。"


@pytest.mark.parametrize(
    "text",
    [
        "Cô ấy hỏi: 'Có ai ở đó?'",
        'He said, "Wait!"',
        "Cô ấy tìm thấy ghi chú (và mỉm cười).",
        "Anh khép sổ lại (thật nhẹ).",
    ],
)
def test_terminal_sentence_punctuation_accepts_closed_quotes_and_brackets(text: str) -> None:
    assert has_terminal_sentence_punctuation(text)


@pytest.mark.parametrize("text", ["Cô ấy hỏi: 'Có ai ở đó'", "Anh khép sổ lại)"])
def test_terminal_sentence_punctuation_rejects_a_closer_without_terminator(text: str) -> None:
    assert not has_terminal_sentence_punctuation(text)


def test_zone_payload_counts_each_cjk_ideograph_for_its_word_budget() -> None:
    value = _zone(ZONE_ORDER[0])
    for item in value["items"]:
        item["text"] = "欢迎来到故事世界。"

    assert validate_zone_payload(value, ZONE_ORDER[0], minimum_words=40, maximum_words=40) is value
