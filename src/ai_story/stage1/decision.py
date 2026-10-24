from __future__ import annotations

from typing import Any

from ..hashing import canonical_json_bytes, sha256_bytes
from .validation import GateResult


def build_quality_decision(
    gates: list[GateResult], *, fixture_mode: bool
) -> dict[str, Any]:
    technical_failures = [
        gate for gate in gates
        if gate.severity == "PUBLISH_BLOCKER"
        and gate.gate_id != "PROFILE_SAFETY_GATE"
        and gate.status != "PASS"
    ]
    safety_gate = next((gate for gate in gates if gate.gate_id == "PROFILE_SAFETY_GATE"), None)
    quality_failures = [
        gate for gate in gates
        if gate.severity == "QUALITY_BLOCKER" and gate.status != "PASS"
    ]
    quality_gate = next((gate for gate in gates if gate.gate_id == "STORY_QUALITY_GATE"), None)
    assessment_basis = (
        str(quality_gate.metrics.get("assessment_basis", "DETERMINISTIC_PREFLIGHT_ONLY"))
        if quality_gate else "MISSING"
    )
    independently_assessed = assessment_basis in {
        "MODEL_CRITIC_CORROBORATED", "MODEL_CRITIC_ASSESSED",
    }

    technical_status = "PASS" if not technical_failures else "FAIL"
    safety_status = "PASS" if safety_gate and safety_gate.status == "PASS" else "FAIL"
    editorial_status = (
        "FAIL" if quality_failures
        else "ASSESSED_PASS" if independently_assessed
        else "NOT_ASSESSED"
    )
    releasable = (
        technical_status == "PASS"
        and safety_status == "PASS"
        and editorial_status == "ASSESSED_PASS"
        and not fixture_mode
    )
    advancement_allowed = (
        technical_status == "PASS"
        and safety_status == "PASS"
        and not quality_failures
    )

    reasons = []
    for gate in technical_failures + quality_failures + ([] if safety_status == "PASS" else [safety_gate]):
        if gate is None:
            continue
        reasons.append({
            "code": "GATE_FAILED",
            "gate_id": gate.gate_id,
            "evidence_id": f"evidence:{gate.gate_id.lower()}",
        })
    if not quality_failures and not independently_assessed:
        reasons.append({
            "code": "MISSING_EDITORIAL_EVIDENCE",
            "gate_id": "STORY_QUALITY_GATE",
            "evidence_id": "evidence:story_quality_gate",
        })
    if fixture_mode:
        reasons.append({
            "code": "TEST_FIXTURE_NOT_RELEASABLE",
            "gate_id": None,
            "evidence_id": None,
        })

    decision = {
        "schema_version": "1.0",
        "workflow_status": "SUCCEEDED" if advancement_allowed else "COMPLETED_WITH_WARNINGS",
        "technical_status": technical_status,
        "safety_status": safety_status,
        "editorial_status": editorial_status,
        "release_status": "PASS" if releasable else "BLOCKED",
        "advancement_status": "ALLOWED" if advancement_allowed else "BLOCKED",
        "continuation_policy": (
            "CONTINUE" if releasable
            else "CONTINUE_WITH_WARNINGS" if advancement_allowed
            else "BLOCKED"
        ),
        "artifact_class": (
            "TEST_FIXTURE" if fixture_mode
            else "PRODUCTION_CANDIDATE" if releasable
            else "EDITORIAL_DRAFT"
        ),
        "assessment_basis": assessment_basis,
        "failed_gate_ids": sorted({
            gate.gate_id for gate in technical_failures + quality_failures
        } | ({"PROFILE_SAFETY_GATE"} if safety_status == "FAIL" else set())),
        "evidence_ids": sorted({
            f"evidence:{gate.gate_id.lower()}" for gate in gates
        }),
        "warning_count": len(reasons),
        "reasons": reasons,
        "decision_digest_sha256": None,
    }
    decision["decision_digest_sha256"] = sha256_bytes(canonical_json_bytes(decision))
    return decision
