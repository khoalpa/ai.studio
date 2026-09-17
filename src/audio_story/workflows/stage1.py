"""M5 Stage 1 vertical-slice application service."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any, cast

from audio_story.adapters.llm.base import LocalLLMAdapter
from audio_story.adapters.llm.models import GenerationKind, GenerationRequest, PromptCapsule
from audio_story.domain.enums import Route, Stage
from audio_story.domain.models import CompileRequest
from audio_story.domain.stage1 import (
    ProfileContract,
    Stage1Error,
    Stage1Request,
    Stage1Result,
    Stage1Status,
    resolve_profile,
)
from audio_story.domain.state import (
    CallStatus,
    DetectorClass,
    GateStatus,
    StageStatus,
    TransactionStatus,
    WorkflowStatus,
)
from audio_story.prompt_compiler import compile_capsule, parse_prompt
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.errors import ValidationError
from audio_story.validation.stage1 import (
    SCRIPT_ENVIRONMENTS,
    ZONE_ORDER,
    final_script_digest,
    has_terminal_sentence_punctuation,
    ordered_json_bytes,
    story_content_projection,
    unicode_word_count,
    validate_character_assets,
    validate_generated_segment_language,
    validate_production_script_content,
    validate_report_bytes,
    validate_script_language,
    validate_story_bytes,
    word_count,
)
from audio_story.validation.strict_json import OrderedObject, parse_json_bytes, validate_field_order
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.recovery import recover
from audio_story.workflows.stage1_capsule_projection import project_stage1_capsule
from audio_story.workflows.stage1_characters import (
    CharacterImageConfig,
    generate_character_reference,
)
from audio_story.workflows.stage1_materialization import (
    StoryQualityResult,
    finalize_production_quality,
    materialize_production_story,
)
from audio_story.workflows.stage1_package import (
    PROMPT_VERSION,
    build_manifest,
    build_series_anchor,
    build_story_zip,
    character_set_digest,
    mock_character_png,
)
from audio_story.workflows.stage1_zone_generation import (
    ZONE_ITEM_ORDER,
    ZONE_PAYLOAD_ORDER,
    aggregate_zone_payloads,
    is_repetitive_story_text,
    normalized_story_text,
    validate_story_repetition,
    validate_zone_payload,
)


class Stage1Service:
    """Run Stage 1 with M1 capsule, M3 lineage and an M4 local adapter."""

    def __init__(
        self,
        kernel: WorkflowKernel,
        adapter: LocalLLMAdapter,
        canonical_path: Path,
        fault_hook: Callable[[str], None] | None = None,
        character_image_config: CharacterImageConfig | None = None,
        story_quality_assessor: Callable[[bytes, OrderedDict[str, bytes]], StoryQualityResult]
        | None = None,
    ) -> None:
        self.kernel = kernel
        self.adapter = adapter
        self.canonical_path = canonical_path
        self.fault_hook = fault_hook
        self.character_image_config = character_image_config
        self.story_quality_assessor = story_quality_assessor

    def start(self, request: Stage1Request) -> Stage1Result:
        contract = resolve_profile(request.profile, request.language)
        capsule = self._capsule(contract)
        config_digest = _config_digest(request, contract)
        workflow_id = self.kernel.create_workflow(
            contract.profile, "STAGE1", "CREATE", capsule.digest, config_digest
        )
        self.kernel.transition_workflow(workflow_id, WorkflowStatus.RUNNING)
        stage_id = self.kernel.start_stage(workflow_id, "STAGE1", capsule.digest)
        if not request.duration_confirmed or request.duration_minutes is None:
            self.kernel.transition_workflow(workflow_id, WorkflowStatus.WAITING_INPUT)
            return Stage1Result(
                Stage1Status.WAITING_INPUT,
                workflow_id,
                stage_id,
                reason_code="S105_DURATION_CONFIRMATION_REQUIRED",
            )
        try:
            return self._execute(workflow_id, stage_id, request, contract, capsule)
        except Stage1Error:
            self._fail_active_run(workflow_id, stage_id)
            raise

    def resume_duration(
        self, workflow_id: str, stage_id: str, request: Stage1Request
    ) -> Stage1Result:
        contract = resolve_profile(request.profile, request.language)
        if not request.duration_confirmed or request.duration_minutes is None:
            raise Stage1Error(
                "S105_DURATION_CONFIRMATION_REQUIRED",
                "duration must be explicitly confirmed",
                "$.duration_confirmed",
            )
        row = self.kernel.db.connection.execute(
            "SELECT w.status,w.profile,s.capsule_digest FROM workflow_runs w "
            "JOIN stage_runs s ON s.workflow_id=w.id WHERE w.id=? AND s.id=?",
            (workflow_id, stage_id),
        ).fetchone()
        if row is None or row["status"] != WorkflowStatus.WAITING_INPUT:
            raise Stage1Error("S160_RECOVERY_CONFLICT", "workflow is not waiting", workflow_id)
        if row["profile"] != contract.profile:
            raise Stage1Error("S121_PROFILE_MISMATCH", "profile changed during resume", "$.profile")
        capsule = self._capsule(contract)
        if row["capsule_digest"] != capsule.digest:
            raise Stage1Error("S106_CAPSULE_BINDING", "capsule changed during resume", stage_id)
        with self.kernel.db.transaction() as connection:
            connection.execute(
                "UPDATE workflow_runs SET config_digest=? WHERE id=?",
                (_config_digest(request, contract), workflow_id),
            )
        self.kernel.transition_workflow(workflow_id, WorkflowStatus.RUNNING)
        return self._execute(workflow_id, stage_id, request, contract, capsule)

    def resume_recovery(
        self, workflow_id: str, stage_id: str, request: Stage1Request
    ) -> Stage1Result:
        """Recover persisted M3 state in a fresh service instance and continue Stage 1."""
        recover(self.kernel, workflow_id)
        contract = resolve_profile(request.profile, request.language)
        capsule = self._capsule(contract)
        row = self.kernel.db.connection.execute(
            "SELECT w.profile,s.capsule_digest FROM workflow_runs w JOIN stage_runs s "
            "ON s.workflow_id=w.id WHERE w.id=? AND s.id=?",
            (workflow_id, stage_id),
        ).fetchone()
        if (
            row is None
            or row["profile"] != contract.profile
            or row["capsule_digest"] != capsule.digest
        ):
            raise Stage1Error(
                "S160_RECOVERY_CONFLICT", "persisted workflow binding differs", workflow_id
            )
        return self._execute(workflow_id, stage_id, request, contract, capsule)

    def _execute(
        self,
        workflow_id: str,
        stage_id: str,
        request: Stage1Request,
        contract: ProfileContract,
        capsule: PromptCapsule,
    ) -> Stage1Result:
        duration = request.duration_minutes
        assert duration is not None
        if not contract.min_minutes <= duration <= contract.max_minutes:
            raise Stage1Error(
                "S107_DURATION_RANGE", "duration is outside profile range", "$.duration_minutes"
            )

        stage_status = self.kernel.db.connection.execute(
            "SELECT status FROM stage_runs WHERE id=?", (stage_id,)
        ).fetchone()[0]
        if stage_status == StageStatus.PREFLIGHT:
            self.kernel.transition_stage(stage_id, StageStatus.GENERATING)
        phase_outputs: list[bytes] = []
        phases = (
            ("plan", "draft", "review", "repair")
            if not request.test_mode
            else ("plan", "draft", "review", "repair", "serialize")
        )
        for phase in phases:
            phase_outputs.append(
                self._call_phase(
                    stage_id,
                    phase,
                    capsule,
                    request.seed,
                    production=not request.test_mode,
                    upstream_outputs=tuple(phase_outputs),
                    creative_input=request.creative_input,
                    language=request.language,
                )
            )
            self._boundary(f"after_{phase}")
        if not request.test_mode:
            phase_outputs.append(
                self._build_production_serialize(
                    stage_id, request, contract, capsule, tuple(phase_outputs)
                )
            )
            self._boundary("after_serialize")
            if self.character_image_config is None:
                return Stage1Result(
                    Stage1Status.WAITING_DEPENDENCY,
                    workflow_id,
                    stage_id,
                    reason_code="S144_CHARACTER_REFERENCE_PRODUCTION_REQUIRED",
                )
            serialized = parse_json_bytes(
                phase_outputs[-1], "stage1_serialize.json", engine_generated=True
            ).value
            characters = serialized["payload"]["story"]["characters"]
            image_results = []
            for index, character in enumerate(characters):
                result = generate_character_reference(
                    self.kernel,
                    stage_id,
                    character,
                    capsule.digest,
                    request.seed + index,
                    self.character_image_config,
                )
                if result.status != "AUTHORITATIVE":
                    raise Stage1Error(
                        "S145_CHARACTER_REFERENCE_GENERATION_FAILED",
                        "production character reference did not pass image authority",
                        str(character["character_id"]),
                    )
                image_results.append(result)
            story, assets, story_bytes = materialize_production_story(
                self.kernel,
                serialized["payload"]["story"],
                image_results,
                request,
                contract,
            )
            if self.story_quality_assessor is None:
                return Stage1Result(
                    Stage1Status.WAITING_DEPENDENCY,
                    workflow_id,
                    stage_id,
                    reason_code="S147_PRODUCTION_QUALITY_EVIDENCE_REQUIRED",
                )
            quality = self.story_quality_assessor(story_bytes, assets)
            story_bytes = finalize_production_quality(story, assets, quality)
            parsed_story = validate_story_bytes(story_bytes, contract)
            validate_production_script_content(parsed_story["script"])
            self._checkpoint_bytes(stage_id, "story.json", story_bytes, capsule)
            report = _build_report(
                story,
                story_bytes,
                assets,
                contract,
                quality_evidence=quality.evidence,
            )
            report_bytes = ordered_json_bytes(report)
            validate_report_bytes(report_bytes, story_bytes, parsed_story)
            self._checkpoint_bytes(stage_id, "story_validation.json", report_bytes, capsule)
            return self._publish_stage1_package(
                workflow_id,
                stage_id,
                contract,
                capsule,
                story_bytes,
                report_bytes,
                assets,
                anchor_bytes=(
                    build_series_anchor(story)
                    if contract.profile.value == "SERIAL_DETECTIVE"
                    else None
                ),
            )
        story, assets = _build_story(request, contract)
        self._boundary("after_final_integrity")
        validate_character_assets(story, assets, test_mode=request.test_mode)
        story_bytes = ordered_json_bytes(story)
        pending = self.kernel.workspace / "outputs" / workflow_id / ".pending"
        pending.mkdir(parents=True, exist_ok=True)
        (pending / "story.json").write_bytes(story_bytes)
        self._boundary("after_story_write")
        parsed_story = validate_story_bytes(story_bytes, contract)
        if not request.test_mode:
            validate_production_script_content(parsed_story["script"])
        anchor_bytes = (
            build_series_anchor(story) if contract.profile.value == "SERIAL_DETECTIVE" else None
        )
        if anchor_bytes is None:
            self._checkpoint_bytes(stage_id, "story.json", story_bytes, capsule)
        else:
            logical_set = canonical_json_bytes(
                {
                    "story_sha256": sha256_bytes(story_bytes),
                    "series_anchor_sha256": sha256_bytes(anchor_bytes),
                }
            )
            self._checkpoint_bytes(stage_id, "story-anchor-set.json", logical_set, capsule)
        self._boundary("after_story_binding")
        report = _build_report(story, story_bytes, assets, contract)
        report_bytes = ordered_json_bytes(report)
        validate_report_bytes(report_bytes, story_bytes, parsed_story)
        (pending / "story_validation.json").write_bytes(report_bytes)
        self._checkpoint_bytes(stage_id, "story_validation.json", report_bytes, capsule)
        self._boundary("after_report_write")
        members: OrderedDict[str, bytes] = OrderedDict()
        members["story.json"] = story_bytes
        members["story_validation.json"] = report_bytes
        members.update(assets)
        if anchor_bytes is not None:
            members["series_anchor.json"] = anchor_bytes
        manifest = build_manifest(contract.profile, story_bytes, members)
        (pending / "workflow_manifest.json").write_bytes(manifest)
        self._checkpoint_bytes(stage_id, "workflow_manifest.json", manifest, capsule)
        self._boundary("after_manifest_write")
        output = self.kernel.workspace / "outputs" / workflow_id / "story.zip"
        package_digest = build_story_zip(output, manifest, members)
        self._boundary("after_zip_publish")
        package_transaction = self.kernel.get_or_create_transaction(
            stage_id, "PACKAGE", "story.zip"
        )
        package_status = self.kernel.db.connection.execute(
            "SELECT status FROM asset_transactions WHERE id=?", (package_transaction,)
        ).fetchone()[0]
        if package_status == TransactionStatus.COMMITTED:
            return self._finish(workflow_id, stage_id, output, package_digest)
        package_call = self.kernel.begin_generation_call(
            package_transaction,
            sha256_bytes(canonical_json_bytes({"package_digest": package_digest})),
            model_identity="deterministic-packager",
            adapter_version="M5-1.0",
        )
        package_artifact = self.kernel.register_candidate(
            package_call,
            output.read_bytes(),
            "application/zip",
            "STAGE1",
            artifact_role="ARCHIVE",
            dependency_digest=capsule.digest,
        )
        self.kernel.record_gate(
            stage_id,
            package_artifact,
            "STAGE1_PACKAGE_GATE",
            DetectorClass.DETERMINISTIC,
            GateStatus.PASS,
            {"package_digest": package_digest, "post_package_reopen": "PASS"},
            sha256_bytes(self.canonical_path.read_bytes()),
            capsule.digest,
            "M5-1.0",
            capsule.digest,
        )
        self.kernel.finish_generation_call(
            package_call,
            CallStatus.FINISHED,
            package_digest,
            model_identity="deterministic-packager",
            adapter_version="M5-1.0",
            duration_ms=0,
            termination_reason="COMPLETED",
        )
        self.kernel.commit_artifact(package_transaction, package_artifact)
        self._boundary("after_zip_binding")
        return self._finish(workflow_id, stage_id, output, package_digest)

    def _fail_active_run(self, workflow_id: str, stage_id: str) -> None:
        """Persist terminal failure when Stage 1 exits through an exception."""
        stage_status = StageStatus(
            self.kernel.db.connection.execute(
                "SELECT status FROM stage_runs WHERE id=?", (stage_id,)
            ).fetchone()[0]
        )
        if stage_status not in {StageStatus.PASS, StageStatus.FAIL}:
            self.kernel.transition_stage(stage_id, StageStatus.FAIL)
        workflow_status = WorkflowStatus(
            self.kernel.db.connection.execute(
                "SELECT status FROM workflow_runs WHERE id=?", (workflow_id,)
            ).fetchone()[0]
        )
        if workflow_status not in {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED}:
            self.kernel.transition_workflow(workflow_id, WorkflowStatus.FAILED)

    def _finish(
        self, workflow_id: str, stage_id: str, output: Path, package_digest: str
    ) -> Stage1Result:
        self.kernel.transition_stage(stage_id, StageStatus.VALIDATING)
        self.kernel.transition_stage(stage_id, StageStatus.PACKAGING)
        self.kernel.transition_stage(stage_id, StageStatus.PASS)
        self.kernel.transition_workflow(workflow_id, WorkflowStatus.COMPLETED)
        return Stage1Result(Stage1Status.PASS, workflow_id, stage_id, output, package_digest)

    def _publish_stage1_package(
        self,
        workflow_id: str,
        stage_id: str,
        contract: ProfileContract,
        capsule: PromptCapsule,
        story_bytes: bytes,
        report_bytes: bytes,
        assets: OrderedDict[str, bytes],
        anchor_bytes: bytes | None,
    ) -> Stage1Result:
        """Publish a validated production Stage 1 package idempotently."""
        pending = self.kernel.workspace / "outputs" / workflow_id / ".pending"
        pending.mkdir(parents=True, exist_ok=True)
        members: OrderedDict[str, bytes] = OrderedDict()
        members["story.json"] = story_bytes
        members["story_validation.json"] = report_bytes
        members.update(assets)
        if anchor_bytes is not None:
            members["series_anchor.json"] = anchor_bytes
        manifest = build_manifest(contract.profile, story_bytes, members)
        (pending / "workflow_manifest.json").write_bytes(manifest)
        self._checkpoint_bytes(stage_id, "workflow_manifest.json", manifest, capsule)
        self._boundary("after_manifest_write")
        output = self.kernel.workspace / "outputs" / workflow_id / "story.zip"
        package_digest = build_story_zip(output, manifest, members)
        self._boundary("after_zip_publish")
        package_transaction = self.kernel.get_or_create_transaction(
            stage_id, "PACKAGE", "story.zip"
        )
        status = self.kernel.db.connection.execute(
            "SELECT status FROM asset_transactions WHERE id=?", (package_transaction,)
        ).fetchone()[0]
        if status != TransactionStatus.COMMITTED:
            package_call = self.kernel.begin_generation_call(
                package_transaction,
                sha256_bytes(canonical_json_bytes({"package_digest": package_digest})),
                model_identity="deterministic-packager",
                adapter_version="M5-1.0",
            )
            package_artifact = self.kernel.register_candidate(
                package_call,
                output.read_bytes(),
                "application/zip",
                "STAGE1",
                artifact_role="ARCHIVE",
                dependency_digest=capsule.digest,
            )
            self.kernel.record_gate(
                stage_id,
                package_artifact,
                "STAGE1_PACKAGE_GATE",
                DetectorClass.DETERMINISTIC,
                GateStatus.PASS,
                {"package_digest": package_digest, "post_package_reopen": "PASS"},
                sha256_bytes(self.canonical_path.read_bytes()),
                capsule.digest,
                "M5-1.0",
                capsule.digest,
            )
            self.kernel.finish_generation_call(
                package_call,
                CallStatus.FINISHED,
                package_digest,
                model_identity="deterministic-packager",
                adapter_version="M5-1.0",
                duration_ms=0,
                termination_reason="COMPLETED",
            )
            self.kernel.commit_artifact(package_transaction, package_artifact)
            self._boundary("after_zip_binding")
        return self._finish(workflow_id, stage_id, output, package_digest)

    def _checkpoint_bytes(
        self, stage_id: str, basename: str, data: bytes, capsule: PromptCapsule
    ) -> None:
        transaction = self.kernel.get_or_create_transaction(stage_id, "STAGE1", basename)
        status = self.kernel.db.connection.execute(
            "SELECT status FROM asset_transactions WHERE id=?", (transaction,)
        ).fetchone()[0]
        if status == TransactionStatus.COMMITTED:
            return
        digest = sha256_bytes(data)
        call = self.kernel.begin_generation_call(
            transaction,
            sha256_bytes(canonical_json_bytes({"basename": basename, "sha256": digest})),
            model_identity="deterministic-stage1-writer",
            adapter_version="M5-1.0",
        )
        artifact = self.kernel.register_candidate(
            call,
            data,
            "application/json",
            "STAGE1",
            artifact_role="STORY",
            dependency_digest=capsule.digest,
        )
        self.kernel.record_gate(
            stage_id,
            artifact,
            f"STAGE1_{basename.upper()}_GATE",
            DetectorClass.DETERMINISTIC,
            GateStatus.PASS,
            {"basename": basename, "sha256": digest},
            sha256_bytes(self.canonical_path.read_bytes()),
            capsule.digest,
            "M5-1.0",
            capsule.digest,
        )
        self.kernel.finish_generation_call(
            call,
            CallStatus.FINISHED,
            digest,
            model_identity="deterministic-stage1-writer",
            adapter_version="M5-1.0",
            duration_ms=0,
            termination_reason="COMPLETED",
        )
        self.kernel.commit_artifact(transaction, artifact)

    def _call_phase(
        self,
        stage_id: str,
        phase: str,
        capsule: PromptCapsule,
        seed: int,
        *,
        production: bool,
        upstream_outputs: tuple[bytes, ...],
        creative_input: str = "",
        language: str = "vi",
    ) -> bytes:
        transaction = self.kernel.get_or_create_transaction(stage_id, "TEXT", f"{phase}.json")
        status = self.kernel.db.connection.execute(
            "SELECT status FROM asset_transactions WHERE id=?", (transaction,)
        ).fetchone()[0]
        if status == TransactionStatus.COMMITTED:
            row = self.kernel.db.connection.execute(
                "SELECT a.sha256 FROM artifact_bindings b "
                "JOIN artifacts a ON a.id=b.artifact_id "
                "WHERE b.transaction_id=? AND b.role='COMMITTED'",
                (transaction,),
            ).fetchone()
            if row is None:
                raise Stage1Error(
                    "S160_RECOVERY_CONFLICT", "committed phase has no artifact binding", phase
                )
            committed = self.kernel.store.get_artifact_by_digest(str(row["sha256"]))
            if production:
                try:
                    _validate_production_phase(committed, phase)
                except (ValidationError, ValueError, KeyError) as exc:
                    raise Stage1Error(
                        "S161_COMMITTED_PHASE_SCHEMA_DRIFT",
                        "committed production phase no longer satisfies the active contract",
                        phase,
                    ) from exc
            return committed
        instruction = (
            _production_phase_instruction(phase, upstream_outputs)
            if production
            else f"STAGE1_{phase.upper()} digest-only bounded call"
        )
        if production and creative_input:
            instruction += f"\nUser-locked creative input: {creative_input}"
        if production:
            instruction += "\n" + _language_instruction(language)
        request = GenerationRequest(
            capsule,
            instruction,
            GenerationKind.STRUCTURED if production else GenerationKind.TEXT,
            max_output_tokens=8192,
            schema_name=f"stage1_{phase}.json" if production else None,
            schema_version="1.0" if production else None,
            field_order=PRODUCTION_PHASE_ROOT_ORDER if production else None,
            seed=seed,
        )
        request_digest = sha256_bytes(
            canonical_json_bytes(
                {"capsule": capsule.digest, "instruction": instruction, "seed": seed}
            )
        )
        last_error: Exception | None = None
        for _ in range(2):
            call_id = self.kernel.begin_generation_call(transaction, request_digest)
            try:
                self._boundary(f"during_{phase}")
                if production:
                    response = self.adapter.generate_structured(request, Event())
                    _validate_production_phase(response.content, phase)
                    response_digest = sha256_bytes(response.content)
                    evidence_bytes = response.content
                    model = response.model_identity
                    version = response.adapter_version
                    duration_ms = response.duration_ms
                    termination = str(response.termination_reason)
                elif phase in {"review", "repair"}:
                    assessment = self.adapter.assess_semantic(request, Event())
                    response_digest = sha256_bytes(canonical_json_bytes(assessment.evidence))
                    model = "semantic-local"
                    version = "1.0"
                    duration_ms = 0
                    termination = "COMPLETED"
                else:
                    response = self.adapter.generate_text(request, Event())
                    response_digest = sha256_bytes(response.content)
                    evidence_bytes = response.content
                    model = response.model_identity
                    version = response.adapter_version
                    duration_ms = response.duration_ms
                    termination = str(response.termination_reason)
                if not production and phase in {"review", "repair"}:
                    evidence_bytes = canonical_json_bytes(assessment.evidence)
                artifact = self.kernel.register_candidate(
                    call_id,
                    evidence_bytes,
                    "application/json",
                    "STAGE1",
                    artifact_role="STORY",
                    dependency_digest=capsule.digest,
                )
                self.kernel.record_gate(
                    stage_id,
                    artifact,
                    f"STAGE1_{phase.upper()}_CHECKPOINT",
                    DetectorClass.DETERMINISTIC,
                    GateStatus.PASS,
                    {
                        "phase": phase,
                        "response_digest": response_digest,
                        "schema_version": "1.0" if production else "TEST_ONLY",
                        "field_order": list(PRODUCTION_PHASE_ROOT_ORDER) if production else [],
                    },
                    sha256_bytes(self.canonical_path.read_bytes()),
                    capsule.digest,
                    "M5-1.0",
                    capsule.digest,
                )
                self.kernel.finish_generation_call(
                    call_id,
                    CallStatus.FINISHED,
                    response_digest,
                    model_identity=model,
                    adapter_version=version,
                    duration_ms=duration_ms,
                    termination_reason=termination,
                )
                self.kernel.commit_artifact(transaction, artifact)
                return evidence_bytes
            except Exception as exc:
                last_error = exc
                self.kernel.finish_generation_call(
                    call_id,
                    CallStatus.FAILED,
                    failure_code="S110_GENERATION_FAILURE",
                    termination_reason=type(exc).__name__,
                )
        raise Stage1Error(
            "S111_RETRY_EXHAUSTED", "local generation retry budget exhausted", phase
        ) from last_error

    def _build_production_serialize(
        self,
        stage_id: str,
        request: Stage1Request,
        contract: ProfileContract,
        capsule: PromptCapsule,
        upstream_outputs: tuple[bytes, ...],
    ) -> bytes:
        """Generate bounded zone payloads and deterministically assemble serialize.json."""
        plan = _validate_production_phase(upstream_outputs[0], "plan")
        story_bible = _build_story_bible(plan, request.language)
        counts = _zone_item_counts(contract.min_script_items)
        word_budgets = _zone_word_budgets(contract)
        zones: dict[str, OrderedObject] = {}
        for index, zone in enumerate(ZONE_ORDER):
            minimum, maximum = word_budgets[zone]
            minimum_item, minimum_remainder = divmod(minimum, counts[zone])
            maximum_item, maximum_remainder = divmod(maximum, counts[zone])
            items: list[OrderedObject] = []
            for item_index in range(counts[zone]):
                item_budget = (
                    minimum_item + (1 if item_index < minimum_remainder else 0),
                    maximum_item + (1 if item_index < maximum_remainder else 0),
                )
                item = self._call_zone_item(
                    stage_id,
                    zone,
                    item_index + 1,
                    item_budget,
                    capsule,
                    request.seed + index * 100 + item_index,
                    upstream_outputs,
                    request.language,
                    story_bible,
                )
                item["item_id"] = f"{zone.lower()}_{item_index + 1:03d}"
                items.append(item)
            zones[zone] = OrderedObject(
                [
                    ("schema_version", "1.0"),
                    ("zone", zone),
                    ("status", "PASS"),
                    ("items", items),
                ]
            )
            self._boundary(f"after_zone_{zone.lower()}")
        last_text = str(zones[ZONE_ORDER[-1]]["items"][-1]["text"])
        characters: list[OrderedDict[str, Any]] = [
            OrderedDict(
                character_id="char_001",
                name="Nhân vật chính",
                age=16 if str(contract.profile) == "YOUTH_SAFE" else 30,
                role="protagonist",
                description=f"Nhân vật trung tâm của {request.title}.",
            )
        ]
        story = aggregate_zone_payloads(
            request.title,
            characters,
            str(plan["payload"]["premise"]),
            last_text,
            zones,
            counts,
            word_budgets,
            language=request.language,
        )
        validate_script_language(story["script"], request.language)
        validate_story_repetition(story["script"])
        serialized = ordered_json_bytes(
            OrderedDict(
                schema_version="1.0",
                phase="serialize",
                status="PASS",
                payload=OrderedDict(story=story),
            )
        )
        _validate_production_phase(serialized, "serialize")
        self._checkpoint_bytes(stage_id, "serialize.json", serialized, capsule)
        return serialized

    def _call_zone_item(
        self,
        stage_id: str,
        zone: str,
        item_index: int,
        word_budget: tuple[int, int],
        capsule: PromptCapsule,
        seed: int,
        upstream_outputs: tuple[bytes, ...],
        language: str,
        story_bible: str,
    ) -> OrderedObject:
        minimum_segments = 3
        maximum_segments = max(minimum_segments, (word_budget[0] + 9) // 10 + 2)
        segment_ceiling = max(35, (word_budget[0] + minimum_segments - 1) // minimum_segments + 10)
        texts: list[str] = []
        for segment_index in range(maximum_segments):
            completed_words = sum(unicode_word_count(text) for text in texts)
            if segment_index >= minimum_segments and completed_words >= word_budget[0]:
                break
            segment_budget = (
                1,
                min(segment_ceiling, word_budget[1] - completed_words),
            )
            if segment_budget[0] > segment_budget[1]:
                raise Stage1Error(
                    "S163_ZONE_RETRY_EXHAUSTED", "item word budget cannot be completed", zone
                )
            segment = self._call_segment(
                stage_id,
                zone,
                item_index,
                segment_index + 1,
                segment_budget,
                capsule,
                seed + (item_index - 1) * maximum_segments + segment_index,
                upstream_outputs,
                language,
                story_bible,
            )
            texts.append(str(segment["text"]).strip())
        if sum(unicode_word_count(text) for text in texts) < word_budget[0]:
            raise Stage1Error("S163_ZONE_RETRY_EXHAUSTED", "item word budget exhausted", zone)
        item = OrderedObject(
            [
                ("item_id", f"{zone.lower()}_{item_index:03d}"),
                ("speaker_id", "narrator"),
                ("voice", "narrator"),
                ("speed", "NORMAL"),
                ("environment", "none"),
                ("text", " ".join(texts)),
            ]
        )
        wrapper = OrderedObject(
            [
                ("schema_version", "1.0"),
                ("zone", zone),
                ("status", "PASS"),
                ("items", [item]),
            ]
        )
        validate_zone_payload(wrapper, zone, 1, *word_budget)
        return item

    def _call_segment(
        self,
        stage_id: str,
        zone: str,
        item_index: int,
        segment_index: int,
        word_budget: tuple[int, int],
        capsule: PromptCapsule,
        seed: int,
        upstream_outputs: tuple[bytes, ...],
        language: str,
        story_bible: str,
    ) -> OrderedObject:
        basename = f"segment-{zone.lower()}-{item_index:03d}-{segment_index:02d}.json"
        transaction = self.kernel.get_or_create_transaction(stage_id, "TEXT", basename)
        status = self.kernel.db.connection.execute(
            "SELECT status FROM asset_transactions WHERE id=?", (transaction,)
        ).fetchone()[0]
        if status == TransactionStatus.COMMITTED:
            row = self.kernel.db.connection.execute(
                "SELECT a.sha256 FROM artifact_bindings b JOIN artifacts a ON a.id=b.artifact_id "
                "WHERE b.transaction_id=? AND b.role='COMMITTED'",
                (transaction,),
            ).fetchone()
            if row is None:
                raise Stage1Error("S160_RECOVERY_CONFLICT", "committed zone has no binding", zone)
            committed = self.kernel.store.get_artifact_by_digest(str(row["sha256"]))
            try:
                parsed = parse_json_bytes(committed, basename, engine_generated=True).value
                try:
                    validated = validate_zone_payload(parsed, zone, 1, *word_budget)
                except ValueError as exc:
                    message = str(exc)
                    code = (
                        "S164_SEGMENT_UNDER_BUDGET"
                        if "below its word budget" in message
                        else "S165_SEGMENT_OVER_BUDGET"
                        if "exceeds its word budget" in message
                        else "S162_ZONE_GENERATION_FAILURE"
                    )
                    actual_words = _generated_segment_word_count(parsed)
                    raise _SegmentRejection(
                        code,
                        message,
                        actual_words=actual_words,
                        rejected_text=_generated_segment_text(parsed),
                    ) from exc
                return cast(OrderedObject, validated["items"][0])
            except (ValidationError, ValueError, KeyError) as exc:
                raise Stage1Error(
                    "S161_COMMITTED_PHASE_SCHEMA_DRIFT",
                    "committed zone no longer satisfies the active contract",
                    zone,
                ) from exc
        prior_segments: list[tuple[str, str]] = []
        prior_rows = self.kernel.db.connection.execute(
            "SELECT t.basename,a.sha256 FROM asset_transactions t "
            "JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
            "JOIN artifacts a ON a.id=b.artifact_id "
            "WHERE t.stage_run_id=? AND t.basename LIKE ? AND t.id<>? "
            "ORDER BY t.basename",
            (stage_id, "segment-%.json", transaction),
        ).fetchall()
        for prior_row in prior_rows:
            prior = parse_json_bytes(
                self.kernel.store.get_artifact_by_digest(str(prior_row["sha256"])),
                str(prior_row["basename"]),
                engine_generated=True,
            ).value
            prior_segments.append(
                (
                    str(prior_row["sha256"]),
                    normalized_story_text(str(prior["items"][0]["text"])),
                )
            )
        instruction = _production_zone_instruction(
            zone,
            1,
            word_budget,
            upstream_outputs,
            item_index=item_index,
            segment_index=segment_index,
            forbidden_texts=tuple(text for _, text in prior_segments),
            language=language,
            story_bible=story_bible,
        )
        prompt_context = project_stage1_capsule(capsule)
        generation_request = GenerationRequest(
            capsule,
            instruction,
            GenerationKind.STRUCTURED,
            max_output_tokens=4096,
            field_order=ZONE_PAYLOAD_ORDER,
            seed=seed,
            json_schema=_segment_json_schema(word_budget, zone, item_index, segment_index),
            prompt_context=prompt_context,
            temperature=0.3,
            top_p=0.9,
        )
        schema_digest = sha256_bytes(canonical_json_bytes(generation_request.json_schema))
        context_digest = sha256_bytes(prompt_context)
        last_error: Exception | None = None
        retry_feedback = ""
        attempt_offset = self.kernel.db.connection.execute(
            "SELECT COUNT(*) FROM generation_calls WHERE transaction_id=?", (transaction,)
        ).fetchone()[0]
        target_words = (word_budget[0] + word_budget[1]) // 2
        for attempt in range(4):
            attempt_instruction = instruction + retry_feedback
            if (
                isinstance(last_error, _SegmentRejection)
                and last_error.code == "S166_SEGMENT_DUPLICATE"
            ):
                attempt_instruction += "\n" + _segment_novelty_instruction(
                    zone, item_index, segment_index, language, variation=attempt
                )
            active_request = replace(
                generation_request,
                instruction=attempt_instruction,
                seed=seed + attempt_offset + attempt,
                temperature=0.7
                if isinstance(last_error, _SegmentRejection)
                and last_error.code == "S166_SEGMENT_DUPLICATE"
                else 0.3,
            )
            request_digest = sha256_bytes(
                canonical_json_bytes(
                    {
                        "capsule": capsule.digest,
                        "instruction": active_request.instruction,
                        "seed": active_request.seed,
                        "json_schema_sha256": schema_digest,
                        "prompt_context_sha256": context_digest,
                        "temperature": active_request.temperature,
                        "top_p": active_request.top_p,
                    }
                )
            )
            call_id = self.kernel.begin_generation_call(transaction, request_digest)
            response_digest: str | None = None
            try:
                self._boundary(f"during_zone_{zone.lower()}")
                response = self.adapter.generate_structured(active_request, Event())
                response_digest = sha256_bytes(response.content)
                artifact = self.kernel.register_candidate(
                    call_id,
                    response.content,
                    "application/json",
                    "STAGE1",
                    artifact_role="STORY",
                    dependency_digest=capsule.digest,
                )
                parsed = parse_json_bytes(response.content, basename, engine_generated=True).value
                try:
                    validated = validate_zone_payload(parsed, zone, 1, *word_budget)
                except ValueError as exc:
                    message = str(exc)
                    code = (
                        "S164_SEGMENT_UNDER_BUDGET"
                        if "below its word budget" in message
                        else "S165_SEGMENT_OVER_BUDGET"
                        if "exceeds its word budget" in message
                        else "S162_ZONE_GENERATION_FAILURE"
                    )
                    actual_words = _generated_segment_word_count(parsed)
                    raise _SegmentRejection(
                        code,
                        message,
                        actual_words=actual_words,
                        rejected_text=_generated_segment_text(parsed),
                    ) from exc
                candidate_text = str(validated["items"][0]["text"])
                try:
                    validate_generated_segment_language(candidate_text, language)
                except Stage1Error as exc:
                    raise _SegmentRejection(
                        exc.code,
                        str(exc),
                        actual_words=unicode_word_count(candidate_text),
                        rejected_text=candidate_text,
                    ) from exc
                normalized_text = normalized_story_text(candidate_text)
                for prior_digest, prior_text in prior_segments:
                    if prior_text == normalized_text or is_repetitive_story_text(
                        candidate_text, prior_text
                    ):
                        raise _SegmentRejection(
                            "S166_SEGMENT_DUPLICATE",
                            "segment text duplicates or closely paraphrases a committed story segment",
                            prior_digest,
                            duplicate_text=normalized_text,
                            rejected_text=candidate_text,
                        )
                digest = response_digest
                self.kernel.record_gate(
                    stage_id,
                    artifact,
                    f"STAGE1_ZONE_{zone}_CHECKPOINT",
                    DetectorClass.DETERMINISTIC,
                    GateStatus.PASS,
                    {
                        "zone": zone,
                        "item_index": item_index,
                        "segment_index": segment_index,
                        "minimum_words": word_budget[0],
                        "maximum_words": word_budget[1],
                        "json_schema_sha256": schema_digest,
                        "prompt_context_sha256": context_digest,
                        "seed": active_request.seed,
                        "temperature": active_request.temperature,
                        "top_p": active_request.top_p,
                        "segment_schema_version": SEGMENT_SCHEMA_VERSION,
                        "text_character_bounds": [
                            SEGMENT_TEXT_MIN_CHARACTERS,
                            _segment_text_max_characters(word_budget),
                        ],
                        "response_digest": digest,
                    },
                    sha256_bytes(self.canonical_path.read_bytes()),
                    capsule.digest,
                    "M5P-ZONE-1.0",
                    capsule.digest,
                )
                self.kernel.finish_generation_call(
                    call_id,
                    CallStatus.FINISHED,
                    digest,
                    model_identity=response.model_identity,
                    adapter_version=response.adapter_version,
                    duration_ms=response.duration_ms,
                    termination_reason=str(response.termination_reason),
                )
                self.kernel.commit_artifact(transaction, artifact)
                return cast(OrderedObject, validated["items"][0])
            except Exception as exc:
                last_error = exc
                retry_feedback = _segment_retry_feedback(
                    exc, word_budget=word_budget, target_words=target_words, language=language
                )
                self.kernel.finish_generation_call(
                    call_id,
                    CallStatus.FAILED,
                    response_digest,
                    failure_code=(
                        exc.code
                        if isinstance(exc, _SegmentRejection)
                        else "S162_ZONE_GENERATION_FAILURE"
                    ),
                    termination_reason=(
                        exc.detail if isinstance(exc, _SegmentRejection) else type(exc).__name__
                    ),
                )
        raise Stage1Error(
            "S163_ZONE_RETRY_EXHAUSTED", "local zone generation retry budget exhausted", zone
        ) from last_error

    def _boundary(self, name: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(name)

    def _capsule(self, contract: ProfileContract) -> PromptCapsule:
        source = self.canonical_path.read_bytes()
        parsed = parse_prompt(source)
        compiled = compile_capsule(
            parsed, CompileRequest(Stage.STAGE1, contract.profile, Route.CREATE)
        )
        return PromptCapsule(compiled.canonical_bytes, compiled.digest)


class _SegmentRejection(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        detail: str | None = None,
        *,
        actual_words: int | None = None,
        duplicate_text: str | None = None,
        rejected_text: str | None = None,
    ) -> None:
        self.code = code
        self.detail = detail or message
        self.actual_words = actual_words
        self.duplicate_text = duplicate_text
        self.rejected_text = rejected_text
        super().__init__(message)


def _generated_segment_word_count(value: Any) -> int | None:
    """Return a diagnostic word count only after the response has a segment-shaped body."""
    text = _generated_segment_text(value)
    return None if text is None else unicode_word_count(text)


def _generated_segment_text(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    items = value.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], Mapping):
        return None
    text = items[0].get("text")
    if not isinstance(text, str):
        return None
    return text


def _segment_retry_feedback(
    exc: Exception, *, word_budget: tuple[int, int], target_words: int, language: str
) -> str:
    correction = f"Write exactly {target_words} Unicode words"
    if isinstance(exc, _SegmentRejection) and exc.actual_words is not None:
        delta = target_words - exc.actual_words
        if delta > 0:
            correction = (
                f"The rejected text had {exc.actual_words} Unicode words. Add exactly {delta} "
                f"words so the replacement has exactly {target_words} Unicode words"
            )
        elif delta < 0:
            correction = (
                f"The rejected text had {exc.actual_words} Unicode words. Remove exactly {-delta} "
                f"words so the replacement has exactly {target_words} Unicode words"
            )
    if isinstance(exc, _SegmentRejection) and exc.code == "S166_SEGMENT_DUPLICATE":
        return (
            "\nRetry correction: the previous candidate duplicated an already committed segment. "
            "Do not restate any earlier sentence. Write a different event with a different opening "
            f"sentence and exactly {target_words} Unicode words. Use this required sentence shape: "
            "[character] [new concrete action] [specific object, person, or clue] [new immediate "
            "consequence]. The main predicate must be an action, decision, discovery, or interaction, "
            "not merely arrival, description, weather, lighting, or memory. Count only the text field's "
            "Unicode words before returning JSON."
        )
    if isinstance(exc, _SegmentRejection) and exc.code == "S167_LANGUAGE_MISMATCH":
        return (
            "\nRetry correction: the rejected text used the wrong language or writing system. "
            + _language_instruction(language)
            + " "
            f"Write exactly {target_words} Unicode words and return JSON only."
        )
    if isinstance(exc, _SegmentRejection) and exc.rejected_text is not None:
        return (
            "\nRetry correction: revise this exact rejected text rather than starting over: "
            f"{exc.rejected_text}\n{correction}. Keep the same story event, make the final "
            "character a supported sentence terminator (., !, ?, 。, ！, or ？), and keep the resulting "
            f"text within {word_budget[0]}–{word_budget[1]} Unicode words. Count only the "
            "text field's Unicode words before returning JSON."
        )
    return (
        "\nRetry correction: return fresh prose that is not identical to any earlier segment. "
        f"{correction}; the deterministic {word_budget[0]}–{word_budget[1]} word gate must pass. "
        "Count only the text field's Unicode words before returning the JSON."
    )


PRODUCTION_PHASE_ROOT_ORDER = ("schema_version", "phase", "status", "payload")
PRODUCTION_PHASE_PAYLOAD_ORDERS = {
    "plan": ("premise", "beats"),
    "draft": ("script",),
    "review": ("verdict", "findings"),
    "repair": ("script", "resolved_findings"),
    "serialize": ("story",),
}
PRODUCTION_STORY_BLUEPRINT_ORDER = ("title", "characters", "outline", "script")
PRODUCTION_CHARACTER_ORDER = ("character_id", "name", "age", "role", "description")
PRODUCTION_OUTLINE_ORDER = tuple(zone.lower() for zone in ZONE_ORDER)
PRODUCTION_SCRIPT_ITEM_ORDER = (
    "zone",
    "environment",
    "voice",
    "speed",
    "lang",
    "text",
)
SEGMENT_SCHEMA_VERSION = "M5P-SEGMENT-SCHEMA-1.3"
SEGMENT_TEXT_MIN_CHARACTERS = 1


def _segment_text_max_characters(word_budget: tuple[int, int]) -> int:
    return max(230, word_budget[1] * 10)


def _zone_item_counts(item_count: int) -> dict[str, int]:
    """Distribute the profile minimum across canonical zones without ambiguity."""
    quotient, remainder = divmod(item_count, len(ZONE_ORDER))
    return {
        zone: quotient + (1 if index < remainder else 0) for index, zone in enumerate(ZONE_ORDER)
    }


def _zone_word_budgets(contract: ProfileContract) -> dict[str, tuple[int, int]]:
    minimum_total = contract.min_minutes * contract.target_wpm
    maximum_total = contract.max_minutes * contract.target_wpm
    minimum, minimum_remainder = divmod(minimum_total, len(ZONE_ORDER))
    maximum, maximum_remainder = divmod(maximum_total, len(ZONE_ORDER))
    return {
        zone: (
            minimum + (1 if index < minimum_remainder else 0),
            maximum + (1 if index < maximum_remainder else 0),
        )
        for index, zone in enumerate(ZONE_ORDER)
    }


def _build_story_bible(plan: OrderedObject, language: str) -> str:
    """Project the validated plan into a compact, zone-addressable continuity contract."""
    payload = plan["payload"]
    assert isinstance(payload, Mapping)
    premise = str(payload["premise"])
    beats = [str(beat) for beat in payload["beats"]]
    # A weak local plan can contain only one beat. Repeating that same beat
    # under every zone taught the writer to rephrase one scene for the entire
    # story. A supplied beat is authoritative for its own zone only; remaining
    # zones use their explicit canonical progression roles.
    zone_beats = "; ".join(
        f"{zone}: {beats[index]}"
        if index < len(beats)
        else f"{zone}: develop this zone's canonical progression role from the prior event"
        for index, zone in enumerate(ZONE_ORDER)
    )
    if language == "vi":
        return (
            "Sổ tay liên kết truyện (nguồn sự thật): tiền đề: "
            + premise
            + ". Mốc cần phát triển theo zone: "
            + zone_beats
            + ". Không được thay đổi tiền đề; chỉ được đưa chi tiết mới khi nó phục vụ mốc "
            "của zone hiện tại hoặc là hệ quả của đoạn trước.\n"
            + _narrative_architecture_instruction(language)
        )
    return (
        "Story bible (source of truth): premise: "
        + premise
        + ". Required zone beats: "
        + zone_beats
        + ". Do not change the premise; introduce a new detail only when it serves the current "
        "zone beat or follows from an earlier segment.\n"
        + _narrative_architecture_instruction(language)
    )


def _narrative_architecture_instruction(language: str) -> str:
    """State the non-negotiable causal spine for compact local story segments.

    This is a generation constraint, rather than an LLM quality score: the
    canonical prompt requires causality and consequence, but a small local
    model benefits from seeing that requirement beside every zone instruction.
    """
    if language == "vi":
        return (
            "Khế ước kịch tính: hãy viết như một biên kịch chuyên nghiệp, bằng hành động và "
            "hệ quả quan sát được, không bằng lời khẳng định chung chung. Nhân vật chính phải "
            "có một mong muốn cụ thể; OPENING tạo xáo trộn, INTRODUCTION làm rõ mục tiêu và điều "
            "có thể mất, DEVELOPMENT buộc ít nhất một nỗ lực gặp trở lực hoặc tạo hậu quả. CLIMAX "
            "phải là một lựa chọn không thể rút lại của nhân vật trước áp lực con người hay hoàn "
            "cảnh, có cái giá cụ thể. FALLING và ENDING phải cho thấy cái giá ấy còn để lại dấu vết "
            "và payoff cho chi tiết đã gieo; FAREWELL chỉ khép lại hình ảnh đã được kiếm được. Mỗi "
            "đoạn phải thay đổi ít nhất một trong: thông tin, quan hệ, lựa chọn, trở lực hoặc tình "
            "trạng; không lặp lại cảnh đến nơi, trang trí, hoài niệm hay bí ẩn mà không có hệ quả."
        )
    return (
        "Dramatic contract: write like a professional screenwriter through observable action and "
        "consequence, never generic reassurance. The protagonist needs a concrete want; OPENING "
        "creates the disruption, INTRODUCTION clarifies the goal and what may be lost, and "
        "DEVELOPMENT makes at least one attempt meet resistance or create a consequence. CLIMAX "
        "must be the protagonist's irreversible choice under human or situational pressure, with "
        "a concrete cost. FALLING and ENDING must preserve that cost and pay off an earlier setup; "
        "FAREWELL may only close on an image earned by the resolution. Every segment must change "
        "at least one of information, relationship, choice, obstacle, or state; do not repeat "
        "arrival, decoration, nostalgia, or a mystery without a consequence."
    )


def _segment_json_schema(
    word_budget: tuple[int, int], zone: str, item_index: int, segment_index: int
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "schema_version": {"const": "1.0"},
            "zone": {"const": zone},
            "status": {"const": "PASS"},
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {
                            "const": f"{zone.lower()}_{item_index:03d}_{segment_index:02d}"
                        },
                        "speaker_id": {"const": "narrator"},
                        "voice": {"const": "narrator"},
                        "speed": {"const": "1.0"},
                        "environment": {"type": "string", "minLength": 1},
                        "text": {
                            "type": "string",
                            "minLength": SEGMENT_TEXT_MIN_CHARACTERS,
                            "maxLength": _segment_text_max_characters(word_budget),
                        },
                    },
                    "required": list(ZONE_ITEM_ORDER),
                    "additionalProperties": False,
                },
            },
        },
        "required": list(ZONE_PAYLOAD_ORDER),
        "additionalProperties": False,
    }


def _production_zone_instruction(
    zone: str,
    expected_count: int,
    word_budget: tuple[int, int],
    upstream_outputs: tuple[bytes, ...],
    *,
    item_index: int | None = None,
    segment_index: int | None = None,
    forbidden_texts: tuple[str, ...] = (),
    language: str = "vi",
    story_bible: str = "",
) -> str:
    context = "\n".join(output.decode("utf-8") for output in upstream_outputs)
    minimum_per_item = word_budget[0] // expected_count
    maximum_per_item = (word_budget[1] + expected_count - 1) // expected_count
    target_words = (word_budget[0] + word_budget[1]) // 2
    instruction = (
        f"Write only segment {segment_index or 1} of item {item_index or 1} in the {zone} "
        "zone of the Stage 1 story offline. "
        "Return one JSON object "
        "with exactly these root fields in order: schema_version, zone, status, items. "
        f'Use schema_version "1.0", zone "{zone}", status "PASS", and exactly '
        f"{expected_count} items. The combined text of those items must contain between "
        f"{word_budget[0]} and {word_budget[1]} Unicode words inclusive. Every text must "
        f"contain between {minimum_per_item} and {maximum_per_item} Unicode words inclusive. "
        f"Aim for exactly {target_words} Unicode words. Count the words before returning the "
        "JSON. Each item must "
        "contain exactly these fields in order: "
        f"{', '.join(ZONE_ITEM_ORDER)}. Every item field must be a JSON string. Use a unique "
        'non-empty item_id, speaker_id "narrator", voice "narrator", speed "1.0", a '
        "non-empty environment, and complete prose sentences "
        "ending in punctuation. Continue the validated story context without adding fields:\n"
        + context
    )
    instruction += "\n" + _language_instruction(language)
    instruction += "\n" + _segment_novelty_instruction(
        zone, item_index or 1, segment_index or 1, language
    )
    instruction += "\n" + _segment_focus_instruction(
        zone, item_index or 1, segment_index or 1, language
    )
    if story_bible:
        instruction += "\n" + story_bible
    if forbidden_texts:
        instruction += (
            "\nThere are "
            + str(len(forbidden_texts))
            + " committed segments before this one. Their prose is deliberately withheld to prevent "
            "copying it into the completion. Continue their causal thread with the next action or "
            "consequence; do not repeat or closely paraphrase any earlier event."
        )
    # Keep the constraints nearest the response boundary.  Long local context
    # and prior-segment lists otherwise make small local models lose the
    # selected-language and word-count requirements.
    instruction += (
        "\nFINAL HARD CONSTRAINTS: Return JSON only. "
        + _language_instruction(language)
        + f" The text field must contain {word_budget[0]}–{word_budget[1]} Unicode words. "
        "Count only text before responding."
    )
    return instruction


def _language_instruction(language: str) -> str:
    if language == "vi":
        return (
            "Language requirement: write every human-readable value, especially every text field, "
            "in natural Vietnamese with Vietnamese diacritics. Do not use Chinese, Japanese, Korean, "
            "or English prose."
        )
    return (
        "Language requirement: write every human-readable value, especially every text field, "
        "in natural English. Do not use Vietnamese, Chinese, Japanese, or Korean prose."
    )


def _segment_novelty_instruction(
    zone: str, item_index: int, segment_index: int, language: str, *, variation: int = 0
) -> str:
    """Return a zone-specific causal role without injecting unrelated plot events."""
    # A seed/temperature change alone did not make the local model leave a
    # repeated scenic sentence. Make the requested story move change too.
    cue_index = (item_index + segment_index + variation) % 6
    english_cues = (
        "use one concrete sensory detail already present in the setting",
        "show a small physical action that advances the current moment",
        "have the protagonist notice a specific relevant detail",
        "state a local decision, question, or intention",
        "show an immediate consequence of the preceding action",
        "add one grounded interaction with an established object or place",
    )
    vietnamese_cues = (
        "dùng một chi tiết giác quan cụ thể đã có trong bối cảnh",
        "thể hiện một hành động nhỏ đẩy khoảnh khắc hiện tại tiến lên",
        "để nhân vật chính nhận ra một chi tiết liên quan cụ thể",
        "nêu một quyết định, câu hỏi hoặc ý định tại chỗ",
        "cho thấy hậu quả tức thời của hành động ngay trước đó",
        "thêm một tương tác có cơ sở với đồ vật hoặc địa điểm đã được xác lập",
    )
    zone_actions = {
        "GREETING": "establish the protagonist, setting, and an ordinary immediate situation",
        "OPENING": "introduce one specific disruption that gives the protagonist a reason to act",
        "INTRODUCTION": "clarify the goal, stakes, or meaningful clue introduced by that disruption",
        "DEVELOPMENT": "show a concrete attempt, discovery, obstacle, or consequence that follows prior events",
        "CLIMAX": "make the decisive choice or confrontation that resolves the central problem",
        "FALLING": "show the immediate result of that decisive moment and settle remaining tension",
        "ENDING": "resolve the episode's main question with a changed situation or understanding",
        "FAREWELL": "leave a warm, earned closing image that follows from the resolution without opening a new plot",
    }
    if language == "vi":
        vietnamese_actions = {
            "GREETING": "giới thiệu nhân vật chính, bối cảnh và một tình huống bình thường trước mắt",
            "OPENING": "đưa vào một xáo trộn cụ thể khiến nhân vật chính phải hành động",
            "INTRODUCTION": "làm rõ mục tiêu, hệ quả hoặc manh mối quan trọng của xáo trộn đó",
            "DEVELOPMENT": "thể hiện một nỗ lực, phát hiện, trở ngại hoặc hậu quả cụ thể từ các sự kiện trước",
            "CLIMAX": "đặt nhân vật trước lựa chọn hay đối đầu quyết định để giải quyết vấn đề trung tâm",
            "FALLING": "cho thấy kết quả trực tiếp của khoảnh khắc quyết định và hạ nhiệt căng thẳng còn lại",
            "ENDING": "khép lại câu hỏi chính bằng một tình huống hoặc nhận thức đã thay đổi",
            "FAREWELL": "để lại một hình ảnh kết thúc ấm áp, có được từ sự giải quyết, không mở một cốt truyện mới",
        }
        return (
            "Vai trò diễn tiến của zone này: "
            + vietnamese_actions[zone]
            + ". Mỗi segment phải nối trực tiếp "
            "với sự kiện ngay trước đó bằng nguyên nhân, quyết định, hậu quả hoặc thông tin mới; "
            "không được đổi bối cảnh hay đưa một bí ẩn không liên quan. Cue riêng của segment này: "
            + vietnamese_cues[cue_index]
            + "."
        )
    return (
        "This zone's progression role is to "
        + zone_actions[zone]
        + ". Each segment must directly connect "
        "to the preceding event through cause, decision, consequence, or new information; do not "
        "change setting or introduce an unrelated mystery. This segment's distinct cue: "
        + english_cues[cue_index]
        + "."
    )


def _segment_focus_instruction(
    zone: str, item_index: int, segment_index: int, language: str
) -> str:
    """Give each short local completion a concrete, non-repeating story focus."""
    ordinal = ZONE_ORDER.index(zone) * 100 + item_index * 10 + segment_index
    objects_vi = (
        "phong bì niêm kín",
        "chiếc chìa khóa đồng",
        "cuốn sổ tay cũ",
        "bức ảnh đã úa màu",
        "mảnh giấy gấp tư",
        "chiếc hộp gỗ nhỏ",
        "tấm biển trước cửa",
        "chiếc đồng hồ dừng kim",
        "bó hoa vừa được đặt xuống",
        "ngăn kéo khóa kín",
        "vết mực trên bàn",
        "chiếc ghế trống cạnh cửa sổ",
    )
    actions_vi = (
        "được nhân vật chính mở ra hoặc kiểm tra",
        "gợi ra một câu hỏi cụ thể",
        "làm nhân vật chính phải lựa chọn",
        "dẫn đến một hệ quả ngay lập tức",
        "được một nhân vật khác nhắc tới",
        "làm lộ ra một chi tiết mới",
        "thay đổi việc nhân vật chính định làm tiếp theo",
        "kết nối trực tiếp với sự kiện trước đó",
        "tạo ra một trở ngại nhỏ nhưng rõ ràng",
        "giúp nhân vật chính tiến thêm một bước",
    )
    object_vi = objects_vi[ordinal % len(objects_vi)]
    action_vi = actions_vi[(ordinal // len(objects_vi)) % len(actions_vi)]
    if language == "vi":
        return (
            "Tiêu điểm bắt buộc, khác các segment khác: "
            f"{object_vi} {action_vi}. Hãy đưa tiêu điểm này vào hành động chính của text, "
            "không chỉ liệt kê hay miêu tả nó."
        )
    return (
        "Required distinct focus: use a specific object, clue, person, or decision that changes "
        "the current situation. Put it in the text's main action, not a background description."
    )


def _production_phase_instruction(phase: str, upstream_outputs: tuple[bytes, ...]) -> str:
    payload_order = PRODUCTION_PHASE_PAYLOAD_ORDERS[phase]
    instruction = (
        f"Execute the Stage 1 {phase} phase offline. Return only one JSON object. "
        "Use exactly these root fields in this order: schema_version, phase, status, payload. "
        f'Use schema_version "1.0", phase "{phase}", and status "PASS". '
        f"Payload must contain exactly these fields in this order: {', '.join(payload_order)}. "
        "All listed payload fields must be non-empty. Arrays must contain at least one item."
    )
    if upstream_outputs:
        instruction += " Validated upstream phase outputs, in execution order:\n" + "\n".join(
            output.decode("utf-8") for output in upstream_outputs
        )
    if phase == "serialize":
        instruction += (
            " The story object must contain exactly title, characters, outline, script in that "
            "order. Each character must contain exactly character_id, name, age, role, "
            "description. Outline must contain the eight lowercase zone names in order. "
            "Each script item must contain exactly zone, environment, voice, speed, lang, text. "
            "Character IDs must be unique. Text must end with "
            "sentence punctuation, and the script must include every zone in this order: "
            + ", ".join(ZONE_ORDER)
            + ". Build the script in eight contiguous zone blocks in this exact order: "
            + ", ".join(ZONE_ORDER)
            + ". Each zone block must contain exactly five concise complete-sentence items, "
            + "for 40 items total. Use voice NARRATOR, speed NORMAL, environment none, "
            + "and lang matching uppercase meta.language. Keep every sentence relevant to the premise and do not "
            + "omit any required object or field."
        )
    return instruction


def _validate_production_phase(data: bytes, phase: str) -> OrderedObject:
    artifact_name = f"stage1_{phase}.json"
    parsed = parse_json_bytes(data, artifact_name, engine_generated=True).value
    validate_field_order(parsed, PRODUCTION_PHASE_ROOT_ORDER, artifact_name)
    assert isinstance(parsed, OrderedObject)
    if parsed["schema_version"] != "1.0":
        raise ValueError("production phase schema_version must be 1.0")
    if parsed["phase"] != phase:
        raise ValueError("production phase does not match transaction phase")
    if parsed["status"] != "PASS":
        raise ValueError("production phase status must be PASS")
    payload = parsed["payload"]
    validate_field_order(
        payload, PRODUCTION_PHASE_PAYLOAD_ORDERS[phase], artifact_name, "$.payload"
    )
    for key, value in payload.items():
        if isinstance(value, str) and value.strip():
            continue
        if isinstance(value, list) and value:
            continue
        if isinstance(value, OrderedObject) and value:
            continue
        raise ValueError(f"production phase payload field {key} must be non-empty")
    if phase == "serialize":
        _validate_story_blueprint(payload["story"], artifact_name)
    return parsed


def _validate_story_blueprint(value: Any, artifact_name: str) -> None:
    validate_field_order(value, PRODUCTION_STORY_BLUEPRINT_ORDER, artifact_name, "$.payload.story")
    assert isinstance(value, OrderedObject)
    if not isinstance(value["title"], str) or not value["title"].strip():
        raise ValueError("production story title must be non-empty")
    characters = value["characters"]
    if not isinstance(characters, list) or not characters:
        raise ValueError("production story characters must be non-empty")
    character_ids: set[str] = set()
    for index, character in enumerate(characters):
        path = f"$.payload.story.characters[{index}]"
        validate_field_order(character, PRODUCTION_CHARACTER_ORDER, artifact_name, path)
        assert isinstance(character, OrderedObject)
        character_id = character["character_id"]
        if (
            not isinstance(character_id, str)
            or not character_id.startswith("char_")
            or character_id in character_ids
        ):
            raise ValueError("production character IDs must be unique char_ identifiers")
        character_ids.add(character_id)
        if not isinstance(character["age"], int) or character["age"] <= 0:
            raise ValueError("production character age must be a positive integer")
        for key in ("name", "role", "description"):
            if not isinstance(character[key], str) or not character[key].strip():
                raise ValueError(f"production character {key} must be non-empty")
    outline = value["outline"]
    validate_field_order(
        outline, PRODUCTION_OUTLINE_ORDER, artifact_name, "$.payload.story.outline"
    )
    assert isinstance(outline, OrderedObject)
    if any(not isinstance(outline[key], str) or not outline[key].strip() for key in outline):
        raise ValueError("production outline fields must be non-empty strings")
    script = value["script"]
    if not isinstance(script, list) or not script:
        raise ValueError("production story script must be non-empty")
    zone_ranks: list[int] = []
    for index, item in enumerate(script):
        path = f"$.payload.story.script[{index}]"
        validate_field_order(item, PRODUCTION_SCRIPT_ITEM_ORDER, artifact_name, path)
        assert isinstance(item, OrderedObject)
        zone = item["zone"]
        if zone not in ZONE_ORDER:
            raise ValueError("production script zone is invalid")
        zone_ranks.append(ZONE_ORDER.index(zone))
        text = item["text"]
        if not isinstance(text, str) or not has_terminal_sentence_punctuation(text):
            raise ValueError("production script text must be a complete sentence")
        for key in ("voice", "speed", "environment", "lang"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"production script {key} must be non-empty")
        if item["voice"] not in {"NARRATOR", "MALE", "FEMALE"}:
            raise ValueError("production script voice is invalid")
        if item["speed"] not in {"SLOW", "NORMAL", "FAST"}:
            raise ValueError("production script speed is invalid")
        if item["environment"] not in SCRIPT_ENVIRONMENTS:
            raise ValueError("production script environment is invalid")
        if item["lang"] not in {"VI", "EN"}:
            raise ValueError("production script lang is invalid")
    if zone_ranks != sorted(zone_ranks) or set(zone_ranks) != set(range(len(ZONE_ORDER))):
        raise ValueError("production script must contain every zone in canonical order")


def _build_story(
    request: Stage1Request, contract: ProfileContract
) -> tuple[OrderedDict[str, Any], OrderedDict[str, bytes]]:
    assert request.duration_minutes is not None
    target_words = request.duration_minutes * contract.target_wpm
    item_count = contract.min_script_items
    zones = [
        ZONE
        for ZONE in (
            "GREETING",
            "OPENING",
            "INTRODUCTION",
            "DEVELOPMENT",
            "CLIMAX",
            "FALLING",
            "ENDING",
            "FAREWELL",
        )
    ]
    per_item = target_words // item_count
    remainder = target_words % item_count
    script = []
    for index in range(item_count):
        zone = zones[min(index * len(zones) // item_count, len(zones) - 1)]
        count = per_item + (1 if index < remainder else 0)
        words = ["câu", str(index + 1)] + ["chuyện"] * max(0, count - 2)
        script.append(
            OrderedDict(
                zone=zone,
                environment="none",
                voice="NARRATOR",
                speed="NORMAL",
                lang=request.language.upper(),
                text=" ".join(words) + ".",
            )
        )
    assets: OrderedDict[str, bytes] = OrderedDict()
    characters = []
    for ordinal, (cid, name) in enumerate((("char_001", "An"), ("char_002", "Bình")), 1):
        path = f"characters/{cid}.png"
        data = mock_character_png(cid, request.seed)
        assets[path] = data
        characters.append(
            OrderedDict(
                character_id=cid,
                name=name,
                age=12 if contract.profile.value == "YOUTH_SAFE" else 30 + ordinal,
                role="protagonist" if ordinal == 1 else "supporting",
                description=f"Nhân vật {name} có nhận diện ổn định.",
                reference_asset=OrderedDict(
                    schema_version="1.0",
                    reference_image=path,
                    file_sha256=sha256_bytes(data),
                    pixel_sha256=sha256_bytes(data),
                    dimensions=OrderedDict(width=1536, height=2048),
                    identity_lock=f"identity:{cid}",
                    validation_status="PASS",
                ),
            )
        )
    commitment: OrderedDict[str, Any] = OrderedDict(
        schema_version="1.1",
        created_by_prompt_version=PROMPT_VERSION,
        minimum_verifier_version="3.11.9",
        final_script_text_digest_sha256=final_script_digest(script),
        recomputable_metrics=OrderedDict(
            total_words=word_count(script),
            estimated_duration_minutes=word_count(script) / contract.target_wpm,
            script_item_count=len(script),
            narrative_scene_count=6,
            direct_dialogue_item_count=0,
            direct_dialogue_ratio=0.0,
            opening_curiosity_seconds=30,
            audience_question_open_count=1,
            audience_question_overdue_count=0,
        ),
        recomputable_metrics_digest_sha256="",
        committed_quality_metrics=OrderedDict(
            final_story_quality_score=9,
            progression_score=9,
            engagement_score=9,
            quality_dimension_scores=[2] * 8,
        ),
        committed_quality_metrics_digest_sha256="",
        portable_gate_records=[],
        planning_claims=OrderedDict(
            story_intent={"status": "PASS"},
            causal_architecture={"status": "PASS"},
            engagement_design={"status": "PASS"},
            refinement_closure={"status": "PASS"},
            evidence_graph_digest_sha256="0" * 64,
        ),
        planning_claims_digest_sha256="",
        stage1_validation_status="PASS",
        commitment_digest_sha256=None,
    )
    for key, source in (
        ("recomputable_metrics_digest_sha256", commitment["recomputable_metrics"]),
        ("committed_quality_metrics_digest_sha256", commitment["committed_quality_metrics"]),
        ("planning_claims_digest_sha256", commitment["planning_claims"]),
    ):
        commitment[key] = sha256_bytes(canonical_json_bytes(source))
    commitment["commitment_digest_sha256"] = sha256_bytes(canonical_json_bytes(commitment))
    story = OrderedDict(
        schema_version="2.3",
        meta=OrderedDict(
            title=request.title,
            series=request.series or request.title,
            episode=request.episode,
            author="Katarina",
            channel=contract.channel,
            target=contract.audience,
            length_min=contract.min_minutes,
            length_max=contract.max_minutes,
            language=request.language,
            genre=contract.genre,
            audience=contract.audience,
            tone="ấm áp, rõ ràng",
            tags=[
                "audio",
                "story",
                "offline",
                "stage1",
                "deterministic",
                contract.profile.value.lower(),
            ],
            story_quality_commitment=commitment,
        ),
        characters=characters,
        outline=OrderedDict(
            (zone.lower(), f"{zone.title()}: một lựa chọn nhỏ tạo hậu quả có ý nghĩa.")
            for zone in ZONE_ORDER
        ),
        script=script,
    )
    return story, assets


def _config_digest(request: Stage1Request, contract: ProfileContract) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "profile": contract.profile,
                "language": request.language,
                "duration_minutes": request.duration_minutes,
                "duration_confirmed": request.duration_confirmed,
                "seed": request.seed,
                "title": request.title,
                "series": request.series,
                "episode": request.episode,
                "creative_input": request.creative_input,
                "target_wpm": contract.target_wpm,
            }
        )
    )


def _build_report(
    story: dict[str, Any],
    story_bytes: bytes,
    assets: OrderedDict[str, bytes],
    contract: ProfileContract,
    quality_evidence: dict[str, Any] | None = None,
) -> OrderedDict[str, Any]:
    script = story["script"]
    story_digest = sha256_bytes(story_bytes)
    content_digest = sha256_bytes(canonical_json_bytes(story_content_projection(story)))
    evidence = sha256_bytes(canonical_json_bytes({"story": story_digest, "capsule": "bound"}))
    gate = OrderedDict(
        gate_id="PRE-SERIALIZE-SCRIPT-ENUM-VALIDATION-01",
        severity="PUBLISH_BLOCKER",
        status="PASS",
        detector_method="deterministic_stage1_v1",
        evidence_id="evidence_script_enum",
        validation_digest_sha256=evidence,
        evidence_locators=["$.script"],
        metrics=OrderedDict(
            scanned_item_count=len(script),
            expected_item_count=len(script),
            invalid_item_count=0,
            violation_count=0,
            violations=[],
        ),
        failure_reason=None,
    )
    quality_method = (
        "independent local semantic evidence bound to final script and character assets"
        if quality_evidence is not None
        else "mock semantic evidence bound to final digest"
    )
    quality_score = (
        quality_evidence["quality"]["final_story_quality_score"]
        if quality_evidence is not None
        else 9
    )
    progression_score = (
        quality_evidence["quality"]["progression_score"] if quality_evidence is not None else 9
    )
    engagement_score = (
        quality_evidence["engagement"]["engagement_score"] if quality_evidence is not None else 9
    )
    quality_dimensions = (
        list(quality_evidence["quality"]["dimension_scores"])
        if quality_evidence is not None
        else [2] * 8
    )
    engagement_dimensions = (
        list(quality_evidence["engagement"]["dimension_scores"])
        if quality_evidence is not None
        else [2] * 5
    )
    return OrderedDict(
        schema_version="2.3",
        prompt_version=PROMPT_VERSION,
        story_sha256=story_digest,
        story_content_digest_sha256=content_digest,
        character_reference_set_digest_sha256=character_set_digest(story, assets),
        story_quality_commitment_digest_sha256=story["meta"]["story_quality_commitment"][
            "commitment_digest_sha256"
        ],
        active_profile=contract.profile,
        summary=OrderedDict(
            total_words=word_count(script),
            estimated_duration_minutes=word_count(script) / contract.target_wpm,
            script_item_count=len(script),
            narrative_scene_count=6,
            material_delta_count=6,
            direct_dialogue_item_count=0,
            material_defect_remaining_count=0,
        ),
        scene_zone_map=[
            OrderedDict(
                scene_id=f"scene_{i + 1:04d}",
                zones=[zone],
                item_start=i,
                item_end=i,
                entry_state_digest="0" * 64,
                exit_state_digest="1" * 64,
                material_delta_ids=[f"delta_{i + 1}"],
                scene_quality_score=9,
            )
            for i, zone in enumerate(
                ("OPENING", "INTRODUCTION", "DEVELOPMENT", "CLIMAX", "FALLING", "ENDING")
            )
        ],
        dialogue_audio=OrderedDict(
            actual_direct_dialogue_ratio=0.0,
            dialogue_scene_ratio=0.0,
            same_voice_owner_switch_count=0,
            same_voice_owner_switch_ambiguity_count=0,
            fake_quoted_dialogue_count=0,
            narrator_restatement_count=0,
            cadence_plateau_count=0,
            locators=[],
        ),
        quality=OrderedDict(
            dimension_scores=quality_dimensions,
            quality_raw_score=sum(quality_dimensions),
            final_story_quality_score=quality_score,
            progression_score=progression_score,
            scoring_method=quality_method,
            evidence_locators=["$.script"],
        ),
        engagement=OrderedDict(
            dimension_scores=engagement_dimensions,
            engagement_raw_score=sum(engagement_dimensions),
            engagement_score=engagement_score,
            opening_curiosity_seconds=30,
            audience_question_open_count=1,
            audience_question_overdue_count=0,
            flat_scene_count=0,
            information_only_reveal_count=0,
            engagement_cold_reader_status="PASS",
            scoring_method=quality_method,
            evidence_locators=["$.script"],
        ),
        gates=[gate],
        refinement=OrderedDict(
            pre_refinement_script_digest=final_script_digest(script),
            refinement_status="NO_REFINEMENT_REQUIRED",
            refinement_round_count=0,
            defect_map=[],
            defect_closure_records=[],
            final_script_text_digest=final_script_digest(script),
        ),
        evidence_graph=OrderedDict(
            schema_version="1.0",
            story_sha256=story_digest,
            nodes=[OrderedDict(evidence_id="evidence_script_enum", digest=evidence, status="PASS")],
            edges=[],
            stale_node_count=0,
        ),
    )
