from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

PRIORITY_GATES = (
    "STORY_QUALITY_GATE",
    "WORD_DURATION_GATE",
    "SEMANTIC_REPETITION_GATE",
    "ZONE_BUDGET_GATE",
    "NARRATIVE_VOICE_GATE",
    "SENTENCE_COMPLETENESS_GATE",
    "SCENE_STATE_CONTINUITY_GATE",
    "AGE_PROFILE_GATE",
    "LANGUAGE_INTEGRITY_GATE",
)


def classify_record(record: dict[str, Any]) -> str:
    expected = str(record.get("expected_decision", "PASS"))
    compliant = bool(record.get("outcome_compliant"))
    accepted = bool(record.get("content_accepted"))
    if expected == "PASS":
        return "CORRECT_PASS" if compliant else "FALSE_BLOCKER"
    if compliant:
        return "CORRECT_REJECTION_OR_REPAIR"
    return "UNEXPECTED_ACCEPTANCE" if accepted else "OUTCOME_MISMATCH"


def build_triage(
    plan: dict[str, Any],
    records: list[dict[str, Any]],
    baseline: dict[str, Any],
    *,
    maximum_regression_cases: int = 10,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cases = {str(case["id"]): case for case in plan["cases"]}
    by_id = {str(record["case_id"]): record for record in records}
    missing = sorted(set(cases) - set(by_id))
    extra = sorted(set(by_id) - set(cases))
    if missing or extra:
        raise ValueError(f"Record set differs from plan: missing={missing}, extra={extra}")

    rows: list[dict[str, Any]] = []
    gate_counts: Counter[str] = Counter()
    false_blocker_gate_counts: Counter[str] = Counter()
    for case_id in sorted(cases):
        case = cases[case_id]
        record = by_id[case_id]
        classification = classify_record(record)
        gates = sorted(str(value) for value in record.get("failed_gate_ids", []))
        gate_counts.update(gates)
        if classification == "FALSE_BLOCKER":
            false_blocker_gate_counts.update(gates)
        rows.append(
            {
                "case_id": case_id,
                "profile": case["profile"],
                "scenario": case.get("labels", {}).get("scenario"),
                "expected_decision": record.get("expected_decision"),
                "classification": classification,
                "outcome_compliant": bool(record.get("outcome_compliant")),
                "content_accepted": bool(record.get("content_accepted")),
                "advancement_allowed": bool(record.get("advancement_allowed")),
                "blocker_count": int(record.get("blocker_count", 0)),
                "failed_gate_ids": gates,
                "editorial_basis": record.get("editorial_basis"),
                "preflight_story_quality_score": record.get(
                    "preflight_story_quality_score"
                ),
                "duration_seconds": record.get("duration_seconds"),
            }
        )

    selected: dict[str, set[str]] = {}
    false_blockers = [row for row in rows if row["classification"] == "FALSE_BLOCKER"]
    for gate in PRIORITY_GATES:
        candidates = [row for row in false_blockers if gate in row["failed_gate_ids"]]
        if not candidates:
            continue
        chosen = min(
            candidates,
            key=lambda row: (
                row["blocker_count"],
                float(row.get("duration_seconds") or 0),
                row["case_id"],
            ),
        )
        selected.setdefault(chosen["case_id"], set()).add(f"covers:{gate}")
        if len(selected) >= maximum_regression_cases:
            break

    control_order = (
        ("CORRECT_PASS", "SERIAL_DETECTIVE", "control:passing-long-form"),
        ("CORRECT_REJECTION_OR_REPAIR", None, "control:negative-rejection"),
    )
    for classification, profile, reason in control_order:
        if len(selected) >= maximum_regression_cases:
            break
        candidates = [
            row
            for row in rows
            if row["classification"] == classification
            and (profile is None or row["profile"] == profile)
            and row["case_id"] not in selected
        ]
        if candidates:
            chosen = min(candidates, key=lambda row: row["case_id"])
            selected.setdefault(chosen["case_id"], set()).add(reason)
    if (
        len(selected) < maximum_regression_cases
        and not any(
            row["classification"] == "CORRECT_PASS" and row["case_id"] in selected
            for row in rows
        )
    ):
        candidates = [
            row
            for row in rows
            if row["classification"] == "CORRECT_PASS"
            and row["case_id"] not in selected
        ]
        if candidates:
            chosen = min(candidates, key=lambda row: row["case_id"])
            selected.setdefault(chosen["case_id"], set()).add("control:passing")

    regression_cases = []
    for case_id, reasons in selected.items():
        case = cases[case_id]
        row = next(item for item in rows if item["case_id"] == case_id)
        regression_cases.append(
            {
                "case_id": case_id,
                "profile": case["profile"],
                "expected_decision": row["expected_decision"],
                "baseline_classification": row["classification"],
                "baseline_failed_gate_ids": row["failed_gate_ids"],
                "selection_reasons": sorted(reasons),
                "case": case,
            }
        )
    regression_cases.sort(key=lambda item: item["case_id"])

    baseline_digest = str(baseline.get("report_digest_sha256", ""))
    counts = Counter(row["classification"] for row in rows)
    triage = {
        "schema_version": "1.0",
        "report_kind": "STORY_BLOCKER_TRIAGE",
        "suite_id": plan["suite_id"],
        "baseline_report_digest_sha256": baseline_digest,
        "baseline_case_set_digest": baseline.get("case_set_digest"),
        "summary": {
            "case_count": len(rows),
            "classification_counts": dict(sorted(counts.items())),
            "outcome_mismatch_count": sum(not row["outcome_compliant"] for row in rows),
            "false_blocker_count": counts["FALSE_BLOCKER"],
            "editorial_assessed_count": sum(
                row["editorial_basis"] in {
                    "MODEL_CRITIC_CORROBORATED", "MODEL_CRITIC_ASSESSED", "HUMAN_REVIEWED",
                }
                for row in rows
            ),
            "gate_counts": dict(gate_counts.most_common()),
            "false_blocker_gate_counts": dict(false_blocker_gate_counts.most_common()),
        },
        "cases": rows,
        "report_digest_sha256": None,
    }
    triage["report_digest_sha256"] = _digest(triage, "report_digest_sha256")

    target = {
        "schema_version": "1.0",
        "report_kind": "TARGETED_REGRESSION_SET",
        "suite_id": plan["suite_id"],
        "source_baseline_report_digest_sha256": baseline_digest,
        "source_triage_report_digest_sha256": triage["report_digest_sha256"],
        "maximum_case_count": maximum_regression_cases,
        "case_count": len(regression_cases),
        "target_gates": [
            gate for gate in PRIORITY_GATES if false_blocker_gate_counts.get(gate)
        ],
        "cases": regression_cases,
        "success_criteria": {
            "completion_rate": 1.0,
            "expected_outcome_accuracy_minimum": 0.75,
            "positive_case_advancement_rate_minimum": 0.8,
            "editorial_assessment_rate": 1.0,
            "forbidden_outcome_rate_maximum": baseline.get("metrics", {}).get(
                "forbidden_outcome_rate", 0
            ),
        },
        "report_digest_sha256": None,
    }
    target["report_digest_sha256"] = _digest(target, "report_digest_sha256")
    return triage, target


def write_phase1_artifacts(
    output_dir: Path, triage: dict[str, Any], target: dict[str, Any]
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "blocker-triage.json", triage)
    _write_json(output_dir / "regression-target.json", target)
    (output_dir / "blocker-triage.md").write_text(
        render_markdown(triage, target), encoding="utf-8", newline="\n"
    )


def render_markdown(triage: dict[str, Any], target: dict[str, Any]) -> str:
    summary = triage["summary"]
    lines = [
        "# Phase 1 story blocker triage",
        "",
        f"Baseline digest: `{triage['baseline_report_digest_sha256']}`",
        f"Cases: {summary['case_count']}; outcome mismatches: {summary['outcome_mismatch_count']}; "
        f"false blockers: {summary['false_blocker_count']}.",
        "",
        "## False-blocker gates",
        "",
        "| Gate | Cases |",
        "|---|---:|",
    ]
    lines.extend(
        f"| `{gate}` | {count} |"
        for gate, count in summary["false_blocker_gate_counts"].items()
    )
    lines.extend(
        [
            "",
            "## Targeted regression set",
            "",
            "| Case | Profile | Baseline result | Selection reason |",
            "|---|---|---|---|",
        ]
    )
    lines.extend(
        "| {case_id} | {profile} | {result} | {reason} |".format(
            case_id=item["case_id"],
            profile=item["profile"],
            result=item["baseline_classification"],
            reason=", ".join(item["selection_reasons"]),
        )
        for item in target["cases"]
    )
    lines.extend(["", "## Case classification", "", "| Case | Expected | Classification | Gates |", "|---|---|---|---|"])
    lines.extend(
        "| {case_id} | {expected} | {classification} | {gates} |".format(
            case_id=row["case_id"],
            expected=row["expected_decision"],
            classification=row["classification"],
            gates=", ".join(row["failed_gate_ids"]) or "—",
        )
        for row in triage["cases"]
    )
    return "\n".join(lines) + "\n"


def _digest(document: dict[str, Any], field: str) -> str:
    projected = dict(document)
    projected[field] = None
    return hashlib.sha256(
        json.dumps(
            projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
