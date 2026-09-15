"""Explicit M10 production runner for the accepted M9 package."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from audio_story.adapters.video import FFmpegAdapter, FFmpegConfig
from audio_story.domain.video_studio import VideoRenderRequest
from audio_story.validation.canonical import sha256_bytes
from audio_story.validation.video_studio import load_stage4_video_input
from audio_story.workflows.video_studio import derive_srt_bytes, render_video


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage4", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--srt", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--mode", choices=("AUTO", "SCENE", "ZONE", "FIXED"), default="AUTO")
    parser.add_argument("--orientation", choices=("LANDSCAPE", "PORTRAIT"), default="LANDSCAPE")
    arguments = parser.parse_args()
    ffmpeg = _executable("ffmpeg")
    ffprobe = _executable("ffprobe")
    source = load_stage4_video_input(arguments.stage4)
    srt = arguments.srt or arguments.output.with_suffix(".srt")
    if arguments.srt is None:
        srt.parent.mkdir(parents=True, exist_ok=True)
        srt.write_bytes(derive_srt_bytes(source))
    adapter = FFmpegAdapter(
        FFmpegConfig(
            ffmpeg,
            ffprobe,
            sha256_bytes(ffmpeg.read_bytes()),
            sha256_bytes(ffprobe.read_bytes()),
        )
    )
    result = render_video(
        source,
        srt,
        arguments.output,
        adapter,
        VideoRenderRequest(
            slideshow_timeline_mode=arguments.mode,
            orientation=arguments.orientation,
        ),
        audio_path=arguments.audio,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(result.output_path),
                "sha256": result.output_sha256,
                "duration_seconds": result.duration_seconds,
                "resolved_mode": result.resolved_mode,
                "quality_report": str(result.quality_report_path),
                "result_manifest": str(result.result_manifest_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _executable(name: str) -> Path:
    resolved = shutil.which(name)
    if resolved is None:
        raise RuntimeError(f"{name} is not installed locally")
    return Path(resolved).resolve(strict=True)


if __name__ == "__main__":
    raise SystemExit(main())
