"""Dependency graph construction and closure checks."""

from __future__ import annotations

import re
from collections.abc import Iterable

from audio_story.domain.errors import CompilerError
from audio_story.domain.models import ParsedPrompt, RegistryBinding
from audio_story.prompt_compiler.registry import alias_entries

REFERENCE = re.compile(rb"\b[A-Z][A-Z0-9-]*-[A-Z0-9-]+\b")


def build_graph(
    parsed: ParsedPrompt, registries: dict[str, RegistryBinding]
) -> dict[str, tuple[str, ...]]:
    owners = {unit.identifier: unit for unit in parsed.units}
    aliases = alias_entries(registries)
    graph: dict[str, tuple[str, ...]] = {}
    for alias, entry in aliases.items():
        target = entry.get("target")
        if target is None:
            graph[alias] = ()
            continue
        if not isinstance(target, str):
            raise CompilerError(
                "PC009_INVALID_ALIAS_TARGET",
                f"target for {alias} must be a string",
                registries["HOT_PATH_RULE_RESOLUTION_REGISTRY_JSON"].span,
            )
        if target == alias:
            raise CompilerError(
                "PC010_SELF_TARGET",
                f"{alias} targets itself",
                registries["HOT_PATH_RULE_RESOLUTION_REGISTRY_JSON"].span,
            )
        if target not in owners and target not in aliases:
            raise CompilerError(
                "PC011_MISSING_TARGET",
                f"{alias} targets missing owner {target}",
                registries["HOT_PATH_RULE_RESOLUTION_REGISTRY_JSON"].span,
            )
        graph[alias] = (target,)
    _assert_acyclic(graph, registries["HOT_PATH_RULE_RESOLUTION_REGISTRY_JSON"])
    for unit in parsed.units:
        references = {match.group().decode("ascii") for match in REFERENCE.finditer(unit.content)}
        graph[unit.identifier] = tuple(
            sorted((references & (owners.keys() | aliases.keys())) - {unit.identifier})
        )
    return graph


def dependency_closure(graph: dict[str, tuple[str, ...]], roots: Iterable[str]) -> tuple[str, ...]:
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        visited.add(node)
        for target in graph.get(node, ()):
            visit(target)

    for root in roots:
        visit(root)
    return tuple(sorted(visited))


def _assert_acyclic(graph: dict[str, tuple[str, ...]], binding: RegistryBinding) -> None:
    visited: set[str] = set()
    active: set[str] = set()

    def visit(node: str) -> None:
        if node in active:
            raise CompilerError("PC012_DEPENDENCY_CYCLE", f"cycle includes {node}", binding.span)
        if node in visited:
            return
        active.add(node)
        for target in graph.get(node, ()):
            visit(target)
        active.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
