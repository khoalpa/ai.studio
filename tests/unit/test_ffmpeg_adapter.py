from __future__ import annotations

import subprocess
from pathlib import Path
from threading import Event

import pytest

from audio_story.adapters.video.ffmpeg import FFmpegAdapter, FFmpegConfig
from audio_story.domain.video_studio import VideoStudioError
from audio_story.validation.canonical import sha256_bytes


class _Process:
    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        *,
        returncode: int = 0,
        communicate_timeout: bool = False,
        wait_timeout: bool = False,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.communicate_timeout = communicate_timeout
        self.wait_timeout = wait_timeout
        self.terminated = False
        self.killed = False

    def communicate(self, timeout: float) -> tuple[bytes, bytes]:
        if self.communicate_timeout:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return self.stdout, self.stderr

    def poll(self) -> int | None:
        return None if self.communicate_timeout and not self.killed else self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> int:
        if self.wait_timeout and not self.killed:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def _config(tmp_path: Path, *, output_limit: int = 1024) -> FFmpegConfig:
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"ffmpeg-pinned")
    ffprobe.write_bytes(b"ffprobe-pinned")
    return FFmpegConfig(
        ffmpeg,
        ffprobe,
        sha256_bytes(ffmpeg.read_bytes()),
        sha256_bytes(ffprobe.read_bytes()),
        output_limit_bytes=output_limit,
    )


def test_ffmpeg_success_identity_render_and_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    processes = [
        _Process(),
        _Process(b'{"streams":[],"format":{"duration":"1.0"}}'),
    ]
    commands: list[list[str]] = []

    def popen(command: list[str], **kwargs: object) -> _Process:
        commands.append(command)
        assert kwargs["shell"] is False
        return processes.pop(0)

    monkeypatch.setattr("audio_story.adapters.video.ffmpeg.subprocess.Popen", popen)
    adapter = FFmpegAdapter(config)
    assert adapter.identity()["adapter_version"] == "M10-FFMPEG-1.0"
    adapter.render(["-version"], timeout_seconds=1)
    assert adapter.probe(tmp_path / "movie.mp4")["streams"] == []
    assert commands[0][0] == str(config.ffmpeg)
    assert commands[1][0] == str(config.ffprobe)


def test_ffmpeg_configuration_and_dependency_digest_fail_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.exe"
    with pytest.raises(VideoStudioError, match="M10C001_DEPENDENCY"):
        FFmpegConfig(missing, missing, "a" * 64, "b" * 64)
    config = _config(tmp_path)
    with pytest.raises(VideoStudioError, match="M10C002_CONFIG"):
        FFmpegConfig(
            config.ffmpeg,
            config.ffprobe,
            config.ffmpeg_sha256,
            config.ffprobe_sha256,
            output_limit_bytes=0,
        )
    config.ffmpeg.write_bytes(b"changed")
    with pytest.raises(VideoStudioError, match="M10C003_DEPENDENCY_DIGEST"):
        FFmpegAdapter(config).identity()


@pytest.mark.parametrize(
    ("process", "code"),
    [
        (_Process(stdout=b"too-large"), "M10C006_OUTPUT_LIMIT"),
        (_Process(stderr=b"bad", returncode=2), "M10C007_NON_ZERO_EXIT"),
    ],
)
def test_ffmpeg_process_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    process: _Process,
    code: str,
) -> None:
    config = _config(tmp_path, output_limit=4)
    monkeypatch.setattr(
        "audio_story.adapters.video.ffmpeg.subprocess.Popen", lambda *args, **kwargs: process
    )
    with pytest.raises(VideoStudioError, match=code):
        FFmpegAdapter(config).render([], timeout_seconds=1)


def test_ffmpeg_cancellation_timeout_and_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    cancelled = Event()
    cancelled.set()
    with pytest.raises(VideoStudioError, match="M10C004_CANCELLED"):
        FFmpegAdapter(config).render([], timeout_seconds=1, cancellation=cancelled)

    process = _Process(communicate_timeout=True, wait_timeout=True)
    monkeypatch.setattr(
        "audio_story.adapters.video.ffmpeg.subprocess.Popen", lambda *args, **kwargs: process
    )
    with pytest.raises(VideoStudioError, match="M10C005_TIMEOUT"):
        FFmpegAdapter(config).render([], timeout_seconds=0)
    assert process.terminated and process.killed

    def failed(*args: object, **kwargs: object) -> _Process:
        raise OSError("cannot execute")

    monkeypatch.setattr("audio_story.adapters.video.ffmpeg.subprocess.Popen", failed)
    with pytest.raises(VideoStudioError, match="M10C008_EXECUTION"):
        FFmpegAdapter(config).render([], timeout_seconds=1)


@pytest.mark.parametrize("payload", [b"not-json", b"[]"])
def test_ffprobe_rejects_malformed_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        "audio_story.adapters.video.ffmpeg.subprocess.Popen",
        lambda *args, **kwargs: _Process(stdout=payload),
    )
    with pytest.raises(VideoStudioError, match="M10D001_PROBE"):
        FFmpegAdapter(config).probe(tmp_path / "movie.mp4")
