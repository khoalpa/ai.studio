from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE3_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/story/phase3"
LOCK_MANIFESTS = (
    PHASE3_ROOT / "phase3f-locked-pilot/manifest.json",
    PHASE3_ROOT / "phase3g-locked-batch1/manifest.json",
    PHASE3_ROOT / "phase3i-locked-batch2/manifest.json",
    PHASE3_ROOT / "phase3n-locked-batch3/manifest.json",
    PHASE3_ROOT / "phase3q-locked-batch4/manifest.json",
    PHASE3_ROOT / "phase3r-locked-recovery-baseline/manifest.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate one controlled Phase 3G batch.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--overlay-run-id", action="append", default=[],
        help="Overlay newer surgical records onto the original batch observations.",
    )
    args = parser.parse_args()
    result_path = PHASE3_ROOT / args.run_id / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    controlled = result["controlled_recovery"]
    observations = [dict(item) for item in controlled["observations"]]
    records = {record["case_id"]: record for record in result["records"]}
    for overlay_run_id in args.overlay_run_id:
        overlay = json.loads(
            (PHASE3_ROOT / overlay_run_id / "result.json").read_text(encoding="utf-8")
        )
        overlay_observations = {
            item["case_id"]: dict(item)
            for item in overlay["controlled_recovery"]["observations"]
        }
        overlay_records = {record["case_id"]: record for record in overlay["records"]}
        records.update(overlay_records)
        observed_ids = {item["case_id"] for item in observations}
        observations.extend(
            item for case_id, item in overlay_observations.items()
            if case_id not in observed_ids
        )
        for observation in observations:
            case_id = observation["case_id"]
            if case_id not in overlay_records:
                continue
            final_count = int(overlay_records[case_id]["blocker_count"])
            observation["blockers_after"] = final_count
            observation["blockers_removed"] = (
                int(observation["blockers_before"]) - final_count
            )
            observation["improved"] = final_count < int(observation["blockers_before"])
            observation["p0_defect_count"] = int(
                overlay_records[case_id]["p0_defect_count"]
            )

    golden_mismatches = []
    for manifest_path in LOCK_MANIFESTS:
        lock = json.loads(manifest_path.read_text(encoding="utf-8"))
        golden_mismatches.extend(
            f"{manifest_path.parent.name}:{entry['case_id']}"
            for entry in lock["packages"]
            if not Path(entry["locked_package"]).is_file()
            or sha256(Path(entry["locked_package"])) != entry["file_sha256"]
        )
    before = sum(int(item["blockers_before"]) for item in observations)
    after = sum(int(item["blockers_after"]) for item in observations)
    reduction = (before - after) / before if before else 0.0
    p0 = sum(int(item["p0_defect_count"]) for item in observations)
    non_regressed = sum(
        int(item["blockers_after"]) <= int(item["blockers_before"])
        for item in observations
    )
    successful = sum(
        bool(item["improved"])
        or int(item["blockers_before"]) == int(item["blockers_after"]) == 0
        or (
            records[item["case_id"]].get("expected_decision") != "PASS"
            and bool(records[item["case_id"]].get("outcome_compliant"))
        )
        for item in observations
    )
    criteria = {
        "all_requested_cases_executed": (
            len(observations) == len(records)
            and len({item["case_id"] for item in observations}) == len(observations)
        ),
        "zero_p0": p0 == 0,
        "no_case_regressed": non_regressed == len(observations),
        "at_least_80_percent_improved_or_stayed_clean": (
            successful / max(1, len(observations)) >= 0.8
        ),
        "effective_blocker_reduction_at_least_60_percent": reduction >= 0.6,
        "locked_regression_sets_unchanged": not golden_mismatches,
    }
    expand = all(criteria.values())
    report = {
        "schema_version": "1.0",
        "report_kind": "PHASE3G_BATCH_DECISION",
        "run_id": args.run_id,
        "overlay_run_ids": args.overlay_run_id,
        "status": "PASS" if expand else "HOLD",
        "open_next_batch": expand,
        "metrics": {
            "case_count": len(observations),
            "successful_case_count": successful,
            "non_regressed_case_count": non_regressed,
            "blockers_before": before,
            "blockers_after": after,
            "blocker_reduction_ratio": round(reduction, 4),
            "p0_defect_count": p0,
        },
        "criteria": criteria,
        "stop_reason": controlled["stop_reason"],
        "golden_mismatches": golden_mismatches,
        "remaining_blockers": {
            case_id: record["failed_gate_ids"]
            for case_id, record in records.items()
            if int(record["blocker_count"]) > 0
            and not (
                record.get("expected_decision") != "PASS"
                and bool(record.get("outcome_compliant"))
            )
        },
    }
    overlay_suffix = (
        "-with-" + "-".join(args.overlay_run_id) if args.overlay_run_id else ""
    )
    output = PHASE3_ROOT / "phase3g" / f"{args.run_id}{overlay_suffix}-decision.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({
        "status": report["status"],
        "open_next_batch": expand,
        "metrics": report["metrics"],
        "output": str(output.resolve()),
    }))


if __name__ == "__main__":
    main()
