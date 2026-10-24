from __future__ import annotations

import copy
import json
import os
import platform
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import project_root
from .errors import ConfigurationError
from .hashing import sha256_file
from .image_models import ImageModelProfile, resolve_image_model_profile
from .model_operations import apply_quality_preset, process_peak_memory_bytes

PROVIDER_MODES = {"deterministic", "local", "local_sd35", "hybrid", "text_local"}
PROVIDER_ROLES = {"story", "character_image", "safety", "landscape", "portrait"}


@lru_cache(maxsize=4)
def load_provider_config(mode_override: str | None = None) -> dict[str, Any]:
    path = Path(os.environ.get("AI_STORY_PROVIDER_CONFIG", project_root() / "spec" / "providers.json"))
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot load provider configuration: {exc}") from exc
    mode = mode_override or os.environ.get("AI_STORY_PROVIDER_MODE") or document.get("active_mode")
    if mode not in PROVIDER_MODES:
        raise ConfigurationError(f"Unsupported provider mode: {mode}")
    modes = document.get("modes", {})
    adapters = document.get("adapters", {})
    selected = modes.get(mode)
    if not isinstance(selected, dict) or set(selected) != PROVIDER_ROLES:
        raise ConfigurationError(f"Provider mode {mode} must configure every canonical role")
    missing = sorted({adapter for adapter in selected.values() if adapter not in adapters})
    if missing:
        raise ConfigurationError(f"Provider configuration references unknown adapters: {missing}")
    runtimes = document.get("runtimes", {})
    image_models = document.get("image_models", {})
    if not isinstance(image_models, dict) or not image_models:
        raise ConfigurationError("Provider configuration requires image model profiles")
    for profile_id, value in image_models.items():
        ImageModelProfile.from_config(profile_id, value)
    missing_runtimes = sorted(
        {
            adapters[adapter]["runtime"]
            for adapter in selected.values()
            if adapters[adapter].get("runtime") not in runtimes
        }
    )
    if missing_runtimes:
        raise ConfigurationError(
            f"Provider configuration references unknown runtimes: {missing_runtimes}"
        )
    for adapter_name in set(selected.values()):
        adapter = adapters[adapter_name]
        if adapter.get("runtime") == "diffusers":
            resolve_image_model_profile(document, adapter)
    policy = document.get("policy", {})
    if policy.get("fallback") != "disabled":
        raise ConfigurationError("MVP provider fallback must be explicitly disabled")
    document["active_mode"] = mode
    document["selected"] = selected
    document["config_path"] = str(path.resolve())
    depth_override = os.environ.get("AI_STORY_DEPTH_CONTROLNET")
    if depth_override is not None:
        normalized = depth_override.strip().casefold()
        if normalized not in {"0", "1", "false", "true", "off", "on"}:
            raise ConfigurationError(
                "AI_STORY_DEPTH_CONTROLNET must be 0/1, false/true or off/on"
            )
        document["runtimes"]["diffusers"]["depth_controlnet_enabled"] = normalized in {
            "1", "true", "on",
        }
    return document


def apply_model_overrides(
    config: dict[str, Any], overrides: dict[str, dict[str, Any]] | None
) -> dict[str, Any]:
    """Return an isolated provider config with request-scoped model bindings.

    The base specification remains immutable, which is important because web jobs may
    run concurrently with different model choices.
    """
    result = copy.deepcopy(config)
    for role, model in (overrides or {}).items():
        if role not in PROVIDER_ROLES:
            raise ConfigurationError(f"Unknown provider role: {role}")
        adapter_name = result["selected"][role]
        override_adapter_name = f"{adapter_name}__{role}"
        result["adapters"][override_adapter_name] = copy.deepcopy(
            result["adapters"][adapter_name]
        )
        result["selected"][role] = override_adapter_name
        adapter = result["adapters"][override_adapter_name]
        if adapter.get("runtime") == "builtin":
            raise ConfigurationError(
                f"Role '{role}' cannot select a model in deterministic mode"
            )
        adapter["model_id"] = model.get("model_id") or model.get("path")
        adapter["model_file"] = model.get("path")
        adapter["quantization"] = model.get("quantization")
        adapter["catalog_id"] = model.get("id")
        if model.get("model_profile"):
            adapter["model_profile"] = model["model_profile"]
            profile = resolve_image_model_profile(result, adapter)
            adapter["parameters"] = {
                **profile.parameters,
                **dict(model.get("parameters", {})),
            }
    return result


def configure_job(
    mode_override: str | None, model_overrides: dict[str, dict[str, Any]] | None,
    quality_preset: str | None = None,
) -> dict[str, Any]:
    return apply_quality_preset(
        apply_model_overrides(load_provider_config(mode_override), model_overrides), quality_preset
    )


