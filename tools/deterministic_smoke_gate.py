from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from ai_story.determinism import package_fingerprint
from ai_story.smoke import run_deterministic_smoke


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Stage 1-4 twice and fail if deterministic output changes."
    )
    parser.add_argument("--root", type=Path, default=Path("artifacts/deterministic-smoke"))
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--keep-runs", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    evidence_path = (args.evidence or root / "evidence.json").resolve()

    runs = []
    fingerprints = []
    for label in ("a", "b"):
        result = run_deterministic_smoke(root / label)
        fingerprint = package_fingerprint(Path(result["stage4_package"]))
        runs.append(
            {
                "label": label,
                "status": result["status"],
                "completed_stages": result["completed_stages"],
                "semantic_package_sha256": fingerprint["sha256"],
            }
        )
        fingerprints.append(fingerprint)

    changed_entries = sorted(
        name
        for name in set(fingerprints[0]["entries"]) | set(fingerprints[1]["entries"])
        if fingerprints[0]["entries"].get(name) != fingerprints[1]["entries"].get(name)
    )
    passed = not changed_entries and fingerprints[0]["sha256"] == fingerprints[1]["sha256"]
    evidence = {
        "gate": "deterministic-smoke",
        "status": "PASS" if passed else "FAIL",
        "provider_mode": "deterministic",
        "runs": runs,
        "changed_entries": changed_entries,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))

    if not args.keep_runs:
        shutil.rmtree(root / "a", ignore_errors=True)
        shutil.rmtree(root / "b", ignore_errors=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
