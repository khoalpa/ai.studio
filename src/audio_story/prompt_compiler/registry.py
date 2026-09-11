"""Canonical owner and structural registry validation."""

from __future__ import annotations

from typing import Any

from audio_story.domain.errors import CompilerError, SourceSpan
from audio_story.domain.models import ParsedPrompt, RegistryBinding

REQUIRED_STRUCTURAL_REGISTRIES = frozenset(
    {
        "HOT_PATH_RULE_RESOLUTION_REGISTRY_JSON",
        "COMPACT_ROUTE_REGISTRY_JSON",
        "PHYSICAL_INVENTORY_REGISTRY_JSON",
        "OVERLAY_ACTIVATION_REGISTRY_JSON",
        "CRITICAL_RULE_OWNER_LOCATION_REGISTRY_JSON",
        "OVERLAY_BODY_ISOLATION_REGISTRY_JSON",
        "STAGE4_AUDIO_PROJECTION_REGISTRY_JSON",
        "HOT_PATH_UNIT_CLASSIFICATION_REGISTRY_JSON",
        "CROSS_STAGE_PERSISTED_DEPENDENCY_ALLOWLIST_JSON",
        "SAFETY_GATE_BINDINGS_JSON",
        "HOT_PATH_JSON_REGISTRY_ACCESS_POLICY_JSON",
    }
)


def registry_map(parsed: ParsedPrompt) -> dict[str, RegistryBinding]:
    result = {binding.symbol: binding for binding in parsed.registries}
    missing = sorted(REQUIRED_STRUCTURAL_REGISTRIES - result.keys())
    if missing:
        span = SourceSpan(1, 1, 0, 0)
        raise CompilerError(
            "PC008_MISSING_REGISTRY", f"missing registries: {', '.join(missing)}", span
        )
    return result


def alias_entries(registries: dict[str, RegistryBinding]) -> dict[str, dict[str, Any]]:
    value = registries["HOT_PATH_RULE_RESOLUTION_REGISTRY_JSON"].value
    entries = value.get("entries") if isinstance(value, dict) else None
    if not isinstance(entries, dict):
        binding = registries["HOT_PATH_RULE_RESOLUTION_REGISTRY_JSON"]
        raise CompilerError(
            "PC007_INVALID_REGISTRY_JSON", "alias entries must be an object", binding.span
        )
    return {str(key): item for key, item in entries.items() if isinstance(item, dict)}
