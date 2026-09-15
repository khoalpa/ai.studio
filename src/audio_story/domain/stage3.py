"""Typed Stage 3 package-intake contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class InheritedByteAuthority:
    """Immutable authority record for one member inherited by Stage 3."""

    path: str
    owner_stage: str
    sha256: str
    size_bytes: int
    mutation_status: str = "READ_ONLY"


@dataclass(frozen=True, slots=True)
class Stage2PackageInput:
    """Validated, immutable view of an authoritative Stage 2 package."""

    source_path: Path
    archive_sha256: str
    package_digest_sha256: str
    manifest_bytes: bytes
    members: Mapping[str, bytes]
    manifest: Mapping[str, Any]
    story: Mapping[str, Any]
    story_validation: Mapping[str, Any]
    visual_plan: Mapping[str, Any]
    visual_bible: Mapping[str, Any]
    inherited_authority: tuple[InheritedByteAuthority, ...]
    portrait_paths: tuple[str, ...]
    final_package_file_set: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Stage3PortraitPlan:
    """Frozen adaptation plan, pilot evidence and portrait execution queue."""

    adaptation_plan: tuple[Mapping[str, Any], ...]
    adaptation_plan_digest_sha256: str
    pilot_evidence: Mapping[str, Any]
    packaging_basenames: tuple[str, ...]
    execution_queue: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Stage3Invocation:
    """Exact Stage 3 request inspected before an image adapter can be called."""

    stage: str
    orientation: str
    target_basename: str
    generator_call_intent: str
    requested_output_count: int
    requested_width: int
    requested_height: int
    explicit_references: tuple[str, ...]
    payload: Mapping[str, Any]


class Stage3Error(RuntimeError):
    """Stable, locator-bearing Stage 3 error."""

    def __init__(self, code: str, message: str, locator: str) -> None:
        self.code = code
        self.locator = locator
        super().__init__(f"{code} at {locator}: {message}")
