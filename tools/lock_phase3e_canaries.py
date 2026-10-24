from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from ai_story.model_operations import BenchmarkEvaluator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORY_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/story"
PHASE3_ROOT = STORY_ROOT / "phase3"

GOLDEN_SOURCES = {
    "youth-no-lesson": PHASE3_ROOT / "phase3b-canary-v1/packages/youth-no-lesson.zip",
    "adult-memory-choice": PHASE3_ROOT / "phase3d-atomic-v4/packages/adult-memory-choice.zip",
    "youth-thin-brief": PHASE3_ROOT / "phase3d-atomic-v5/packages/youth-thin-brief.zip",
}
QUARANTINE_SOURCES = {
    "adult-five-characters": PHASE3_ROOT / "phase3d-atomic-v5/packages/adult-five-characters.zip",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lock or verify Phase 3E canary packages.")
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = PHASE3_ROOT / "phase3e"
    manifest_path = root / "golden-lock.json"
    if args.verify_only:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mismatches = [
            entry["case_id"]
            for entry in manifest["golden_packages"]
            if not Path(entry["locked_package"]).is_file()
            or sha256(Path(entry["locked_package"])) != entry["file_sha256"]
        ]
        status = "PASS" if not mismatches else "FAIL"
        print(json.dumps({"status": status, "mismatches": mismatches}))
        if mismatches:
            raise SystemExit(1)
        return

    evaluator = BenchmarkEvaluator()
    plan = evaluator.plan()
    cases = {str(case["id"]): case for case in plan["cases"]}
    golden_dir = root / "golden" / "packages"
    quarantine_dir = root / "quarantine" / "packages"
    golden_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    golden_entries = []
    for case_id, source in GOLDEN_SOURCES.items():
        target = golden_dir / f"{case_id}.zip"
        shutil.copy2(source, target)
        record = evaluator.record_from_package(cases[case_id], target, seed=int(cases[case_id]["seed"]))
        if int(record["blocker_count"]) != 0 or int(record["p0_defect_count"]) != 0:
            raise RuntimeError(f"Cannot lock non-clean canary: {case_id}")
        golden_entries.append({
            "case_id": case_id,
            "source_package": str(source.resolve()),
            "locked_package": str(target.resolve()),
            "file_sha256": sha256(target),
            "story_sha256": record["story_sha256"],
            "package_digest_sha256": record["package_digest_sha256"],
            "blocker_count": record["blocker_count"],
            "p0_defect_count": record["p0_defect_count"],
        })

    quarantine_entries = []
    for case_id, source in QUARANTINE_SOURCES.items():
        target = quarantine_dir / f"{case_id}.zip"
        shutil.copy2(source, target)
        record = evaluator.record_from_package(cases[case_id], target, seed=int(cases[case_id]["seed"]))
        quarantine_entries.append({
            "case_id": case_id,
            "source_package": str(source.resolve()),
            "quarantined_package": str(target.resolve()),
            "file_sha256": sha256(target),
            "blocker_count": record["blocker_count"],
            "p0_defect_count": record["p0_defect_count"],
            "failed_gate_ids": record["failed_gate_ids"],
        })

    manifest = {
        "schema_version": "1.0",
        "report_kind": "PHASE3E_CANARY_LOCK",
        "policy": {
            "golden_packages_are_immutable": True,
            "image_regeneration_allowed": False,
            "repair_strategy": "surgical_only",
        },
        "golden_packages": golden_entries,
        "quarantine_packages": quarantine_entries,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({
        "status": "LOCKED",
        "golden_count": len(golden_entries),
        "quarantine_count": len(quarantine_entries),
        "manifest": str(manifest_path.resolve()),
    }))


if __name__ == "__main__":
    main()
