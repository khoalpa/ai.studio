"""Command-line entry point."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from audio_story.doctor import report_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="audio-story")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="emit a machine-readable local environment inventory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "doctor":
        print(report_json())
        return 0
    return 2  # pragma: no cover - argparse rejects unknown commands


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
