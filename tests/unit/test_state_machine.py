from __future__ import annotations

import pytest

from audio_story.domain.state import StageStatus, WorkflowStatus
from audio_story.domain.state_machine import (
    StateTransitionError,
    transition_stage,
    transition_workflow,
)


def test_valid_workflow_and_stage_transitions() -> None:
    assert (
        transition_workflow(WorkflowStatus.CREATED, WorkflowStatus.RUNNING)
        is WorkflowStatus.RUNNING
    )
    assert transition_stage(StageStatus.PREFLIGHT, StageStatus.GENERATING) is StageStatus.GENERATING
    assert transition_stage(StageStatus.PACKAGING, StageStatus.PASS) is StageStatus.PASS


@pytest.mark.parametrize(
    ("function", "current", "target"),
    [
        (transition_workflow, WorkflowStatus.CREATED, WorkflowStatus.COMPLETED),
        (transition_workflow, WorkflowStatus.COMPLETED, WorkflowStatus.RUNNING),
        (transition_stage, StageStatus.PREFLIGHT, StageStatus.PASS),
        (transition_stage, StageStatus.PASS, StageStatus.FAIL),
    ],
)
def test_invalid_transitions_have_stable_code(function, current, target) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(StateTransitionError) as caught:
        function(current, target)
    assert caught.value.code == "RK001_INVALID_STATE_TRANSITION"
