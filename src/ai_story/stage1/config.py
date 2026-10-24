from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..config import project_root
from ..errors import ConfigurationError, WorkflowError
from ..models import Profile


@lru_cache(maxsize=1)
def stage1_config() -> dict[str, Any]:
    try:
        return json.loads((project_root() / "spec" / "stage1.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot load Stage 1 config: {exc}") from exc


@dataclass(frozen=True)
class DurationPlan:
    length_min: int
    length_max: int
    length_target: int
    target_wpm: int
    discriminator: str
    confirmed: bool = False

    @property
    def target_words(self) -> int:
        return round(self.length_target * self.target_wpm)


def suggested_duration(profile: Profile, discriminator: str | None = None) -> DurationPlan:
    key = profile.value
    if profile is Profile.SERIAL_DETECTIVE:
        mode = discriminator or "START_SERIES"
        if mode not in {"START_SERIES", "CONTINUE_SERIES", "FINALIZE_SERIES"}:
            raise WorkflowError("Serial duration requires a valid episode mode")
        key = f"SERIAL_DETECTIVE_{mode}"
    return DurationPlan(**stage1_config()["duration_defaults"][key], confirmed=False)


def confirm_duration(profile: Profile, minutes: int | None = None, discriminator: str | None = None) -> DurationPlan:
    suggested = suggested_duration(profile, discriminator)
    target = minutes if minutes is not None else suggested.length_target
    if not suggested.length_min <= target <= suggested.length_max:
        raise WorkflowError(
            f"Duration must be between {suggested.length_min} and {suggested.length_max} minutes"
        )
    return DurationPlan(
        suggested.length_min,
        suggested.length_max,
        target,
        suggested.target_wpm,
        suggested.discriminator,
        confirmed=True,
    )
