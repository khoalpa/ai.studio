from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from audio_story.adapters.image import (
    DeterministicMockImageAdapter,
    ImageAdapterError,
    ImageRequest,
    ImageResponse,
)
from audio_story.domain.stage3 import Stage3Error
from audio_story.domain.state import WorkflowStatus
from audio_story.validation.canonical import sha256_bytes
from audio_story.validation.stage3 import (
    QUALITY_DIMENSIONS,
    assert_inherited_bytes,
    load_stage2_package,
    serialize_package_quality_report,
    serialize_stage3_progress,
    validate_package_quality_report_bytes,
)
from audio_story.workflows.image_transaction import SemanticImageGateResult
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.stage3_execution import Stage3PortraitExecutor
from audio_story.workflows.stage3_package import build_stage3_package, publish_stage3_package
from audio_story.workflows.stage3_planning import (
    build_stage3_portrait_plan,
    compile_stage3_invocation,
    validate_stage3_invocation,
)

HASH = "a" * 64


def _component() -> OrderedDict[str, object]:
    return OrderedDict(
        component_id="component:test",
        component_weight=100,
        detector_output_key="detector:test",
        raw_score=100,
        score=100,
        status="PASS",
        applicability_code="APPLICABLE",
        measurement_digest_sha256=HASH,
        finding_ids=[],
        evidence_ids=["evidence:test"],
    )


def _report() -> OrderedDict[str, object]:
    registry_digest, asset_digest = "b" * 64, "c" * 64
    preimage = f"PACKAGE_QUALITY_REPORT|2.0|{registry_digest}|{asset_digest}"
    dimensions = [
        OrderedDict(
            dimension_id=name,
            score=100,
            quality_rating="EXCELLENT",
            status="PASS",
            applicability_code="APPLICABLE",
            coverage_ratio=1.0,
            components=[_component()],
            evidence_ids=["evidence:test"],
            findings=[],
            recommendations=[],
        )
        for name in QUALITY_DIMENSIONS
    ]
    return OrderedDict(
        schema_version="2.0",
        report_id="pqr_" + sha256_bytes(preimage.encode())[:24],
        generated_at_utc="2026-09-15T00:00:00Z",
        package_identity=OrderedDict(
            title="Test",
            active_profile="YOUTH_SAFE",
            story_sha256=HASH,
            story_quality_commitment_digest_sha256=HASH,
            character_set_digest_sha256=HASH,
            landscape_set_digest_sha256=HASH,
            portrait_set_digest_sha256=HASH,
            ordered_asset_manifest_digest_sha256=asset_digest,
        ),
        registry_bindings=OrderedDict(
            quality_component_registry_schema_version="2.0",
            quality_component_registry_digest_sha256=registry_digest,
            finding_taxonomy_registry_digest_sha256=HASH,
            penalty_profile_registry_digest_sha256=HASH,
            compatibility_adapter_registry_schema_version="1.1",
            compatibility_adapter_registry_digest_sha256=HASH,
            applied_adapter_id=None,
            applied_adapter_version=None,
            compatibility_evidence_digest_sha256=None,
            adapter_output_digest_sha256=None,
            excluded_component_ids=[],
        ),
        summary=OrderedDict(
            overall_score=100,
            quality_rating="EXCELLENT",
            publish_verdict="PASS",
            scoring_coverage_ratio=1.0,
            applicable_weight_sum=100,
            excluded_weight_sum=0,
            strengths=[],
            weaknesses=[],
        ),
        dimensions=dimensions,
        measurement_ledger=OrderedDict(schema_version="2.0", measurements=[], findings=[]),
        story_evidence=OrderedDict(),
        image_evidence=OrderedDict(
            asset_results=[],
            set_results=[],
            pair_results=[],
            cover_results=[],
            evidence_digest_sha256=HASH,
        ),
        blockers=[],
        recommendations=[],
        validation=OrderedDict(
            schema_status="PASS",
            field_order_status="PASS",
            artifact_binding_status="PASS",
            score_recompute_status="PASS",
            gate_reconciliation_status="PASS",
            report_digest_sha256=None,
            status="PASS",
        ),
    )


