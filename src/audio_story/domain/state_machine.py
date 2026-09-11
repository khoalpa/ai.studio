"""Pure state transition validation."""

from __future__ import annotations

from audio_story.domain.state import (
    STAGE_TRANSITIONS,
    WORKFLOW_TRANSITIONS,
    StageStatus,
    WorkflowStatus,
)


class StateTransitionError(ValueError):
    code = "RK001_INVALID_STATE_TRANSITION"


def transition_workflow(current: WorkflowStatus, target: WorkflowStatus) -> WorkflowStatus:
    if target not in WORKFLOW_TRANSITIONS[current]:
        raise StateTransitionError(f"{current} -> {target}")
    return target


def transition_stage(current: StageStatus, target: StageStatus) -> StageStatus:
    if target not in STAGE_TRANSITIONS[current]:
        raise StateTransitionError(f"{current} -> {target}")
    return target
