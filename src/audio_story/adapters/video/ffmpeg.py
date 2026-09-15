"""Pinned, local-only FFmpeg/FFprobe adapter for M10."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

from audio_story.domain.video_studio import VideoStudioError
from audio_story.validation.canonical import sha256_bytes


@dataclass(frozen=True, slots=True)
class FFmpegConfig:
    ffmpeg: Path
    ffprobe: Path
    ffmpeg_sha256: str
    ffprobe_sha256: str
    adapter_version: str = "M10-FFMPEG-1.0"
    cleanup_timeout_seconds: float = 3.0
    output_limit_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if not self.ffmpeg.is_file() or not self.ffprobe.is_file():
            raise VideoStudioError("M10C001_DEPENDENCY", "FFmpeg/FFprobe executable missing")
        if self.cleanup_timeout_seconds <= 0 or self.output_limit_bytes <= 0:
            raise VideoStudioError("M10C002_CONFIG", "invalid adapter limits")


class FFmpegAdapter:
    def __init__(self, config: FFmpegConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[bytes] | None = None

    def identity(self) -> Mapping[str, str]:
        self._verify_dependencies()
        return {
            "adapter_version": self.config.adapter_version,
            "ffmpeg_sha256": self.config.ffmpeg_sha256,
            "ffprobe_sha256": self.config.ffprobe_sha256,
        }

    def render(
        self, arguments: Sequence[str], *, timeout_seconds: float, cancellation: Event | None = None
    ) -> None:
        self._verify_dependencies()
        self._run(
            [str(self.config.ffmpeg), "-nostdin", "-hide_banner", *arguments],
            timeout_seconds,
            cancellation,
        )

    def probe(self, output: Path, *, timeout_seconds: float = 30.0) -> Mapping[str, Any]:
        self._verify_dependencies()
        stdout = self._run(
            [
                str(self.config.ffprobe),
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(output),
            ],
            timeout_seconds,
            None,
        )
        try:
            value = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VideoStudioError("M10D001_PROBE", "FFprobe returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise VideoStudioError("M10D001_PROBE", "FFprobe root must be an object")
        return value

    def _verify_dependencies(self) -> None:
        if (
            _digest(self.config.ffmpeg) != self.config.ffmpeg_sha256
            or _digest(self.config.ffprobe) != self.config.ffprobe_sha256
        ):
            raise VideoStudioError("M10C003_DEPENDENCY_DIGEST", "FFmpeg dependency changed")

    def _run(
        self, command: Sequence[str], timeout_seconds: float, cancellation: Event | None
    ) -> bytes:
        token = cancellation or Event()
        if token.is_set():
            raise VideoStudioError("M10C004_CANCELLED", "render cancelled")
        try:
            self._process = subprocess.Popen(
                list(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False
            )
            deadline = time.monotonic() + timeout_seconds
            while True:
                if token.is_set():
                    self._cleanup()
                    raise VideoStudioError("M10C004_CANCELLED", "render cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._cleanup()
                    raise VideoStudioError("M10C005_TIMEOUT", "local FFmpeg timed out")
                try:
                    stdout, stderr = self._process.communicate(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if (
                len(stdout) > self.config.output_limit_bytes
                or len(stderr) > self.config.output_limit_bytes
            ):
                raise VideoStudioError("M10C006_OUTPUT_LIMIT", "process output exceeded limit")
            if self._process.returncode:
                detail = stderr[-2048:].decode("utf-8", errors="replace")
                raise VideoStudioError("M10C007_NON_ZERO_EXIT", detail or "FFmpeg failed")
            return stdout
        except VideoStudioError:
            raise
        except OSError as exc:
            raise VideoStudioError("M10C008_EXECUTION", "local process failed") from exc
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        process = self._process
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.config.cleanup_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.config.cleanup_timeout_seconds)
        finally:
            self._process = None


def _digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())
