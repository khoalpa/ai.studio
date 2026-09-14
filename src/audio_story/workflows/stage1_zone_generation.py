"""Deterministic contract and aggregation for bounded Stage 1 zone generation."""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any, cast

from audio_story.validation.stage1 import ZONE_ORDER
from audio_story.validation.strict_json import OrderedObject, validate_field_order

ZONE_PAYLOAD_ORDER = ("schema_version", "zone", "status", "items")
ZONE_ITEM_ORDER = ("item_id", "speaker_id", "voice", "speed", "environment", "text")


def validate_zone_payload(
    value: Any,
    zone: str,
    expected_count: int = 5,
    minimum_words: int | None = None,
    maximum_words: int | None = None,
) -> OrderedObject:
    """Validate one compact zone response before it can be aggregated."""
    if zone not in ZONE_ORDER:
        raise ValueError("unknown canonical zone")
    validate_field_order(value, ZONE_PAYLOAD_ORDER, "stage1_zone.json")
    if value["schema_version"] != "1.0" or value["zone"] != zone or value["status"] != "PASS":
        raise ValueError("zone response header is invalid")
    items = value["items"]
    if not isinstance(items, list) or len(items) != expected_count:
        raise ValueError("zone response item count is invalid")
    seen: set[str] = set()
    for item in items:
        validate_field_order(item, ZONE_ITEM_ORDER, "stage1_zone.json")
        if item["item_id"] in seen or not str(item["item_id"]).strip():
            raise ValueError("zone item IDs must be unique")
        seen.add(item["item_id"])
        for key in ZONE_ITEM_ORDER[1:]:
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"zone item {key} must be non-empty")
        if not item["text"].rstrip().endswith((".", "!", "?")):
            raise ValueError("zone item text must be a complete sentence")
    item_words = [len(re.findall(r"\w+", item["text"], flags=re.UNICODE)) for item in items]
    words = sum(item_words)
    if minimum_words is not None:
        minimum_per_item = minimum_words // expected_count
        if any(count < minimum_per_item for count in item_words):
            raise ValueError("zone item is below its word budget")
    if maximum_words is not None:
        maximum_per_item = (maximum_words + expected_count - 1) // expected_count
        if any(count > maximum_per_item for count in item_words):
            raise ValueError("zone item exceeds its word budget")
    if minimum_words is not None and words < minimum_words:
        raise ValueError("zone response is below its word budget")
    if maximum_words is not None and words > maximum_words:
        raise ValueError("zone response exceeds its word budget")
    return cast(OrderedObject, value)


def aggregate_zone_payloads(
    title: str,
    characters: list[OrderedDict[str, Any]],
    premise: str,
    ending: str,
    zones: dict[str, OrderedObject],
    expected_counts: dict[str, int] | None = None,
    word_budgets: dict[str, tuple[int, int]] | None = None,
) -> OrderedDict[str, Any]:
    """Assemble validated zones into the existing serialize blueprint order."""
    if list(zones) != list(ZONE_ORDER):
        raise ValueError("zone payloads must be supplied in canonical order")
    script: list[OrderedDict[str, Any]] = []
    index = 1
    for zone in ZONE_ORDER:
        expected_count = 5 if expected_counts is None else expected_counts[zone]
        minimum_words, maximum_words = (None, None) if word_budgets is None else word_budgets[zone]
        payload = validate_zone_payload(
            zones[zone], zone, expected_count, minimum_words, maximum_words
        )
        for item in payload["items"]:
            script.append(
                OrderedDict(
                    item_id=f"item_{index:03d}",
                    zone=zone,
                    speaker_id=item["speaker_id"],
                    voice=item["voice"],
                    speed=item["speed"],
                    environment=item["environment"],
                    text=item["text"],
                )
            )
            index += 1
    return OrderedDict(
        title=title,
        characters=characters,
        outline=OrderedDict(premise=premise, ending=ending),
        script=script,
    )
