"""Strict UTF-8 JSON parser retaining object field order."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any

from audio_story.validation.errors import ValidationError, ValidationFinding
from audio_story.validation.limits import DEFAULT_LIMITS, ValidationLimits


class OrderedObject(dict[str, Any]):
    """Dictionary retaining the exact input member order."""

    def __init__(self, pairs: list[tuple[str, Any]]) -> None:
        super().__init__(pairs)
        self.field_order = tuple(key for key, _ in pairs)


@dataclass(frozen=True, slots=True)
class ParsedJson:
    value: Any
    source_bytes: bytes


def parse_json_bytes(
    data: bytes,
    artifact_path: str,
    *,
    engine_generated: bool = False,
    limits: ValidationLimits = DEFAULT_LIMITS,
) -> ParsedJson:
    if len(data) > limits.max_json_bytes:
        _fail("DJ001_JSON_SIZE_LIMIT", "JSON exceeds configured size limit", artifact_path)
    if data.startswith(b"\xef\xbb\xbf"):
        _fail("DJ002_UTF8_BOM", "UTF-8 BOM is forbidden", artifact_path, byte_offset=0)
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        _fail("DJ003_INVALID_UTF8", "invalid UTF-8", artifact_path, byte_offset=exc.start)

    def pairs_hook(pairs: list[tuple[str, Any]]) -> OrderedObject:
        raw: set[str] = set()
        normalized: set[str] = set()
        for key, _ in pairs:
            if key in raw:
                _fail("DJ004_DUPLICATE_KEY", f"duplicate key {key!r}", artifact_path, json_path="$")
            nfc = unicodedata.normalize("NFC", key)
            if nfc in normalized:
                _fail(
                    "DJ005_NFC_DUPLICATE_KEY",
                    f"NFC-colliding key {key!r}",
                    artifact_path,
                    json_path="$",
                )
            raw.add(key)
            normalized.add(nfc)
        return OrderedObject(pairs)

    def reject_constant(value: str) -> None:
        _fail("DJ006_NON_FINITE_NUMBER", f"non-finite number {value}", artifact_path)

    decoder = json.JSONDecoder(object_pairs_hook=pairs_hook, parse_constant=reject_constant)
    try:
        value, end = decoder.raw_decode(text)
    except json.JSONDecodeError as exc:
        _fail(
            "DJ007_JSON_SYNTAX",
            exc.msg,
            artifact_path,
            byte_offset=len(text[: exc.pos].encode("utf-8")),
            line=exc.lineno,
            column=exc.colno,
        )
    if text[end:].strip():
        _fail(
            "DJ008_TRAILING_DATA",
            "trailing data after JSON value",
            artifact_path,
            byte_offset=len(text[:end].encode("utf-8")),
        )
    _validate_tree(value, artifact_path, engine_generated, limits.max_json_depth)
    return ParsedJson(value, data)


def validate_field_order(
    value: Any, expected: tuple[str, ...], artifact_path: str, json_path: str = "$"
) -> None:
    if not isinstance(value, OrderedObject):
        _fail(
            "DJ009_EXPECTED_OBJECT", "ordered object required", artifact_path, json_path=json_path
        )
    actual = value.field_order
    if actual != expected:
        missing = [key for key in expected if key not in actual]
        extra = [key for key in actual if key not in expected]
        if missing:
            code = "DJ010_MISSING_FIELD"
        elif extra:
            code = "DJ011_EXTRA_FIELD"
        else:
            code = "DJ012_FIELD_ORDER"
        _fail(
            code, f"expected fields {expected}, found {actual}", artifact_path, json_path=json_path
        )


def _validate_tree(
    value: Any, path: str, engine_generated: bool, depth: int, json_path: str = "$"
) -> None:
    if depth < 0:
        _fail(
            "DJ013_JSON_DEPTH_LIMIT",
            "JSON nesting exceeds configured limit",
            path,
            json_path=json_path,
        )
    if isinstance(value, str):
        if engine_generated and not unicodedata.is_normalized("NFC", value):
            _fail(
                "DJ014_NON_NFC_STRING",
                "engine-generated string is not NFC",
                path,
                json_path=json_path,
            )
    elif isinstance(value, dict):
        for key, item in value.items():
            if engine_generated and not unicodedata.is_normalized("NFC", key):
                _fail(
                    "DJ015_NON_NFC_KEY",
                    "engine-generated key is not NFC",
                    path,
                    json_path=json_path,
                )
            _validate_tree(item, path, engine_generated, depth - 1, f"{json_path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_tree(item, path, engine_generated, depth - 1, f"{json_path}[{index}]")


def _fail(code: str, message: str, path: str, **locator: Any) -> None:
    raise ValidationError(ValidationFinding(code, message, path, **locator))
