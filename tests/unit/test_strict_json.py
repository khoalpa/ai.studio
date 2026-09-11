from __future__ import annotations

import math

import pytest

from audio_story.validation.canonical import canonical_json_bytes, digest_json
from audio_story.validation.errors import ValidationError
from audio_story.validation.limits import ValidationLimits
from audio_story.validation.strict_json import parse_json_bytes, validate_field_order


def _code(data: bytes, **kwargs: object) -> str:
    with pytest.raises(ValidationError) as caught:
        parse_json_bytes(data, "fixture.json", **kwargs)  # type: ignore[arg-type]
    return caught.value.finding.code


def test_valid_json_preserves_nested_order() -> None:
    parsed = parse_json_bytes(b'{"a":1,"nested":{"x":1,"y":2}}', "fixture.json")
    validate_field_order(parsed.value, ("a", "nested"), "fixture.json")
    validate_field_order(parsed.value["nested"], ("x", "y"), "fixture.json", "$.nested")


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"\xef\xbb\xbf{}", "DJ002_UTF8_BOM"),
        (b'"\xff"', "DJ003_INVALID_UTF8"),
        (b'{"a":1,"a":2}', "DJ004_DUPLICATE_KEY"),
        ('{"é":1,"é":2}'.encode(), "DJ005_NFC_DUPLICATE_KEY"),
        (b'{"a":NaN}', "DJ006_NON_FINITE_NUMBER"),
        (b'{"a":Infinity}', "DJ006_NON_FINITE_NUMBER"),
        (b'{/* comment */"a":1}', "DJ007_JSON_SYNTAX"),
        (b"{} trailing", "DJ008_TRAILING_DATA"),
    ],
)
def test_strict_json_rejections(data: bytes, code: str) -> None:
    assert _code(data) == code


def test_size_and_depth_limits() -> None:
    tiny = ValidationLimits(max_json_bytes=2, max_json_depth=1)
    assert _code(b'{"a":1}', limits=tiny) == "DJ001_JSON_SIZE_LIMIT"
    depth = ValidationLimits(max_json_bytes=100, max_json_depth=1)
    assert _code(b'{"a":{"b":1}}', limits=depth) == "DJ013_JSON_DEPTH_LIMIT"


def test_engine_generated_json_requires_nfc_keys_and_strings() -> None:
    assert _code('{"key":"é"}'.encode(), engine_generated=True) == "DJ014_NON_NFC_STRING"
    assert _code('{"é":"ok"}'.encode(), engine_generated=True) == "DJ015_NON_NFC_KEY"


@pytest.mark.parametrize(
    ("data", "expected", "code"),
    [
        (b'{"a":1}', ("a", "b"), "DJ010_MISSING_FIELD"),
        (b'{"a":1,"b":2}', ("a",), "DJ011_EXTRA_FIELD"),
        (b'{"b":2,"a":1}', ("a", "b"), "DJ012_FIELD_ORDER"),
    ],
)
def test_field_order_failures(data: bytes, expected: tuple[str, ...], code: str) -> None:
    value = parse_json_bytes(data, "fixture.json").value
    with pytest.raises(ValidationError) as caught:
        validate_field_order(value, expected, "fixture.json")
    assert caught.value.finding.code == code


def test_canonical_serialization_and_digest_are_stable() -> None:
    first = canonical_json_bytes({"é": [1, "é"]})
    second = canonical_json_bytes({"é": [1, "é"]})
    assert first == second
    assert digest_json({"b": 2, "a": 1}) == digest_json({"a": 1, "b": 2})
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json_bytes({"x": math.inf})