def test_package_quality_report_20_is_deterministic_and_strict() -> None:
    first = serialize_package_quality_report(_report())
    assert first == serialize_package_quality_report(_report())
    validate_package_quality_report_bytes(first)
    with pytest.raises(Exception, match="DJ012_FIELD_ORDER"):
        value = _report()
        value.move_to_end("schema_version")
        serialize_package_quality_report(value)
    with pytest.raises(Stage3Error, match="M8A102_DIMENSIONS"):
        value = _report()
        dimensions = value["dimensions"]
        assert isinstance(dimensions, list)
        dimensions.pop()
        serialize_package_quality_report(value)
    with pytest.raises(Stage3Error, match="M8A109_SCORE_RECOMPUTE"):
        value = _report()
        summary = value["summary"]
        assert isinstance(summary, dict)
        summary["overall_score"] = 99
        serialize_package_quality_report(value)


def test_authoritative_m7_package_intake_and_authority_map() -> None:
    archive = Path(__file__).parents[2] / "artifacts/m7-production-d26/story.zip"
    if not archive.exists():
        pytest.skip("local production checkpoint is absent")
    package = load_stage2_package(
        archive,
        expected_archive_sha256="47db5f8ae31364caafea37019d38f0aa8f7823936c3fc1bbac998f55e1ff4cd2",
    )
    assert len(package.inherited_authority) == 15
    assert len(package.portrait_paths) == 10
    assert len(package.final_package_file_set) == 27
    assert package.final_package_file_set[0] == "workflow_manifest.json"
    assert package.final_package_file_set[-1] == "package_quality_report.json"
    assert_inherited_bytes(package, package.members)
    changed = OrderedDict(package.members)
    changed["visual_bible.json"] += b" "
    with pytest.raises(Stage3Error, match="M8A031_INHERITED_MUTATION"):
        assert_inherited_bytes(package, changed)
    with pytest.raises(Stage3Error, match="M8A001_ARCHIVE_AUTHORITY"):
        load_stage2_package(archive, expected_archive_sha256=HASH)


def test_m8b_plan_pilot_firewall_and_progress_are_deterministic() -> None:
    archive = Path(__file__).parents[2] / "artifacts/m7-production-d26/story.zip"
    if not archive.exists():
        pytest.skip("local production checkpoint is absent")
    source = load_stage2_package(archive)
    plan = build_stage3_portrait_plan(source)
    assert plan == build_stage3_portrait_plan(source)
    assert len(plan.adaptation_plan) == 10
    assert all(item["landscape_sha256"] != HASH for item in plan.adaptation_plan)
    assert plan.pilot_evidence["winning_basename"] == "cover.png"
    assert plan.pilot_evidence["tie_breaker_used"] == "COVER_TYPOGRAPHY"
    invocation = compile_stage3_invocation(source, plan, "cover.png")
    assert invocation.explicit_references == (
        "landscape/cover.png",
        "characters/char_001.png",
    )
    with pytest.raises(Stage3Error, match="M8B100_QUEUE_ORDER"):
        compile_stage3_invocation(source, plan, "introduction.png")
    with pytest.raises(Stage3Error, match="M8B114_DIMENSIONS"):
        validate_stage3_invocation(source, plan, replace(invocation, requested_width=1920))
    with pytest.raises(Stage3Error, match="M8B113_CARDINALITY"):
        validate_stage3_invocation(source, plan, replace(invocation, requested_output_count=2))
    contaminated = OrderedDict(invocation.payload)
    contaminated["batch_requests"] = []
    with pytest.raises(Stage3Error, match="M8B115_PAYLOAD|M8B118_GLOBAL_CONTEXT"):
        validate_stage3_invocation(source, plan, replace(invocation, payload=contaminated))

    assets = [
        OrderedDict(
            basename=name,
            execution_index=index,
            packaging_index=plan.packaging_basenames.index(name) + 1,
            queue_status="PENDING",
            asset_source=None,
            file_path=None,
            file_sha256=None,
            transaction_id=None,
            postwrite_validation_status=None,
        )
        for index, name in enumerate(plan.execution_queue, 1)
    ]
    progress = OrderedDict(
        schema_version="1.0",
        bundle_kind="STAGE3",
        stage="STAGE3",
        orientation="PORTRAIT",
        original_operation_mode="CREATE",
        input_story_package_digest_sha256=source.package_digest_sha256,
        input_story_zip_sha256=source.archive_sha256,
        active_basename_set_digest_sha256=HASH,
        visual_plan_digest_sha256=source.visual_plan["visual_plan_digest_sha256"],
        visual_bible_availability="REQUIRED_PRESENT",
        visual_bible_digest_sha256=HASH,
        required_count=10,
        committed_count=0,
        pending_count=10,
        failed_count=0,
        assets=assets,
        last_committed_basename=None,
        next_pending_basename="cover.png",
        missing_assets=[f"portrait/{name}" for name in plan.packaging_basenames],
        status="IN_PROGRESS",
        progress_digest_sha256=None,
    )
    assert serialize_stage3_progress(progress) == serialize_stage3_progress(progress)
    assets[0]["basename"] = "opening.png"
    with pytest.raises(Stage3Error, match="M8B202_PROGRESS_ASSETS|M8B203_PROGRESS_ORDER"):
        serialize_stage3_progress(progress)


