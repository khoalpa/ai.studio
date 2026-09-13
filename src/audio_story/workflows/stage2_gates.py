"""Fail-closed M7-C2a landscape gate orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from audio_story.domain.stage2 import ZONE_IMAGE_BASENAMES, Stage2Error, Stage2ZonePlan
from audio_story.domain.state import DetectorClass, GateStatus
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.images import validate_image_qa
from audio_story.workflows.kernel import WorkflowKernel


@dataclass(frozen=True, slots=True)
class SemanticAssessment:
    """Externally supplied per-pixel assessment; never inferred from metadata."""

    basename: str
    status: str
    method: str
    evidence_digest_sha256: str
    observable_findings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Stage2GateResult:
    status: str
    authoritative_count: int
    semantic_pass_count: int
    blocker_codes: tuple[str, ...]
    evidence_digest_sha256: str


def evaluate_stage2_landscape_gates(
    kernel: WorkflowKernel,
    stage_id: str,
    plan: Stage2ZonePlan,
    assessments: Mapping[str, SemanticAssessment],
) -> Stage2GateResult:
    """Evaluate structural and semantic gates on exact committed artifact bytes."""
    rows = kernel.db.connection.execute(
        "SELECT t.basename,t.id transaction_id,b.artifact_id,a.sha256,a.relative_path "
        "FROM asset_transactions t "
        "JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
        "JOIN artifacts a ON a.id=b.artifact_id "
        "WHERE t.stage_run_id=? AND t.orientation='LANDSCAPE'",
        (stage_id,),
    ).fetchall()
    by_name = {str(row["basename"]): row for row in rows}
    blockers: list[str] = []
    if tuple(name for name in ZONE_IMAGE_BASENAMES if name in by_name) != ZONE_IMAGE_BASENAMES:
        blockers.append("M7C201_LANDSCAPE_SET")
    if len({str(row["transaction_id"]) for row in rows}) != 10:
        blockers.append("M7C202_TRANSACTION_CARDINALITY")
    semantic_pass = 0
    evidence: list[dict[str, object]] = []
    plan_digest = sha256_bytes(plan.visual_plan_bytes)
    for index, basename in enumerate(ZONE_IMAGE_BASENAMES, 1):
        row = by_name.get(basename)
        if row is None:
            continue
        data = kernel.store.read(str(row["relative_path"]))
        info = validate_image_qa(data, basename, expected_dimensions=(3840, 2160))
        if info.sha256 != row["sha256"]:
            blockers.append("M7C203_EXACT_BYTES")
            continue
        role_gate = (
            "IDENTITY-PILOT-GATE-01"
            if index == 1
            else "ART-DIRECTION-CALIBRATION-GATE-01"
            if index == 2
            else "COVER-ART-01"
            if basename == "cover.png"
            else "OUTRO-FULL-FRAME-VALIDATION-01"
            if basename == "outro.png"
            else "LANDSCAPE-WAVE-GATE-01"
        )
        assessment = assessments.get(basename)
        semantic_status = (
            GateStatus.PASS
            if assessment is not None
            and assessment.status == "PASS"
            and bool(assessment.observable_findings)
            and len(assessment.evidence_digest_sha256) == 64
            else GateStatus.NOT_VERIFIED
        )
        if semantic_status is GateStatus.PASS:
            semantic_pass += 1
        else:
            blockers.append(f"M7C204_SEMANTIC_NOT_VERIFIED:{basename}")
        semantic_evidence = {
            "basename": basename,
            "file_sha256": info.sha256,
            "transaction_id": str(row["transaction_id"]),
            "transaction_index": index,
            "role_gate": role_gate,
            "assessment_method": assessment.method if assessment else None,
            "assessment_evidence_digest_sha256": (
                assessment.evidence_digest_sha256 if assessment else None
            ),
            "observable_findings": list(assessment.observable_findings) if assessment else [],
        }
        kernel.record_gate(
            stage_id,
            str(row["artifact_id"]),
            role_gate,
            DetectorClass.MODEL_SEMANTIC,
            semantic_status,
            semantic_evidence,
            plan_digest,
            plan_digest,
            "M7-C2a-1.0",
            plan_digest,
        )
        kernel.record_gate(
            stage_id,
            str(row["artifact_id"]),
            "VISUAL-SEMANTIC-TRUTH-GATE-01",
            DetectorClass.MODEL_SEMANTIC,
            semantic_status,
            semantic_evidence,
            plan_digest,
            plan_digest,
            "M7-C2a-1.0",
            plan_digest,
        )
        evidence.append(semantic_evidence)
    aggregate_digest = sha256_bytes(canonical_json_bytes(evidence))
    if semantic_pass != 10:
        blockers.append("M7C205_COHERENCE_NOT_VERIFIED")
    if not blockers and rows:
        last = by_name["outro.png"]
        kernel.record_gate(
            stage_id,
            str(last["artifact_id"]),
            "IMAGE-SET-COHERENCE-GATE-01",
            DetectorClass.MODEL_SEMANTIC,
            GateStatus.PASS,
            {"asset_count": 10, "evidence_digest_sha256": aggregate_digest},
            plan_digest,
            plan_digest,
            "M7-C2a-1.0",
            plan_digest,
        )
    return Stage2GateResult(
        "PASS" if not blockers else "NOT_VERIFIED",
        len(rows),
        semantic_pass,
        tuple(blockers),
        aggregate_digest,
    )


def require_stage2_gate_pass(result: Stage2GateResult) -> None:
    if result.status != "PASS":
        raise Stage2Error(
            "M7C299_AGGREGATE_BLOCKED",
            ",".join(result.blocker_codes),
            "STAGE2_PACKAGE_GATE",
        )
