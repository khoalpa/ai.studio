from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_story.release import build_release_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--external-inventory", type=Path)
    arguments = parser.parse_args()
    inventory = None
    if arguments.external_inventory:
        value = json.loads(arguments.external_inventory.read_text(encoding="utf-8"))
        inventory = value["components"]
    manifest = build_release_bundle(
        arguments.wheelhouse, arguments.output, external_inventory=inventory
    )
    print(json.dumps({"status": "PASS", "files": len(manifest["files"])}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
