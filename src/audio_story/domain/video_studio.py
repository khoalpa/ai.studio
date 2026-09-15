"""Typed contracts for the M10 offline Video Studio."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class VideoStudioError(RuntimeError):
    def __init__(self, code: str, message: str, locator: str = "video-studio") -> None:
        self.code = code
        self.locator = locator
        super().__init__(f"{code} at {locator}: {message}")


@dataclass(frozen=True, slots=True)
class Stage4VideoInput:
    source_path: Path
    archive_sha256: str
    package_digest_sha256: str
    manifest: Mapping[str, Any]
    members: Mapping[str, bytes]
    story: Mapping[str, Any]
    visual_plan: Mapping[str, Any]
    video_prompts: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SlideshowSegment:
    image_member: str
    start_seconds: float
    end_seconds: float
    source_kind: str
    source_id: str

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True, slots=True)
class VideoRenderRequest:
    slideshow_timeline_mode: str = "AUTO"
    orientation: str = "LANDSCAPE"
    frame_rate: int = 30
    video_codec: str = "libx264"
    pixel_format: str = "yuv420p"
    audio_codec: str = "aac"
    timeout_seconds: float = 3600.0


@dataclass(frozen=True, slots=True)
class RenderResult:
    output_path: Path
    output_sha256: str
    output_size_bytes: int
    request_digest_sha256: str
    quality_report_path: Path
    result_manifest_path: Path
    duration_seconds: float
    resolved_mode: str
