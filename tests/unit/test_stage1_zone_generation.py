import pytest

from audio_story.validation.stage1 import ZONE_ORDER
from audio_story.validation.strict_json import OrderedObject
from audio_story.workflows.stage1_zone_generation import (
    aggregate_zone_payloads,
    validate_zone_payload,
)


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
    story = aggregate_zone_payloads("Title", [], "Premise", "Ending", zones)
    assert len(story["script"]) == 40
    assert story["script"][0]["item_id"] == "item_001"
    assert story["script"][-1]["item_id"] == "item_040"
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