class _FailOpeningOnce(DeterministicMockImageAdapter):
    def __init__(self) -> None:
        self.failed = False

    def generate_image(self, request: ImageRequest, cancellation: Event) -> ImageResponse:
        if request.basename == "opening.png" and not self.failed:
            self.failed = True
            raise ImageAdapterError("IMG099_TEST_FAILURE", "targeted repair fixture")
        return super().generate_image(request, cancellation)


def test_m8c_mock_executes_pilot_once_and_repairs_only_failed_basename(tmp_path: Path) -> None:
    archive = Path(__file__).parents[2] / "artifacts/m7-production-d26/story.zip"
    if not archive.exists():
        pytest.skip("local production checkpoint is absent")
    source = load_stage2_package(archive)
    plan = build_stage3_portrait_plan(source)
    kernel = WorkflowKernel(tmp_path)
    try:
        workflow = kernel.create_workflow("YOUTH_SAFE", "STAGE3", "CREATE", HASH, HASH)
        kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
        stage = kernel.start_stage(workflow, "STAGE3", HASH)

        def semantic_pass(data: bytes, request: ImageRequest) -> SemanticImageGateResult:
            return SemanticImageGateResult(
                "PASS",
                {"image_sha256": sha256_bytes(data), "basename": request.basename},
                "TEST_ONLY",
                "M8C-TEST-1.0",
            )

        executor = Stage3PortraitExecutor(
            kernel, stage, source, plan, _FailOpeningOnce(), semantic_pass
        )
        completed = executor.execute_all()
        assert completed.status == "READY_FOR_AGGREGATE_GATES"
        assert completed.committed_count == 10
        rows = kernel.db.connection.execute(
            "SELECT basename FROM asset_transactions WHERE stage_run_id=? ORDER BY created_at",
            (stage,),
        ).fetchall()
        assert [row["basename"] for row in rows] == list(plan.execution_queue)
        assert [row["basename"] for row in rows].count("cover.png") == 1
        attempts = kernel.db.connection.execute(
            "SELECT COUNT(*) FROM generation_calls g JOIN asset_transactions t "
            "ON t.id=g.transaction_id WHERE t.stage_run_id=? AND t.basename='opening.png'",
            (stage,),
        ).fetchone()[0]
        assert attempts == 2
        first = build_stage3_package(kernel, stage, source, generated_at_utc="2026-09-15T00:00:00Z")
        second = build_stage3_package(
            kernel, stage, source, generated_at_utc="2026-09-15T00:00:00Z"
        )
        assert first.zip_bytes == second.zip_bytes
        published = publish_stage3_package(kernel, stage, first, "published/story.zip")
        resumed = publish_stage3_package(kernel, stage, second, "published/story.zip")
        assert published == resumed
        assert (tmp_path / "published/story.zip").read_bytes() == first.zip_bytes
        events = kernel.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_PUBLISHED'"
        ).fetchone()[0]
        assert events == 1
    finally:
        kernel.close()
