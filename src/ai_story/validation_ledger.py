from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .hashing import canonical_json_bytes, sha256_bytes

LEDGER_PATH = "validation_ledger.json"
PASS_STATUSES = {"PASS", "ASSESSED_PASS", "RESOLVED"}


def _digest(ledger: dict[str, Any]) -> str:
    projected = copy.deepcopy(ledger)
    projected["ledger_digest_sha256"] = None
    return sha256_bytes(canonical_json_bytes(projected))


def _record(
    *,
    record_id: str,
    stage: str,
    category: str,
    severity: str,
    status: str,
    evidence_ids: list[str] | None = None,
    locators: list[str] | None = None,
    details: Any = None,
) -> dict[str, Any]:
    passed = status in PASS_STATUSES
    return {
        "record_id": record_id,
        "stage": stage,
        "category": category,
        "severity": severity,
        "status": status,
        "resolution_status": "RESOLVED" if passed else "OPEN",
        "continuation_policy": "CONTINUE",
        "release_impact": "NONE" if passed else "NOT_RECOMMENDED",
        "evidence_ids": evidence_ids or [],
        "locators": locators or [],
        "details": details,
    }


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for record in records:
        status = str(record["status"])
        counts[status] = counts.get(status, 0) + 1
    open_records = [record for record in records if record["resolution_status"] == "OPEN"]
    return {
        "record_count": len(records),
        "open_warning_count": len(open_records),
        "resolved_count": len(records) - len(open_records),
        "counts_by_status": counts,
        "release_recommendation": "READY" if not open_records else "NOT_RECOMMENDED",
    }


def write_ledger(path: Path, stage: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
    prior_records = existing.get("records", []) if isinstance(existing, dict) else []
    by_id = {
        str(item["record_id"]): item
        for item in prior_records
        if isinstance(item, dict) and item.get("record_id")
    }
    for record in records:
        by_id[record["record_id"]] = record
    merged = list(by_id.values())
    ledger = {
        "schema_version": "1.0",
        "current_stage": stage,
        "records": merged,
        "summary": _summarize(merged),
        "stage_history": [
            *[item for item in existing.get("stage_history", []) if item != stage],
            stage,
        ],
        "ledger_digest_sha256": None,
    }
    ledger["ledger_digest_sha256"] = _digest(ledger)
    path.write_bytes(canonical_json_bytes(ledger))
    return ledger


def stage1_records(report: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for gate in report.get("gates", []):
        findings = gate.get("findings") or gate.get("failure_reason") or []
        locators = gate.get("evidence_locators", [])
        records.append(_record(
            record_id=f"STAGE1:{gate.get('gate_id', 'UNKNOWN')}",
            stage="STAGE1",
            category="STORY_GATE",
            severity=str(gate.get("severity", "QUALITY_BLOCKER")),
            status=str(gate.get("status", "NOT_VERIFIED")),
            evidence_ids=[f"evidence:{str(gate.get('gate_id', 'unknown')).lower()}"],
            locators=[str(item) for item in locators],
            details=findings,
        ))
    return records


def stage2_records(plan: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for asset in plan.get("assets", []):
        basename = str(asset.get("basename", "unknown"))
        assessment = asset.get("landscape_image", {}).get("quality_assessment", {})
        status = str(assessment.get("status", "NOT_VERIFIED"))
        records.append(_record(
            record_id=f"STAGE2:LANDSCAPE:{basename}", stage="STAGE2",
            category="VISUAL_QUALITY", severity="QUALITY_BLOCKER", status=status,
            evidence_ids=[f"asset:landscape/{basename}"],
            locators=[f"visual_plan.assets[{basename}]"], details=assessment,
        ))
    return records


def stage3_records(report: dict[str, Any]) -> list[dict[str, Any]]:
    summary = report.get("summary", {})
    return [_record(
        record_id="STAGE3:PACKAGE_QUALITY", stage="STAGE3",
        category="PACKAGE_QUALITY", severity="QUALITY_BLOCKER",
        status="PASS" if summary.get("publish_verdict") == "PASS" else "FAIL",
        evidence_ids=["artifact:package_quality_report.json"],
        locators=["package_quality_report.summary"], details=summary,
    )]


def stage4_records(review: dict[str, Any], production: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _record(
            record_id="STAGE4:HUMAN_VISUAL_REVIEW", stage="STAGE4",
            category="HUMAN_REVIEW", severity="QUALITY_BLOCKER",
            status="PASS" if review.get("decision") == "APPROVED" else "NOT_VERIFIED",
            evidence_ids=["artifact:visual_review.json"], locators=["visual_review.decision"],
            details={"decision": review.get("decision")},
        ),
        _record(
            record_id="STAGE4:PRODUCTION_PLAN", stage="STAGE4",
            category="PRODUCTION_INTEGRITY", severity="PUBLISH_BLOCKER",
            status=str(production.get("validation", {}).get("status", "NOT_VERIFIED")),
            evidence_ids=["artifact:production_plan.json"],
            locators=["production_plan.validation"], details=production.get("validation", {}),
        ),
    ]


def verify_ledger(ledger: dict[str, Any]) -> None:
    if ledger.get("schema_version") != "1.0" or not isinstance(ledger.get("records"), list):
        raise ValueError("Validation ledger shape is invalid")
    if ledger.get("ledger_digest_sha256") != _digest(ledger):
        raise ValueError("Validation ledger digest is invalid")
