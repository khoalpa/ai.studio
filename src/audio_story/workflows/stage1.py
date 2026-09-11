"""M5 Stage 1 vertical-slice application service."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

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
from audio_story.validation.stage1 import (
    final_script_digest,
    ordered_json_bytes,
    story_content_projection,
    validate_character_assets,
    validate_report_bytes,
    validate_story_bytes,
    word_count,
)
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.recovery import recover
from audio_story.workflows.stage1_package import (
    PROMPT_VERSION,
    build_manifest,
    build_series_anchor,
    build_story_zip,
    character_set_digest,
    mock_character_png,
)


class Stage1Service:
    """Run Stage 1 with M1 capsule, M3 lineage and an M4 local adapter."""

    def __init__(
        self,
        kernel: WorkflowKernel,
        adapter: LocalLLMAdapter,
        canonical_path: Path,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.kernel = kernel
        self.adapter = adapter
        self.canonical_path = canonical_path
        self.fault_hook = fault_hook

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
        return self._execute(workflow_id, stage_id, request, contract, capsule)

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
        if not request.test_mode:
            return Stage1Result(
                Stage1Status.WAITING_DEPENDENCY,
                workflow_id,
                stage_id,
                reason_code="S143_TEST_ASSET_PRODUCTION_PATH",
            )
        stage_status = self.kernel.db.connection.execute(
            "SELECT status FROM stage_runs WHERE id=?", (stage_id,)
        ).fetchone()[0]
        if stage_status == StageStatus.PREFLIGHT:
            self.kernel.transition_stage(stage_id, StageStatus.GENERATING)
        for phase in ("plan", "draft", "review", "repair", "serialize"):
            self._call_phase(stage_id, phase, capsule, request.seed)
            self._boundary(f"after_{phase}")
        story, assets = _build_story(request, contract)
        self._boundary("after_final_integrity")
        validate_character_assets(story, assets, test_mode=request.test_mode)
        story_bytes = ordered_json_bytes(story)
        pending = self.kernel.workspace / "outputs" / workflow_id / ".pending"
        pending.mkdir(parents=True, exist_ok=True)
        (pending / "story.json").write_bytes(story_bytes)
        self._boundary("after_story_write")
        parsed_story = validate_story_bytes(story_bytes, contract)
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

    def _finish(
        self, workflow_id: str, stage_id: str, output: Path, package_digest: str
    ) -> Stage1Result:
        self.kernel.transition_stage(stage_id, StageStatus.VALIDATING)
        self.kernel.transition_stage(stage_id, StageStatus.PACKAGING)
        self.kernel.transition_stage(stage_id, StageStatus.PASS)
        self.kernel.transition_workflow(workflow_id, WorkflowStatus.COMPLETED)
        return Stage1Result(Stage1Status.PASS, workflow_id, stage_id, output, package_digest)

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

    def _call_phase(self, stage_id: str, phase: str, capsule: PromptCapsule, seed: int) -> None:
        transaction = self.kernel.get_or_create_transaction(stage_id, "TEXT", f"{phase}.json")
        status = self.kernel.db.connection.execute(
            "SELECT status FROM asset_transactions WHERE id=?", (transaction,)
        ).fetchone()[0]
        if status == TransactionStatus.COMMITTED:
            return
        instruction = f"STAGE1_{phase.upper()} digest-only bounded call"
        request = GenerationRequest(
            capsule,
            instruction,
            GenerationKind.TEXT,
            max_output_tokens=8192,
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
                if phase in {"review", "repair"}:
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
                    termination = response.termination_reason
                if phase in {"review", "repair"}:
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
                    {"phase": phase, "response_digest": response_digest},
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
                return
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
                item_id=f"item_{index + 1:04d}",
                zone=zone,
                speaker_id="NARRATOR",
                voice="narrator",
                speed="NORMAL",
                environment="none",
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
            series=request.title,
            episode="1",
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
            premise="Một lựa chọn nhỏ tạo hậu quả có ý nghĩa.",
            ending="Nhân vật chịu trách nhiệm và tiến về phía trước.",
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
                "target_wpm": contract.target_wpm,
            }
        )
    )


def _build_report(
    story: dict[str, Any],
    story_bytes: bytes,
    assets: OrderedDict[str, bytes],
    contract: ProfileContract,
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
            dimension_scores=[2] * 8,
            quality_raw_score=16,
            final_story_quality_score=9,
            progression_score=9,
            scoring_method="mock semantic evidence bound to final digest",
            evidence_locators=["$.script"],
        ),
        engagement=OrderedDict(
            dimension_scores=[2] * 5,
            engagement_raw_score=10,
            engagement_score=9,
            opening_curiosity_seconds=30,
            audience_question_open_count=1,
            audience_question_overdue_count=0,
            flat_scene_count=0,
            information_only_reveal_count=0,
            engagement_cold_reader_status="PASS",
            scoring_method="mock semantic evidence bound to final digest",
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