def adapter_metadata(
    role: str, provider_id: str, mode_override: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_provider_config(mode_override)
    adapter_name = config["selected"][role]
    adapter = config["adapters"][adapter_name]
    model_file = adapter.get("model_file")
    digest = None
    if model_file:
        path = Path(model_file).expanduser()
        if path.is_file():
            digest = sha256_file(path)
    return {
        "role": role,
        "adapter": adapter_name,
        "provider_id": provider_id,
        "runtime": adapter.get("runtime"),
        "model_id": adapter.get("model_id"),
        "model_file_sha256": digest,
        "quantization": adapter.get("quantization"),
        "catalog_id": adapter.get("catalog_id"),
        "model_profile": adapter.get("model_profile"),
        "model_family": (
            resolve_image_model_profile(config, adapter).family
            if adapter.get("runtime") == "diffusers" else None
        ),
        "parameters": adapter.get("parameters", {}),
    }


def generation_metadata(
    providers: list[tuple[str, str]],
    prompt_template_version: str | None = None,
    mode_override: str | None = None,
    config: dict[str, Any] | None = None,
    runtime_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_provider_config(mode_override)
    metrics = dict(runtime_metrics or {"call_count": 0, "attempt_count": 0, "retry_count": 0, "failure_count": 0, "duration_ms": 0.0})
    calls = max(0, int(metrics.get("call_count", 0)))
    retries = max(0, int(metrics.get("retry_count", 0)))
    attempts = max(calls + retries, int(metrics.get("attempt_count", calls)))
    failures = max(0, int(metrics.get("failure_count", 0)))
    metrics["call_count"] = calls
    metrics["attempt_count"] = attempts
    metrics["retry_count"] = retries
    metrics["failure_count"] = failures
    duration_ms = max(
        0.0,
        float(metrics.get("wall_clock_duration_ms", metrics.get("duration_ms", 0.0))),
    )
    operational_metrics = {
        "completion_rate": round((calls - failures) / calls, 4) if calls else 1.0,
        "retry_rate": round(retries / attempts, 4) if attempts else 0.0,
        "failure_rate": round(failures / attempts, 4) if attempts else 0.0,
        "duration_seconds": round(duration_ms / 1000, 4),
        "call_count": calls,
        "attempt_count": attempts,
    }
    return {
        "provider_mode": config["active_mode"],
        "providers": [
            adapter_metadata(role, provider_id, mode_override, config) for role, provider_id in providers
        ],
        "prompt_template_version": prompt_template_version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": sys.platform,
        },
        "peak_memory_bytes": process_peak_memory_bytes(),
        "quality_preset": config.get("quality_preset", "balanced"),
        "image_candidate_policy": config.get("image_candidate_policy", {}),
        "runtime_metrics": metrics,
        "operational_metrics": operational_metrics,
        "runtime_metrics_lineage": [{
            "roles": [role for role, _ in providers],
            "quality_preset": config.get("quality_preset", "balanced"),
            "metrics": metrics,
        }],
    }


def merge_generation_metadata(
    parent: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Accumulate provider provenance while keeping the current stage runtime metadata."""
    parent_providers = parent.get("providers", []) if isinstance(parent, dict) else []
    current_providers = current.get("providers", [])
    by_role = {
        str(item.get("role")): item
        for item in [*parent_providers, *current_providers]
        if isinstance(item, dict) and item.get("role")
    }
    lineage = list(parent.get("provider_mode_lineage", [])) if isinstance(parent, dict) else []
    parent_mode = parent.get("provider_mode") if isinstance(parent, dict) else None
    if not lineage and parent_mode:
        lineage.append(parent_mode)
    current_mode = current.get("provider_mode")
    if current_mode and (not lineage or lineage[-1] != current_mode):
        lineage.append(current_mode)
    current["providers"] = list(by_role.values())
    current["provider_mode_lineage"] = lineage
    current["runtime_metrics_lineage"] = [
        *(parent.get("runtime_metrics_lineage", []) if isinstance(parent, dict) else []),
        *current.get("runtime_metrics_lineage", []),
    ]
    current["operational_metrics_lineage"] = [
        *(parent.get("operational_metrics_lineage", []) if isinstance(parent, dict) else []),
        {"roles": [item.get("role") for item in current.get("providers", [])], "metrics": current.get("operational_metrics", {})},
    ]
    return current


def require_builtin_adapter(role: str, allowed: set[str]) -> str:
    config = load_provider_config()
    adapter = config["selected"][role]
    if adapter not in allowed:
        raise ConfigurationError(
            f"Provider adapter '{adapter}' for role '{role}' is configured but not installed; "
            "use deterministic mode until the local adapter is available"
        )
    return adapter
