from __future__ import annotations

import pytest

from audio_story.domain.errors import CompilerError
from audio_story.prompt_compiler.parser import parse_prompt


def _prompt(body: bytes, identifier: bytes = b"ONE") -> bytes:
    return (
        b"===== MODULE:"
        + identifier
        + b" BEGIN =====\n"
        + body
        + b"===== MODULE:"
        + identifier
        + b" END =====\n"
    )


def test_parses_module_overlay_units_and_json_without_normalizing_bytes() -> None:
    source = (
        _prompt(b"RULE-ONE-01:\n- exact bytes\r\n")
        + b"===== OVERLAY:OPTIONAL BEGIN =====\n"
        + b'SAMPLE_REGISTRY_JSON:\n```json\n{"value":1}\n```\n'
        + b"OUTPUT TEMPLATE:\nvalue\n"
        + b"===== OVERLAY:OPTIONAL END =====\n"
    )
    parsed = parse_prompt(source)
    assert [block.identifier for block in parsed.blocks] == ["ONE", "OPTIONAL"]
    assert {unit.identifier for unit in parsed.units} == {
        "RULE-ONE-01",
        "SAMPLE_REGISTRY_JSON",
        "OUTPUT_TEMPLATE",
    }
    assert parsed.registries[0].value == {"value": 1}
    assert parsed.source_size == len(source)


@pytest.mark.parametrize(
    ("source", "code"),
    [
        (b"===== MODULE:X START =====\n", "PC001_MALFORMED_MARKER"),
        (b"===== MODULE:X END =====\n", "PC002_UNMATCHED_MARKER"),
        (b"===== MODULE:X BEGIN =====\n", "PC002_UNMATCHED_MARKER"),
        (
            b"===== MODULE:X BEGIN =====\n===== MODULE:Y BEGIN =====\n",
            "PC003_NESTED_MARKER",
        ),
        (
            b"===== MODULE:X BEGIN =====\n===== MODULE:Y END =====\n",
            "PC004_CROSSED_MARKER",
        ),
        (
            _prompt(b"") + _prompt(b"", b"ONE"),
            "PC005_DUPLICATE_PHYSICAL_BLOCK",
        ),
    ],
)
def test_marker_failures_have_stable_code_and_span(source: bytes, code: str) -> None:
    with pytest.raises(CompilerError) as caught:
        parse_prompt(source)
    assert caught.value.code == code
    assert caught.value.span.start_line >= 1


def test_duplicate_canonical_owner_is_rejected() -> None:
    with pytest.raises(CompilerError, match="PC006_DUPLICATE_CANONICAL_OWNER"):
        parse_prompt(_prompt(b"SAME-RULE-01:\na\n") + _prompt(b"SAME-RULE-01:\nb\n", b"TWO"))


def test_invalid_structural_json_is_rejected() -> None:
    with pytest.raises(CompilerError, match="PC007_INVALID_REGISTRY_JSON"):
        parse_prompt(_prompt(b"BROKEN_REGISTRY_JSON:\n```json\n{broken}\n```\n"))


def test_registry_without_json_fence_is_rejected() -> None:
    with pytest.raises(CompilerError, match="PC007_INVALID_REGISTRY_JSON"):
        parse_prompt(_prompt(b"BROKEN_REGISTRY_JSON:\nnot json\n"))
