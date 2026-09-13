"""M7-C mock-safe Stage 2 ZONE queue execution and durable progress."""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from audio_story.adapters.image import ImageRequest, LocalImageAdapter
from audio_story.domain.stage2 import Stage1PackageInput, Stage2Error, Stage2ZonePlan
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage2 import serialize_stage2_progress, validate_visual_plan_bytes
from audio_story.workflows.image_transaction import ImageTransactionResult, generate_single_image
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.stage2_planning import compile_stage2_invocation


@dataclass(frozen=True, slots=True)
class Stage2ExecutionResult:
    status: str
    committed_count: int
    next_pending_basename: str | None
    progress_path: Path | None
    last_transaction: ImageTransactionResult | None


class Stage2ZoneExecutor:
    """Execute exactly one or all pending ZONE assets in dependency order."""

    def __init__(
        self,
        kernel: WorkflowKernel,
        stage_id: str,
        source: Stage1PackageInput,
        plan: Stage2ZonePlan,
        adapter: LocalImageAdapter,
        progress_path: Path,
    ) -> None:
        self.kernel = kernel
        self.stage_id = stage_id
        self.source = source
        self.plan = plan
        self.adapter = adapter
        self.progress_path = progress_path

    def execute_next(self) -> Stage2ExecutionResult:
        committed = self._committed()
        next_name = next(
            (name for name in self.plan.execution_queue if name not in committed), None
        )
        if next_name is None:
            return Stage2ExecutionResult("READY_FOR_AGGREGATE_GATES", 10, None, None, None)
        invocation = compile_stage2_invocation(self.plan, next_name, committed_basenames=committed)
        payload_digest = sha256_bytes(canonical_json_bytes(invocation.payload))
        request = ImageRequest(
            next_name,
            payload_digest,
            sha256_bytes(self.plan.visual_plan_bytes),
            "deterministic-mock",
            self.plan.execution_queue.index(next_name) + 1,
            1,
            3840,
            2160,
            "PNG",
            30.0,
            "preflight",
            "preflight",
        )
        result = generate_single_image(
            self.kernel,
            self.stage_id,
            request,
            self.adapter,
            owner_stage="STAGE2",
            artifact_role="LANDSCAPE",
            max_attempts=1,
        )
        current = self._committed()
        path = None if len(current) == 10 else self._persist_progress()
        return Stage2ExecutionResult(
            "READY_FOR_AGGREGATE_GATES" if len(current) == 10 else "IN_PROGRESS",
            len(current),
            next((name for name in self.plan.execution_queue if name not in current), None),
            path,
            result,
        )

    def execute_all(self) -> Stage2ExecutionResult:
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
            "SELECT t.basename FROM asset_transactions t JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' WHERE t.stage_run_id=? AND t.orientation='LANDSCAPE' ORDER BY t.created_at,t.basename",
            (self.stage_id,),
        ).fetchall()
        found = {str(row["basename"]) for row in rows}
        return tuple(name for name in self.plan.execution_queue if name in found)

    def _persist_progress(self) -> Path:
        rows = self.kernel.db.connection.execute(
            "SELECT t.basename,t.id,a.sha256 FROM asset_transactions t LEFT JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' LEFT JOIN artifacts a ON a.id=b.artifact_id WHERE t.stage_run_id=? AND t.orientation='LANDSCAPE'",
            (self.stage_id,),
        ).fetchall()
        committed = {str(row["basename"]): row for row in rows if row["sha256"] is not None}
        assets = []
        for index, basename in enumerate(self.plan.execution_queue, 1):
            row = committed.get(basename)
            assets.append(
                OrderedDict(
                    basename=basename,
                    execution_index=index,
                    packaging_index=self.plan.packaging_basenames.index(basename) + 1,
                    queue_status="COMMITTED" if row else "PENDING",
                    asset_source="CURRENT_OPERATION" if row else None,
                    file_path=f"landscape/{basename}" if row else None,
                    file_sha256=str(row["sha256"]) if row else None,
                    transaction_id=str(row["id"]) if row else None,
                    postwrite_validation_status="PASS" if row else None,
                )
            )
        pending = [name for name in self.plan.execution_queue if name not in committed]
        visual_plan = validate_visual_plan_bytes(self.plan.visual_plan_bytes)
        value = OrderedDict(
            schema_version="1.0",
            bundle_kind="STAGE2",
            stage="STAGE2",
            orientation="LANDSCAPE",
            original_operation_mode="CREATE",
            input_story_package_digest_sha256=self.source.manifest["package_digest_sha256"],
            input_story_zip_sha256=self.source.package_digest_sha256,
            active_basename_set_digest_sha256=sha256_bytes(
                canonical_json_bytes(list(self.plan.packaging_basenames))
            ),
            visual_plan_digest_sha256=visual_plan["visual_plan_digest_sha256"],
            visual_bible_availability="REQUIRED_PRESENT",
            visual_bible_digest_sha256=sha256_bytes(self.plan.visual_bible_bytes),
            required_count=10,
            committed_count=len(committed),
            pending_count=len(pending),
            failed_count=0,
            assets=assets,
            last_committed_basename=next(
                (name for name in reversed(self.plan.execution_queue) if name in committed), None
            ),
            next_pending_basename=pending[0] if pending else None,
            missing_assets=[
                f"landscape/{name}" for name in self.plan.packaging_basenames if name in pending
            ],
            status="IN_PROGRESS",
            progress_digest_sha256=None,
        )
        data = serialize_stage2_progress(value)
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.progress_path.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, self.progress_path)
        if self.progress_path.read_bytes() != data:
            raise Stage2Error(
                "M7C100_PROGRESS_REOPEN",
                "progress bytes changed after write",
                str(self.progress_path),
            )
        return self.progress_path
