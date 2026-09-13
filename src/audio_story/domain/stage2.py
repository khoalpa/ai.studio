"""Typed Stage 2 inputs and canonical ZONE constants."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ZONE_IMAGE_BASENAMES = (
    "introduction.png",
    "opening.png",
    "cover.png",
    "development.png",
    "climax.png",
    "falling.png",
    "ending.png",
    "greeting.png",
    "farewell.png",
    "outro.png",
)
ZONE_EXECUTION_QUEUE = ZONE_IMAGE_BASENAMES


@dataclass(frozen=True, slots=True)
class Stage2ZonePlan:
    """Frozen Stage 2 planning artifacts and execution order."""

    visual_plan_bytes: bytes
    visual_bible_bytes: bytes
    packaging_basenames: tuple[str, ...]
    execution_queue: tuple[str, ...]
    identity_pilot_basename: str
    calibration_basename: str


@dataclass(frozen=True, slots=True)
class Stage2Invocation:
    """Exact pre-call arguments checked independently of an image adapter."""

    stage: str
    orientation: str
    target_basename: str
    generator_call_intent: str
    requested_output_count: int
    requested_width: int
    requested_height: int
    explicit_references: tuple[str, ...]
    payload: Mapping[str, Any]


class Stage2Error(RuntimeError):
    """Stable, locator-bearing Stage 2 error."""

    def __init__(self, code: str, message: str, locator: str) -> None:
        self.code = code
        self.locator = locator
        super().__init__(f"{code} at {locator}: {message}")


@dataclass(frozen=True, slots=True)
class Stage1PackageInput:
    """Validated immutable view of an authoritative Stage 1 package."""

    source_path: Path
    package_digest_sha256: str
    manifest_bytes: bytes
    story_bytes: bytes
    story_validation_bytes: bytes
    character_assets: Mapping[str, bytes]
    series_anchor_bytes: bytes | None
    manifest: Mapping[str, Any]
    story: Mapping[str, Any]
    story_validation: Mapping[str, Any]
