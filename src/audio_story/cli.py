"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from audio_story.adapters.llm.mock import DeterministicMockAdapter
from audio_story.doctor import report_json
from audio_story.domain.stage1 import Stage1Request
from audio_story.workflows import Stage1Service, WorkflowKernel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="audio-story")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="emit a machine-readable local environment inventory")
    stage1 = subparsers.add_parser("stage1-mock", help="run the explicit deterministic M5 path")
    stage1.add_argument("--workspace", type=Path, required=True)
    stage1.add_argument(
        "--canonical",
        type=Path,
        default=Path("canonical/ChatGPT_prompt_v3.16.13.txt"),
    )
    stage1.add_argument("--profile", required=True)
    stage1.add_argument("--duration", type=int, required=True)
    stage1.add_argument("--language", choices=("vi", "en"), default="vi")
    stage1.add_argument("--seed", type=int, default=0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "doctor":
        print(report_json())
        return 0
    if arguments.command == "stage1-mock":
        kernel = WorkflowKernel(arguments.workspace)
        try:
            result = Stage1Service(kernel, DeterministicMockAdapter(), arguments.canonical).start(
                Stage1Request(
                    arguments.profile,
                    language=arguments.language,
                    duration_minutes=arguments.duration,
                    duration_confirmed=True,
                    seed=arguments.seed,
                    test_mode=True,
                )
            )
            print(
                json.dumps(
                    {
                        "status": result.status,
                        "workflow_id": result.workflow_id,
                        "stage_id": result.stage_id,
                        "package_path": str(result.package_path) if result.package_path else None,
                        "package_digest": result.package_digest,
                        "reason_code": result.reason_code,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0 if result.status == "PASS" else 1
        finally:
            kernel.close()
    return 2  # pragma: no cover - argparse rejects unknown commands


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
