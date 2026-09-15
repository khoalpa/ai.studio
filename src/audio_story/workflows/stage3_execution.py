"""M8-C single-portrait execution with pilot-first targeted repair."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from audio_story.adapters.image import ImageRequest, LocalImageAdapter
from audio_story.domain.stage3 import Stage2PackageInput, Stage3Error, Stage3PortraitPlan
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.workflows.image_transaction import (
    ImageTransactionResult,
    SemanticImageGateResult,
    generate_single_image,
)
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.stage3_commitment import (
    bind_stage3_commitments,
    validate_stage3_commitments,
)
from audio_story.workflows.stage3_planning import compile_stage3_invocation


@dataclass(frozen=True, slots=True)
class Stage3ExecutionResult:
    status: str
    committed_count: int
    next_pending_basename: str | None
    last_transaction: ImageTransactionResult | None


class Stage3PortraitExecutor:
    def __init__(
        self,
        kernel: WorkflowKernel,
        stage_id: str,
        source: Stage2PackageInput,
        plan: Stage3PortraitPlan,
        adapter: LocalImageAdapter,
        semantic_assessor: Callable[[bytes, ImageRequest], SemanticImageGateResult],
        *,
        workflow_digest: str = "",
        model_identity: str = "deterministic-mock",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.kernel, self.stage_id, self.source, self.plan, self.adapter = (
            kernel,
            stage_id,
            source,
            plan,
            adapter,
        )
        self.model_identity, self.timeout_seconds = model_identity, timeout_seconds
        self.workflow_digest = workflow_digest
        self.semantic_assessor = semantic_assessor

    def execute_next(self) -> Stage3ExecutionResult:
        committed = self._committed()
        name = next((item for item in self.plan.execution_queue if item not in committed), None)
        if name is None:
            return Stage3ExecutionResult("READY_FOR_AGGREGATE_GATES", 10, None, None)
        if committed and self.plan.execution_queue[0] not in committed:
            raise Stage3Error("M8C001_PILOT_BLOCKED", "pilot has not committed", name)
        invocation = compile_stage3_invocation(
            self.source, self.plan, name, committed_basenames=committed
        )
        snapshot = next(item for item in self.plan.adaptation_plan if item["basename"] == name)
        pilot_digest = cast_str(self.plan.pilot_evidence["validation_digest_sha256"])
        request = ImageRequest(
            basename=name,
            prompt_digest=sha256_bytes(canonical_json_bytes(invocation.payload)),
            workflow_digest=self.workflow_digest,
            model_identity=self.model_identity,
            seed=self.plan.execution_queue.index(name) + 1,
            requested_output_count=1,
            requested_width=1080,
            requested_height=1920,
            output_format="PNG",
            timeout_seconds=self.timeout_seconds,
            transaction_id="preflight",
            generation_call_id="preflight",
            commitment_context={
                "transaction_role": "PORTRAIT_PILOT"
                if name == self.plan.execution_queue[0]
                else "STANDARD",
                "transaction_index": self.plan.execution_queue.index(name) + 1,
                "art_direction_id": self.source.visual_bible["art_direction_id"],
                "plan_snapshot": snapshot,
                "plan_digest_sha256": self.plan.adaptation_plan_digest_sha256,
                "pilot_evidence": self.plan.pilot_evidence,
                "pilot_digest": pilot_digest,
                "landscape_reference": snapshot["landscape_reference"],
                "landscape_sha256": snapshot["landscape_sha256"],
            },
        )
        result = generate_single_image(
            self.kernel,
            self.stage_id,
            request,
            self.adapter,
            owner_stage="STAGE3",
            artifact_role="PORTRAIT",
            max_attempts=2,
            retry_seed_step=1009,
            metadata_binder=bind_stage3_commitments,
            semantic_assessor=self.semantic_assessor,
        )
        if result.status == "AUTHORITATIVE" and result.digest:
            validate_stage3_commitments(
                self.kernel.store.get_artifact_by_digest(result.digest),
                name,
                result.transaction_id,
                cast_str(snapshot["landscape_sha256"]),
            )
        current = self._committed()
        next_name = next((item for item in self.plan.execution_queue if item not in current), None)
        return Stage3ExecutionResult(
            "READY_FOR_AGGREGATE_GATES" if len(current) == 10 else "IN_PROGRESS",
            len(current),
            next_name,
            result,
        )

    def execute_all(self) -> Stage3ExecutionResult:
        result = self.execute_next()
        while (
            result.status == "IN_PROGRESS"
            and result.last_transaction is not None
            and result.last_transaction.status == "AUTHORITATIVE"
        ):
            result = self.execute_next()
        return result

    def _committed(self) -> tuple[str, ...]:
        rows = self.kernel.db.connection.execute(
            "SELECT t.basename FROM asset_transactions t JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' WHERE t.stage_run_id=? AND t.orientation='PORTRAIT'",
            (self.stage_id,),
        ).fetchall()
        found = {str(row["basename"]) for row in rows}
        return tuple(name for name in self.plan.execution_queue if name in found)


def cast_str(value: object) -> str:
    if not isinstance(value, str):
        raise Stage3Error("M8C002_CONTEXT", "expected string", "commitment_context")
    return value
