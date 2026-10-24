from __future__ import annotations

import json
from pathlib import Path

from ai_story.model_operations import BenchmarkEvaluator
from ai_story.regression_triage import build_triage, write_phase1_artifacts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/story"
OUTPUT_ROOT = BASELINE_ROOT / "phase1"


def main() -> None:
    evaluator = BenchmarkEvaluator()
    baseline_path = BASELINE_ROOT / "baseline.json"
    if not baseline_path.is_file():
        raise RuntimeError(f"Frozen baseline is missing: {baseline_path}")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    records = evaluator.load_records(BASELINE_ROOT / "records")
    for record in records:
        evaluator.validate_canonical_record(record)
    triage, target = build_triage(evaluator.plan(), records, baseline)
    write_phase1_artifacts(OUTPUT_ROOT, triage, target)
    print(
        json.dumps(
            {
                "status": "COMPLETE",
                "triage": str(OUTPUT_ROOT / "blocker-triage.json"),
                "regression_target": str(OUTPUT_ROOT / "regression-target.json"),
                "case_count": target["case_count"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
