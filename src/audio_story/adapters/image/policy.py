"""Bounded local policy-rejection recovery for one image basename."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PolicyRecovery:
    basename: str
    attempt_index: int
    changed_risk_axes: tuple[str, ...]
    preserved_semantic_axes: tuple[str, ...]
    outcome: str


def recover_policy_prompt(
    basename: str, prompt: str, *, attempt_index: int, max_attempts: int = 2
) -> tuple[str, PolicyRecovery]:
    if attempt_index >= max_attempts:
        return prompt, PolicyRecovery(basename, attempt_index, (), (), "POLICY_BLOCKED")
    changed = "lighting" if attempt_index % 2 == 0 else "camera_distance"
    return f"{prompt}; safe {changed} variant", PolicyRecovery(
        basename,
        attempt_index,
        (changed,),
        ("identity", "age", "narrative_function", "location", "composition_purpose"),
        "RECOVERED",
    )
