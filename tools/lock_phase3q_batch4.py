from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from ai_story.model_operations import BenchmarkEvaluator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE3_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/story/phase3"
LOCK_ROOT = PHASE3_ROOT / "phase3q-locked-batch4"
SOURCE_RUNS = {
    "youth-thin-brief": "phase3o-batch4-pilot-v1",
    "adult-negative-dialogue": "phase3p-adult-negative-dialogue-v7",
    "serial-negative-state": "phase3p-serial-negative-state-v3",
    "youth-no-lesson": "phase3q-batch4a-v1",
    "adult-negative-invariant": "phase3q-batch4a-v1",
    "youth-negative-violence": "phase3q-batch4b-v1",
    "serial-negative-clue": "phase3q-batch4b-v1",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_expected_outcome(record: dict[str, object]) -> bool:
    expected = str(record["expected_decision"])
    accepted = bool(record["content_accepted"])
    advanced = bool(record["advancement_allowed"])
    blockers = int(record["blocker_count"])
    if expected == "PASS":
        return accepted and advanced and blockers == 0
    if expected == "REJECT":
        return not accepted and not advanced
    if expected == "REJECT_OR_REPAIR":
        return (accepted and advanced and blockers == 0) or (
            not accepted and not advanced
        )
    return False


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
        if int(record["p0_defect_count"]) or not valid_expected_outcome(record):
            raise RuntimeError(f"Cannot lock non-compliant Batch 4 case: {case_id}")
        entries.append({
            "case_id": case_id,
            "source_run_id": run_id,
            "expected_decision": record["expected_decision"],
            "outcome_compliant": record["outcome_compliant"],
            "advancement_allowed": record["advancement_allowed"],
            "locked_package": str(target.resolve()),
            "file_sha256": sha256(target),
            "story_sha256": record["story_sha256"],
            "failed_gate_ids": record["failed_gate_ids"],
        })
    manifest = {
        "schema_version": "1.0",
        "report_kind": "PHASE3Q_BATCH4_LOCK",
        "case_count": len(entries),
        "packages": entries,
    }
    path = LOCK_ROOT / "manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({
        "status": "LOCKED", "case_count": len(entries), "manifest": str(path)
    }))


if __name__ == "__main__":
    main()
