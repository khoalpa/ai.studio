from __future__ import annotations

import hashlib

import pytest

from audio_story.domain.enums import UnitKind
from audio_story.domain.errors import CompilerError, SourceSpan
from audio_story.domain.models import ParsedPrompt, PromptUnit, RegistryBinding
from audio_story.prompt_compiler.dependency import build_graph, dependency_closure

SPAN = SourceSpan(1, 1, 0, 1)


def _parsed() -> ParsedPrompt:
    content = b"TARGET-RULE-01:\n"
    unit = PromptUnit(
        "TARGET-RULE-01",
        UnitKind.CANONICAL_RULE_BLOCK,
        "ONE",
        SPAN,
        content,
        hashlib.sha256(content).hexdigest(),
    )
    return ParsedPrompt("0" * 64, len(content), (), (unit,), ())


def _registries(entries: dict[str, object]) -> dict[str, RegistryBinding]:
    binding = RegistryBinding(
        "HOT_PATH_RULE_RESOLUTION_REGISTRY_JSON",
        {"entries": entries},
        SPAN,
        "1" * 64,
    )
    return {binding.symbol: binding}


def test_alias_closure_resolves_target() -> None:
    graph = build_graph(
        _parsed(),
        _registries({"ALIAS-RULE-01": {"resolution_kind": "ALIAS", "target": "TARGET-RULE-01"}}),
    )
    assert dependency_closure(graph, ["ALIAS-RULE-01"]) == (
        "ALIAS-RULE-01",
        "TARGET-RULE-01",
    )


@pytest.mark.parametrize(
    ("entries", "code"),
    [
        ({"ALIAS-RULE-01": {"target": 42}}, "PC009_INVALID_ALIAS_TARGET"),
        ({"ALIAS-RULE-01": {"target": "ALIAS-RULE-01"}}, "PC010_SELF_TARGET"),
        ({"ALIAS-RULE-01": {"target": "MISSING-RULE-01"}}, "PC011_MISSING_TARGET"),
        (
            {
                "ALIAS-A-01": {"target": "ALIAS-B-01"},
                "ALIAS-B-01": {"target": "ALIAS-A-01"},
            },
            "PC012_DEPENDENCY_CYCLE",
        ),
    ],
)
def test_invalid_alias_graph_is_rejected(entries: dict[str, object], code: str) -> None:
    with pytest.raises(CompilerError) as caught:
        build_graph(_parsed(), _registries(entries))
    assert caught.value.code == code


def test_external_audit_alias_may_have_null_target() -> None:
    graph = build_graph(_parsed(), _registries({"AUDIT-RULE-01": {"target": None}}))
    assert graph["AUDIT-RULE-01"] == ()
