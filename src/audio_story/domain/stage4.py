"""Typed contracts for the M9 canonical video-prompt package."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Stage4PackageInput:
    source_path: Path
    archive_sha256: str
    package_digest_sha256: str
    manifest_bytes: bytes
    members: Mapping[str, bytes]
    manifest: Mapping[str, Any]
    story: Mapping[str, Any]
    story_validation: Mapping[str, Any]
    package_quality_report: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Stage4Config:
    aspect_ratio: str = "LANDSCAPE_16_9"
    coverage_mode: str = "FULL_STORY"
    clip_duration_seconds: int = 8
    audio_mode: str = "NATIVE_DIALOGUE"
    continuity_mode: str = "CHAINED_LAST_FRAME"
    prompt_language: str = "EN"
    generator_family: str = "VEO"
    preferred_model: str = "VEO_3_1"


@dataclass(frozen=True, slots=True)
class TimelineSpan:
    item_index: int
    start_word_offset: int
    end_word_offset: int
    start_time_seconds: Decimal
    end_time_seconds: Decimal
    usable_span_seconds: Decimal
    pause_seconds: Decimal
    text: str
    speaker_id: str
    zone: str
    environment: str
    utterance_group_id: str
    segment_index: int
    segment_count: int
    segmentation_mode: str


class Stage4Error(RuntimeError):
    def __init__(self, code: str, message: str, locator: str) -> None:
        self.code = code
        self.locator = locator
        super().__init__(f"{code} at {locator}: {message}")
