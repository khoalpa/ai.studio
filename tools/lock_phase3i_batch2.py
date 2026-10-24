from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from ai_story.model_operations import BenchmarkEvaluator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE3_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/story/phase3"
LOCK_ROOT = PHASE3_ROOT / "phase3i-locked-batch2"
SOURCE_RUNS = {
    "youth-promise-rain": "phase3j-quality-v2",
    "youth-lost-bird-rain": "phase3j-quality-v1",
    "adult-thin-brief": "phase3k-batch2-resume-v1",
    "adult-memory-choice": "phase3k-batch2-resume-v1",
    "serial-river-ferry": "phase3k-batch2-resume-v1",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    evaluator = BenchmarkEvaluator()
    cases = {str(case["id"]): case for case in evaluator.plan()["cases"]}
    packages = LOCK_ROOT / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    entries = []
    for case_id, run_id in SOURCE_RUNS.items():
        source = PHASE3_ROOT / run_id / "packages" / f"{case_id}.zip"
        target = packages / source.name
        shutil.copy2(source, target)
        record = evaluator.record_from_package(
            cases[case_id], target, seed=int(cases[case_id]["seed"])
        )
        if int(record["blocker_count"]) or int(record["p0_defect_count"]):
            raise RuntimeError(f"Cannot lock blocked Batch 2 case: {case_id}")
        entries.append({
            "case_id": case_id,
            "source_run_id": run_id,
            "locked_package": str(target.resolve()),
            "file_sha256": sha256(target),
            "story_sha256": record["story_sha256"],
            "failed_gate_ids": record["failed_gate_ids"],
        })
    manifest = {
        "schema_version": "1.0",
        "report_kind": "PHASE3I_BATCH2_LOCK",
        "case_count": len(entries),
        "packages": entries,
    }
    path = LOCK_ROOT / "manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({"status": "LOCKED", "case_count": len(entries), "manifest": str(path)}))


if __name__ == "__main__":
    main()
