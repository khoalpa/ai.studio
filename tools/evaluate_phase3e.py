from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE3_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/story/phase3"
PHASE3E_ROOT = PHASE3_ROOT / "phase3e"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a Phase 3E controlled pilot.")
    parser.add_argument("--pilot-run-id", default="phase3e-controlled-pilot-v1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    lock = load(PHASE3E_ROOT / "golden-lock.json")
    pilot = load(PHASE3_ROOT / args.pilot_run_id / "result.json")
    quarantine = load(PHASE3_ROOT / "phase3e-quarantine-v1/result.json")
    controlled = pilot["controlled_recovery"]
    observations = controlled["observations"]
    records_by_id = {record["case_id"]: record for record in pilot["records"]}

    golden_mismatches = [
        entry["case_id"]
        for entry in lock["golden_packages"]
        if not Path(entry["locked_package"]).is_file()
        or sha256(Path(entry["locked_package"])) != entry["file_sha256"]
    ]
    before = sum(int(item["blockers_before"]) for item in observations)
    after = sum(int(item["blockers_after"]) for item in observations)
    improved = sum(bool(item["improved"]) for item in observations)
    non_regressed = sum(
        int(item["blockers_after"]) <= int(item["blockers_before"])
        for item in observations
    )
    successful_cases = sum(
        bool(item["improved"])
        or (
            int(item["blockers_before"]) == 0
            and int(item["blockers_after"]) == 0
        )
        or (
            records_by_id[item["case_id"]].get("expected_decision") != "PASS"
            and bool(records_by_id[item["case_id"]].get("outcome_compliant"))
        )
        for item in observations
    )
    p0 = sum(int(item["p0_defect_count"]) for item in observations)
    reduction = (before - after) / before if before else 0.0
    forbidden_regression_codes = {
        "FILLER_PADDING", "PREMATURE_PAYOFF", "STALE_QUALITY_FINDING",
    }
    defect_codes = {
        str(code)
        for record in pilot["records"]
        for code in record.get("defect_codes", [])
    }
    criteria = {
        "zero_p0": p0 == 0,
        "at_least_four_of_five_improved_or_stayed_clean": successful_cases >= 4,
        "golden_packages_unchanged": not golden_mismatches,
        "blocker_reduction_at_least_60_percent": reduction >= 0.60,
        "no_filler_payoff_or_stale_quality_regression": not (
            defect_codes & forbidden_regression_codes
        ),
    }
    expand = all(criteria.values())
    report = {
        "schema_version": "1.0",
        "report_kind": "PHASE3E_CONTROLLED_RECOVERY_DECISION",
        "status": "PASS" if expand else "HOLD",
        "expand_to_remaining_cases": expand,
        "pilot": {
            "run_id": args.pilot_run_id,
            "requested_case_count": controlled["requested_case_count"],
            "executed_case_count": controlled["executed_case_count"],
            "stop_reason": controlled["stop_reason"],
            "improved_case_count": improved,
            "non_regressed_case_count": non_regressed,
            "successful_case_count": successful_cases,
            "blockers_before": before,
            "blockers_after": after,
            "blocker_reduction_ratio": round(reduction, 4),
            "p0_defect_count": p0,
            "observations": observations,
        },
        "criteria": criteria,
        "golden_mismatches": golden_mismatches,
        "quarantine": quarantine["records"],
        "remaining_blockers": {
            record["case_id"]: record["failed_gate_ids"]
            for record in pilot["records"]
            if int(record["blocker_count"]) > 0
            and not (
                record.get("expected_decision") != "PASS"
                and bool(record.get("outcome_compliant"))
            )
        },
    }
    suffix = args.pilot_run_id.removeprefix("phase3e-controlled-pilot-")
    output = PHASE3E_ROOT / f"controlled-recovery-decision-{suffix}.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({
        "status": report["status"],
        "expand_to_remaining_cases": expand,
        "improved_case_count": improved,
        "blockers_before": before,
        "blockers_after": after,
        "output": str(output.resolve()),
    }))


if __name__ == "__main__":
    main()
