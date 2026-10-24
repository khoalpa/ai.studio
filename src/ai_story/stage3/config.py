from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..config import project_root
from ..errors import ConfigurationError


@lru_cache(maxsize=1)
def stage3_config() -> dict[str, Any]:
    try:
        return json.loads((project_root() / "spec" / "stage3.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot load Stage 3 config: {exc}") from exc
