from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from ai_story.model_operations import BenchmarkEvaluator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE3_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/story/phase3"
SOURCE_ROOT = PHASE3_ROOT / "phase3f-final-pilot-v1"
LOCK_ROOT = PHASE3_ROOT / "phase3f-locked-pilot"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    evaluator = BenchmarkEvaluator()
    cases = {str(case["id"]): case for case in evaluator.plan()["cases"]}
    records = evaluator.load_records(SOURCE_ROOT / "records")
    packages = LOCK_ROOT / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    entries = []
    for source_record in records:
        case_id = str(source_record["case_id"])
        source = SOURCE_ROOT / "packages" / f"{case_id}.zip"
        target = packages / source.name
        shutil.copy2(source, target)
        record = evaluator.record_from_package(
            cases[case_id], target, seed=int(cases[case_id]["seed"])
        )
        expected_pass = record["expected_decision"] == "PASS"
        accepted = (
            int(record["blocker_count"]) == 0
            if expected_pass else bool(record["outcome_compliant"])
        )
        if not accepted or int(record["p0_defect_count"]) != 0:
            raise RuntimeError(f"Cannot lock unsuccessful Phase 3F case: {case_id}")
        entries.append({
            "case_id": case_id,
            "expected_decision": record["expected_decision"],
            "outcome_compliant": record["outcome_compliant"],
            "failed_gate_ids": record["failed_gate_ids"],
            "file_sha256": sha256(target),
            "story_sha256": record["story_sha256"],
            "locked_package": str(target.resolve()),
        })
    manifest = {
        "schema_version": "1.0",
        "report_kind": "PHASE3F_PILOT_LOCK",
        "case_count": len(entries),
        "policy": {
            "immutable": True,
            "expected_rejection_is_success": True,
            "image_regeneration_allowed": False,
        },
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
