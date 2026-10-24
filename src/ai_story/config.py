from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def registry() -> dict[str, Any]:
    path = project_root() / "spec" / "registry.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot load canonical registry: {exc}") from exc


@lru_cache(maxsize=1)
def mvp_contract() -> dict[str, Any]:
    path = project_root() / "spec" / "mvp_contract.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot load MVP contract: {exc}") from exc
