"""Run independent local semantic assessments for a committed Stage 2 set."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

NAMES = (
    "introduction.png",
    "opening.png",
    "cover.png",
    "development.png",
    "climax.png",
    "falling.png",
    "ending.png",
    "greeting.png",
    "farewell.png",
    "outro.png",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    db = sqlite3.connect(args.workspace / "runtime.sqlite3")
    rows = db.execute(
        "SELECT t.basename,a.relative_path FROM asset_transactions t "
        "JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
        "JOIN artifacts a ON a.id=b.artifact_id "
        "WHERE t.orientation='LANDSCAPE'"
    ).fetchall()
    by_name = {str(name): str(path) for name, path in rows}
    if tuple(by_name.get(name) for name in NAMES).count(None) != 0:
        raise RuntimeError("all ten committed landscape assets are required")
    args.output.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        image = args.output / name
        image.write_bytes((args.workspace / by_name[name]).read_bytes())
        record = args.output / f"{Path(name).stem}.record.json"
        record.write_text(
            json.dumps(
                {
                    "basename": name,
                    "asset_role": "Stage 2 landscape",
                    "required": [
                        "landscape composition",
                        "no text or watermark",
                        "single coherent scene",
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [
                sys.executable,
                "scripts/run_m7_semantic_assessor.py",
                str(image),
                "--model",
                str(args.model),
                "--asset-record",
                str(record),
                "--output",
                str(args.output / f"{Path(name).stem}.assessment.json"),
            ],
            check=True,
        )
    print(json.dumps({"status": "PASS", "count": len(NAMES), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
