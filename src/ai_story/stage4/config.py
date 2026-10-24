from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..config import project_root
from ..errors import ConfigurationError, WorkflowError


@lru_cache(maxsize=1)
def stage4_config() -> dict[str, Any]:
    try:
        return json.loads((project_root() / "spec" / "stage4.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot load Stage 4 config: {exc}") from exc


def validate_options(aspect_ratio: str, coverage_mode: str) -> None:
    if aspect_ratio not in {"LANDSCAPE_16_9", "PORTRAIT_9_16"}:
        raise WorkflowError("Invalid Stage 4 aspect ratio")
    if coverage_mode != "FULL_STORY":
        raise WorkflowError("Only FULL_STORY coverage is enabled in this milestone")
