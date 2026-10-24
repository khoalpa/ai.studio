from __future__ import annotations

from dataclasses import dataclass

from .config import registry
from .errors import TransitionError
from .models import Operation, Profile, Stage


@dataclass(frozen=True)
class TransitionRequest:
    profile: Profile
    target_stage: Stage
    operation: Operation
    source_stage: Stage | None = None
    image_mode: str = "ZONE"


class WorkflowStateMachine:
    def validate(self, request: TransitionRequest) -> None:
        if request.image_mode != "ZONE":
            raise TransitionError("Only ZONE image mode is enabled in the MVP")

        if request.operation is Operation.CREATE:
            self._validate_create(request)
        else:
            self._validate_repair(request)

    @staticmethod
    def _validate_create(request: TransitionRequest) -> None:
        if request.target_stage is Stage.STAGE1:
            if request.source_stage is not None:
                raise TransitionError("STAGE1 CREATE must not have a source stage")
            return
        if request.source_stage is None:
            raise TransitionError("CREATE after STAGE1 requires a source stage")
        expected = registry()["workflow"]["transitions"][request.source_stage.value]
        if expected != request.target_stage.value:
            raise TransitionError(
                f"Invalid transition {request.source_stage.value} -> {request.target_stage.value}"
            )

    @staticmethod
    def _validate_repair(request: TransitionRequest) -> None:
        if request.source_stage is not request.target_stage:
            raise TransitionError("REPAIR requires source_stage equal to target_stage")

    @staticmethod
    def allowed_next(stage: Stage) -> Stage | None:
        value = registry()["workflow"]["transitions"][stage.value]
        return Stage(value) if value else None
