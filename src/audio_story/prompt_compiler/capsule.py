"""Deterministic ACTIVE_STAGE_CAPSULE compilation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from audio_story.domain.enums import FindingSeverity
from audio_story.domain.errors import CompilerError
from audio_story.domain.models import (
    ActiveStageCapsule,
    CompileRequest,
    CompilerFinding,
    ParsedPrompt,
)
from audio_story.prompt_compiler.dependency import build_graph, dependency_closure
from audio_story.prompt_compiler.registry import registry_map

LEGACY_GUARD = "EXACT_VERSION_LEGACY_INPUT"
AUDIT_GUARD = "EXPLICIT_FRAMEWORK_RELEASE_AUDIT_ONLY"


def compile_capsule(parsed: ParsedPrompt, request: CompileRequest) -> ActiveStageCapsule:
    """Compile one deterministic active capsule from a previously parsed prompt."""
    registries = registry_map(parsed)
    route_value = registries["COMPACT_ROUTE_REGISTRY_JSON"].value
    if not isinstance(route_value, dict):
        raise CompilerError(
            "PC007_INVALID_REGISTRY_JSON",
            "route registry must be an object",
            registries["COMPACT_ROUTE_REGISTRY_JSON"].span,
        )
    always = _strings(route_value.get("always"))
    profiles = route_value.get("profiles")
    stages = route_value.get("stages")
    if not isinstance(profiles, dict) or not isinstance(stages, dict):
        raise CompilerError(
            "PC013_INVALID_ROUTE_REGISTRY",
            "profiles and stages must be objects",
            registries["COMPACT_ROUTE_REGISTRY_JSON"].span,
        )
    profile_module = profiles.get(request.profile.value)
    stage_entry = stages.get(request.stage.value)
    if not isinstance(profile_module, str) or not isinstance(stage_entry, dict):
        raise CompilerError(
            "PC013_INVALID_ROUTE_REGISTRY",
            "requested route is not declared",
            registries["COMPACT_ROUTE_REGISTRY_JSON"].span,
        )
    active_blocks = set(always + [profile_module] + _strings(stage_entry.get("include")))
    if LEGACY_GUARD in request.activation_guards:
        active_blocks.add("LEGACY_INPUT_COMPATIBILITY")
    if AUDIT_GUARD in request.activation_guards:
        active_blocks.add("FRAMEWORK_RELEASE_AUDIT")
    forbidden = set(_strings(stage_entry.get("forbid")))
    if active_blocks & forbidden:
        raise CompilerError(
            "PC014_FORBIDDEN_ROUTE_BLOCK",
            "route includes a forbidden block",
            registries["COMPACT_ROUTE_REGISTRY_JSON"].span,
        )

    owners = {unit.identifier: unit for unit in parsed.units}
    graph = build_graph(parsed, registries)
    active_owner_ids = {
        unit.identifier for unit in parsed.units if unit.owner_block in active_blocks
    }
    roots = _entrypoints(parsed, request)
    closure = set(dependency_closure(graph, roots))
    selected_ids = closure & active_owner_ids
    selected = sorted(
        (owners[item] for item in selected_ids), key=lambda unit: unit.span.start_byte
    )
    dormant = sorted(
        ({target for source in selected_ids for target in graph.get(source, ())} - selected_ids),
    )
    bindings = [
        {"symbol": symbol, "sha256": registries[symbol].sha256} for symbol in sorted(registries)
    ]
    document: dict[str, Any] = {
        "schema_version": "1.9",
        "stage": request.stage.value,
        "profile": request.profile.value,
        "route": request.route.value,
        "canonical_prompt_sha256": parsed.source_sha256,
        "active_blocks": sorted(active_blocks),
        "source_spans": [
            {
                "identifier": unit.identifier,
                "start_line": unit.span.start_line,
                "end_line": unit.span.end_line,
                "start_byte": unit.span.start_byte,
                "end_byte": unit.span.end_byte,
            }
            for unit in selected
        ],
        "ordered_unit_identifiers": [unit.identifier for unit in selected],
        "units": [
            {
                "identifier": unit.identifier,
                "kind": unit.kind.value,
                "sha256": unit.sha256,
                "content_utf8": unit.content.decode("utf-8"),
            }
            for unit in selected
        ],
        "registry_binding_digests": bindings,
        "dormant_dependency_records": [
            {"identifier": item, "reason": "DORMANT_ROUTE_DEPENDENCY"} for item in dormant
        ],
    }
    preimage = _canonical_json(document)
    digest = hashlib.sha256(preimage).hexdigest()
    document["capsule_digest"] = digest
    canonical = _canonical_json(document)
    return ActiveStageCapsule(document, canonical, digest)


def audio_mode_collision_finding(parsed: ParsedPrompt) -> CompilerFinding | None:
    """Return the stable v3.16.13 Stage 4 default collision finding, if present."""
    registries = registry_map(parsed)
    audio = registries["STAGE4_AUDIO_PROJECTION_REGISTRY_JSON"]
    value_text = _canonical_json(audio.value).decode("utf-8")
    source_text = b"".join(
        unit.content
        for unit in parsed.units
        if unit.identifier in {"COMPACT-RUNTIME-SELF-CHECK-01", "STAGE4-CONFIG-RESOLUTION-01"}
    )
    canonical = next(
        (
            unit
            for unit in parsed.units
            if b"VIDEO_PROMPT_DEFAULT_CONFIG" in unit.content
            and b"audio_mode:NATIVE_DIALOGUE" in unit.content
        ),
        None,
    )
    if canonical and b"NATIVE_DIALOGUE" in source_text and '"AMBIENCE_ONLY"' in value_text:
        spans = (canonical.span, audio.span)
        return CompilerFinding(
            "PCF001_STAGE4_AUDIO_MODE_DEFAULT_COLLISION",
            FindingSeverity.ERROR,
            "VIDEO_PROMPT_DEFAULT_CONFIG and runtime self-check require NATIVE_DIALOGUE, "
            "while STAGE4_AUDIO_PROJECTION_REGISTRY_JSON maps default/ABSENT to "
            "AMBIENCE_ONLY; no value was selected.",
            spans,
        )
    return None


def _entrypoints(parsed: ParsedPrompt, request: CompileRequest) -> list[str]:
    constants = next(
        (unit for unit in parsed.units if b"HOT_PATH_STAGE_ENTRYPOINTS" in unit.content), None
    )
    text = constants.content.decode("utf-8") if constants else ""
    roots = [
        "CAPABILITY-RESOLUTION-ORDER-01",
        "RELEASE-ASSURANCE-MODE-01",
        "HOT-PATH-DEPENDENCY-MANIFEST-01",
        "STAGE-MODEL-RECOMMENDATION-01",
    ]
    stage_match = _inline_list(text, "HOT_PATH_STAGE_ENTRYPOINTS", request.stage.value)
    profile_match = _inline_list(
        text, "HOT_PATH_PROFILE_ENTRYPOINTS", request.stage.value, request.profile.value
    )
    return roots + stage_match + profile_match


def _inline_list(text: str, symbol: str, *keys: str) -> list[str]:
    line = next((line for line in text.splitlines() if symbol in line), "")
    position = 0
    for key in keys:
        position = line.find(key, position)
        if position < 0:
            return []
        position += len(key)
    start = line.find("[", position)
    end = line.find("]", start)
    if start < 0 or end < 0:
        return []
    return [item.strip() for item in line[start + 1 : end].split(",") if item.strip()]


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
