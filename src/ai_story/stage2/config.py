from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..config import project_root, registry
from ..errors import ConfigurationError, WorkflowError


@lru_cache(maxsize=1)
def stage2_config() -> dict[str, Any]:
    try:
        return json.loads((project_root() / "spec" / "stage2.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot load Stage 2 config: {exc}") from exc


def resolve_image_mode(requested: str | None) -> str:
    value = requested or stage2_config()["enabled_mode"]
    if value != "ZONE":
        raise WorkflowError("Only ZONE image mode is enabled for Stage 2")
    return value


def basenames() -> list[str]:
    return list(registry()["zone_image_basenames"])
