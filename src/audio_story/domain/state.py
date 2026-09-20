"""Versioned workflow states, transitions and kernel records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WorkflowStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_INPUT = "WAITING_INPUT"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class StageStatus(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    PACKAGING = "PACKAGING"
    PASS = "PASS"
    FAIL = "FAIL"


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMMITTED = "COMMITTED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_BLOCKING = "FAILED_BLOCKING"


class ArtifactStatus(StrEnum):
    WORKING = "WORKING"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    QUARANTINED = "QUARANTINED"


class MutationStatus(StrEnum):
    MUTABLE = "MUTABLE"
    READ_ONLY = "READ_ONLY"


class CallStatus(StrEnum):
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DetectorClass(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    TOOL_MEASURED = "TOOL_MEASURED"
    MODEL_SEMANTIC = "MODEL_SEMANTIC"


class RecoveryCode(StrEnum):
    CLEAN = "RK_CLEAN"
    TEMP_ORPHAN_QUARANTINED = "RK_TEMP_ORPHAN_QUARANTINED"
    STORE_ORPHAN_FOUND = "RK_STORE_ORPHAN_FOUND"
    DB_FILE_MISSING = "RK_DB_FILE_MISSING"
    DIGEST_MISMATCH = "RK_DIGEST_MISMATCH"
    CALL_INTERRUPTED = "RK_CALL_INTERRUPTED"
    TRANSACTION_INTERRUPTED = "RK_TRANSACTION_INTERRUPTED"
    STALE_GATE = "RK_STALE_GATE"


WORKFLOW_TRANSITIONS = {
    WorkflowStatus.CREATED: {WorkflowStatus.RUNNING, WorkflowStatus.FAILED},
    WorkflowStatus.RUNNING: {
        WorkflowStatus.WAITING_INPUT,
        WorkflowStatus.FAILED,
        WorkflowStatus.COMPLETED,
    },
    WorkflowStatus.WAITING_INPUT: {WorkflowStatus.RUNNING, WorkflowStatus.FAILED},
    # A user can explicitly retry a failed, non-terminal asset.  The retry
    # keeps its transaction and generation-call history rather than creating a
    # new workflow, so it must be able to return the workflow to RUNNING.
    WorkflowStatus.FAILED: {WorkflowStatus.RUNNING},
    WorkflowStatus.COMPLETED: set(),
}

STAGE_TRANSITIONS = {
    StageStatus.PREFLIGHT: {StageStatus.GENERATING, StageStatus.FAIL},
    StageStatus.GENERATING: {StageStatus.VALIDATING, StageStatus.FAIL},
    StageStatus.VALIDATING: {StageStatus.PACKAGING, StageStatus.FAIL},
    StageStatus.PACKAGING: {StageStatus.PASS, StageStatus.FAIL},
    StageStatus.PASS: set(),
    # As above, this transition is used only by the explicit retry command for
    # a FAILED_RETRYABLE transaction.
    StageStatus.FAIL: {StageStatus.GENERATING},
}


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    id: str
    status: WorkflowStatus
    canonical_prompt_sha256: str


@dataclass(frozen=True, slots=True)
class StageRun:
    id: str
    workflow_id: str
    stage: str
    status: StageStatus
    capsule_digest: str


@dataclass(frozen=True, slots=True)
class AssetTransaction:
    id: str
    stage_run_id: str
    orientation: str
    basename: str
    status: TransactionStatus


@dataclass(frozen=True, slots=True)
class GenerationCall:
    id: str
    transaction_id: str
    attempt_index: int
    status: CallStatus


@dataclass(frozen=True, slots=True)
class Artifact:
    id: str
    sha256: str
    owner_stage: str
    status: ArtifactStatus
    mutation_status: MutationStatus


@dataclass(frozen=True, slots=True)
class GateResult:
    id: str
    artifact_id: str
    status: GateStatus
    detector_class: DetectorClass
    is_current: bool


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    workflow_id: str
    sequence_no: int
    event_type: str
    payload_digest: str


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    transaction_id: str
    artifact_id: str
    role: str


@dataclass(frozen=True, slots=True)
class ResumeDecision:
    code: RecoveryCode
    subject_id: str
    action: str


@dataclass(frozen=True, slots=True)
class CommitIntent:
    transaction_id: str
    digest: str
    owner_stage: str
    mutation_status: MutationStatus
