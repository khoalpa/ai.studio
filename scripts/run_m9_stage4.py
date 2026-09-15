"""Build the offline Stage 4 canonical video-prompt package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_story.validation.stage4 import load_stage3_package
from audio_story.workflows.stage4_package import build_stage4_package, write_stage4_package
from audio_story.workflows.stage4_planning import build_video_prompts, resolve_stage4_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument(
        "--coverage", choices=("FULL_STORY", "NARRATIVE_ONLY", "KEY_SCENES"), default="FULL_STORY"
    )
    parser.add_argument(
        "--aspect-ratio", choices=("LANDSCAPE_16_9", "PORTRAIT_9_16"), default="LANDSCAPE_16_9"
    )
    parser.add_argument(
        "--audio-mode",
        choices=("NATIVE_DIALOGUE", "AMBIENCE_ONLY", "SILENT"),
        default="NATIVE_DIALOGUE",
    )
    parser.add_argument(
        "--continuity",
        choices=("CHAINED_LAST_FRAME", "FIRST_LAST_FRAME", "REFERENCE_IMAGES", "PROMPT_ONLY"),
        default="CHAINED_LAST_FRAME",
    )
    args = parser.parse_args()
    source = load_stage3_package(args.source, expected_archive_sha256=args.expected_sha256)
    config = resolve_stage4_config(
        {
            "video_coverage_mode": args.coverage,
            "video_aspect_ratio": args.aspect_ratio,
            "video_audio_mode": args.audio_mode,
            "video_continuity_mode": args.continuity,
        }
    )
    root, video_bytes = build_video_prompts(source, config)
    package = build_stage4_package(source, video_bytes)
    write_stage4_package(package, args.output)
    print(
        json.dumps(
            {
                "story_zip": str(args.output.resolve()),
                "archive_sha256": package.archive_sha256,
                "package_digest_sha256": package.package_digest_sha256,
                "clip_count": root["project"]["clip_count"],
                "planned_video_duration_seconds": root["project"]["planned_video_duration_seconds"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
