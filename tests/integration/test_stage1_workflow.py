from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from audio_story.adapters.llm.base import LLMAdapterError
from audio_story.adapters.llm.mock import DeterministicMockAdapter
from audio_story.cli import main
from audio_story.domain.stage1 import Stage1Error, Stage1Request, Stage1Status
from audio_story.domain.stage2 import ZONE_IMAGE_BASENAMES, Stage2Error
from audio_story.validation.canonical import sha256_bytes
from audio_story.validation.stage1 import ZONE_ORDER
from audio_story.validation.stage2 import load_stage1_package
from audio_story.workflows import Stage1Service, WorkflowKernel
from audio_story.workflows.recovery import recover
from audio_story.workflows.stage2_planning import (
    build_stage2_zone_plan,
    compile_stage2_invocation,
    validate_stage2_invocation,
)


@pytest.fixture
def canonical_path() -> Path:
    return Path(__file__).parents[2] / "canonical" / "ChatGPT_prompt_v3.16.13.txt"


def _zone_response(
    zone: str, count: int, total_words: int | None = None, prefix: str = "raw"
) -> bytes:
    total_words = total_words or count * 5
    per_item, remainder = divmod(total_words, count)
    return json.dumps(
        {
            "schema_version": "1.0",
            "zone": zone,
            "status": "PASS",
            "items": [
                {
                    "item_id": f"{prefix}_{index + 1:03d}",
                    "speaker_id": "narrator",
                    "voice": "narrator",
                    "speed": "1.0",
                    "environment": "quiet room",
                    "text": " ".join(
                        [f"{prefix}Sentence{index + 1}"]
                        + ["story"] * (per_item + (1 if index < remainder else 0) - 1)
                    )
                    + ".",
                }
                for index in range(count)
            ],
        },
        separators=(",", ":"),
    ).encode()


def _item_responses(item_counts: list[int], word_totals: list[int]) -> list[bytes]:
    responses: list[bytes] = []
    for zone, count, total in zip(ZONE_ORDER, item_counts, word_totals, strict=True):
        per_item, remainder = divmod(total, count)
        for index in range(count):
            item_words = per_item + (1 if index < remainder else 0)
            per_segment, segment_remainder = divmod(item_words, 3)
            responses.extend(
                _zone_response(
                    zone,
                    1,
                    per_segment + (1 if segment < segment_remainder else 0),
                    f"{zone.lower()}_{index + 1}_{segment + 1}",
                )
                for segment in range(3)
            )
    return responses


def test_stage2_intake_reopens_authoritative_stage1_package(tmp_path, canonical_path) -> None:
    kernel = WorkflowKernel(tmp_path)
    try:
        result = Stage1Service(kernel, DeterministicMockAdapter(), canonical_path).start(
            Stage1Request(
                "YOUTH_SAFE", duration_minutes=12, duration_confirmed=True, test_mode=True
            )
        )
        assert result.package_path is not None
        before = result.package_path.read_bytes()
        source = load_stage1_package(result.package_path, test_mode=True)
        assert source.package_digest_sha256 == sha256_bytes(before)
        assert source.manifest["package_stage"] == "STAGE1"
        assert source.manifest["active_profile"] == "YOUTH_SAFE"
        assert source.series_anchor_bytes is None
        assert result.package_path.read_bytes() == before
        plan = build_stage2_zone_plan(source)
        assert plan.packaging_basenames == ZONE_IMAGE_BASENAMES
        assert plan.execution_queue == ZONE_IMAGE_BASENAMES
        assert plan.identity_pilot_basename == "introduction.png"
        assert plan.calibration_basename == "opening.png"

        committed: list[str] = []
        for basename in plan.execution_queue:
            invocation = compile_stage2_invocation(plan, basename, committed_basenames=committed)
            assert invocation.target_basename == basename
            assert invocation.requested_output_count == 1
            expected_references = (
                ()
                if basename in {"greeting.png", "farewell.png", "outro.png"}
                else ("characters/char_001.png",)
            )
            assert invocation.explicit_references == expected_references
            committed.append(basename)

        first = compile_stage2_invocation(plan, "introduction.png")
        with pytest.raises(Stage2Error, match="M7B114_CARDINALITY"):
            validate_stage2_invocation(replace(first, requested_output_count=2), plan)
        with pytest.raises(Stage2Error, match="M7B101_QUEUE_ORDER"):
            compile_stage2_invocation(plan, "cover.png")
    finally:
        kernel.close()


@pytest.mark.parametrize(
    ("profile", "duration"),
    [("YOUTH_SAFE", 12), ("ADULT_STANDARD", 25), ("SERIAL_DETECTIVE", 35)],
)
def test_stage1_end_to_end_mock(tmp_path, canonical_path, profile: str, duration: int) -> None:
    kernel = WorkflowKernel(tmp_path / profile / "first")
    request = Stage1Request(
        profile, duration_minutes=duration, duration_confirmed=True, seed=7, test_mode=True
    )
    try:
        service = Stage1Service(kernel, DeterministicMockAdapter(), canonical_path)
        first = service.start(request)
        assert first.status is Stage1Status.PASS
        assert first.package_path is not None
        rows = kernel.db.connection.execute(
            "SELECT basename,COUNT(*) calls FROM asset_transactions t "
            "JOIN generation_calls g ON g.transaction_id=t.id "
            "WHERE t.stage_run_id=? GROUP BY basename ORDER BY basename",
            (first.stage_id,),
        ).fetchall()
        expected_basenames = {
            "plan.json",
            "draft.json",
            "review.json",
            "repair.json",
            "serialize.json",
            "story_validation.json",
            "workflow_manifest.json",
            "story.zip",
        }
        expected_basenames.add(
            "story-anchor-set.json" if profile == "SERIAL_DETECTIVE" else "story.json"
        )
        assert {row["basename"] for row in rows} == expected_basenames
        assert all(row["calls"] == 1 for row in rows)
        assert kernel.progress(first.stage_id) == (9, 9)
    finally:
        kernel.close()
    second_kernel = WorkflowKernel(tmp_path / profile / "second")
    try:
        second = Stage1Service(second_kernel, DeterministicMockAdapter(), canonical_path).start(
            request
        )
        assert second.status is Stage1Status.PASS
        assert second.package_path is not None
        with (
            zipfile.ZipFile(first.package_path) as left,
            zipfile.ZipFile(second.package_path) as right,
        ):
            assert left.namelist() == right.namelist()
            assert ("series_anchor.json" in left.namelist()) is (profile == "SERIAL_DETECTIVE")
            if profile == "SERIAL_DETECTIVE":
                assert left.namelist()[-1] == "series_anchor.json"
            assert [left.read(name) for name in left.namelist()] == [
                right.read(name) for name in right.namelist()
            ]
    finally:
        second_kernel.close()


def test_duration_wait_and_resume_reuses_workflow(tmp_path, canonical_path) -> None:
    kernel = WorkflowKernel(tmp_path)
    try:
        service = Stage1Service(kernel, DeterministicMockAdapter(), canonical_path)
        waiting = service.start(Stage1Request("YOUTH_SAFE"))
        assert waiting.status is Stage1Status.WAITING_INPUT
        before = kernel.db.connection.execute(
            "SELECT config_digest FROM workflow_runs WHERE id=?", (waiting.workflow_id,)
        ).fetchone()[0]
        resumed = service.resume_duration(
            waiting.workflow_id,
            waiting.stage_id,
            Stage1Request(
                "YOUTH_SAFE", duration_minutes=12, duration_confirmed=True, test_mode=True
            ),
        )
        assert resumed.status is Stage1Status.PASS
        count = kernel.db.connection.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        assert count == 1
        after = kernel.db.connection.execute(
            "SELECT config_digest FROM workflow_runs WHERE id=?", (waiting.workflow_id,)
        ).fetchone()[0]
        assert before != after
    finally:
        kernel.close()


def test_production_path_commits_structured_phases_then_waits_for_m6(
    tmp_path, canonical_path
) -> None:
    kernel = WorkflowKernel(tmp_path)
    try:
        responses = [
            b'{"schema_version":"1.0","phase":"plan","status":"PASS","payload":{"premise":"p","beats":["b"]}}',
            b'{"schema_version":"1.0","phase":"draft","status":"PASS","payload":{"script":["s"]}}',
            b'{"schema_version":"1.0","phase":"review","status":"PASS","payload":{"verdict":"approved","findings":["none"]}}',
            b'{"schema_version":"1.0","phase":"repair","status":"PASS","payload":{"script":["s2"],"resolved_findings":["none"]}}',
        ] + _item_responses([8, 8, 8, 8, 7, 7, 7, 7], [688, 688, 688, 688, 687, 687, 687, 687])
        instructions: list[str] = []

        class RecordingAdapter(DeterministicMockAdapter):
            def generate_structured(self, request, cancellation):
                instructions.append(request.instruction)
                return super().generate_structured(request, cancellation)

        result = Stage1Service(kernel, RecordingAdapter(responses=responses), canonical_path).start(
            Stage1Request("ADULT_STANDARD", duration_minutes=25, duration_confirmed=True)
        )
        assert result.status is Stage1Status.WAITING_DEPENDENCY
        assert result.package_path is None
        assert result.reason_code == "S144_CHARACTER_REFERENCE_PRODUCTION_REQUIRED"
        rows = kernel.db.connection.execute(
            "SELECT basename,status FROM asset_transactions"
        ).fetchall()
        assert {(row["basename"], row["status"]) for row in rows} == {
            (f"{phase}.json", "COMMITTED") for phase in ("plan", "draft", "review", "repair")
        } | {
            (f"segment-{zone.lower()}-{item + 1:03d}-{segment + 1:02d}.json", "COMMITTED")
            for zone_index, zone in enumerate(ZONE_ORDER)
            for item in range(8 if zone_index < 4 else 7)
            for segment in range(3)
        } | {("serialize.json", "COMMITTED")}
        assert (
            kernel.db.connection.execute(
                "SELECT COUNT(*) FROM gate_results WHERE gate_id LIKE 'STAGE1_%_CHECKPOINT' "
                "AND status='PASS'"
            ).fetchone()[0]
            == 184
        )
        for index, instruction in enumerate(instructions[:4]):
            for upstream in responses[:index]:
                assert upstream.decode("utf-8") in instruction
        for instruction in instructions[4:]:
            for upstream in responses[:4]:
                assert upstream.decode("utf-8") in instruction
            assert 'speed "1.0"' in instruction
            assert "Every item field must be a JSON string" in instruction
        evidence = kernel.db.connection.execute(
            "SELECT evidence_json FROM gate_results "
            "WHERE gate_id='STAGE1_ZONE_GREETING_CHECKPOINT' LIMIT 1"
        ).fetchone()[0]
        assert '"segment_schema_version":"M5P-SEGMENT-SCHEMA-1.2"' in evidence
        assert '"text_character_bounds":[120,230]' in evidence
    finally:
        kernel.close()


def test_production_phase_invalid_field_order_never_commits(tmp_path, canonical_path) -> None:
    kernel = WorkflowKernel(tmp_path)
    try:
        invalid = (
            b'{"phase":"plan","schema_version":"1.0","status":"PASS",'
            b'"payload":{"premise":"p","beats":["b"]}}'
        )
        with pytest.raises(Stage1Error, match="S111_RETRY_EXHAUSTED"):
            Stage1Service(
                kernel,
                DeterministicMockAdapter(responses=[invalid, invalid]),
                canonical_path,
            ).start(Stage1Request("ADULT_STANDARD", duration_minutes=25, duration_confirmed=True))
        assert (
            kernel.db.connection.execute("SELECT COUNT(*) FROM artifact_bindings").fetchone()[0]
            == 0
        )
    finally:
        kernel.close()


def test_production_invalid_zone_never_commits_or_serializes(tmp_path, canonical_path) -> None:
    kernel = WorkflowKernel(tmp_path)
    try:
        placeholder = (
            b'{"schema_version":"1.0","phase":"serialize","status":"PASS",'
            b'"payload":{"story":{"premise":"placeholder","beats":["placeholder"]}}}'
        )
        responses = [
            b'{"schema_version":"1.0","phase":"plan","status":"PASS","payload":{"premise":"p","beats":["b"]}}',
            b'{"schema_version":"1.0","phase":"draft","status":"PASS","payload":{"script":["s"]}}',
            b'{"schema_version":"1.0","phase":"review","status":"PASS","payload":{"verdict":"approved","findings":["none"]}}',
            b'{"schema_version":"1.0","phase":"repair","status":"PASS","payload":{"script":["s2"],"resolved_findings":["none"]}}',
            placeholder,
            placeholder,
        ]
        with pytest.raises(Stage1Error, match="S163_ZONE_RETRY_EXHAUSTED"):
            Stage1Service(
                kernel, DeterministicMockAdapter(responses=responses), canonical_path
            ).start(Stage1Request("ADULT_STANDARD", duration_minutes=25, duration_confirmed=True))
        greeting = kernel.db.connection.execute(
            "SELECT id,status FROM asset_transactions WHERE basename='segment-greeting-001-01.json'"
        ).fetchone()
        assert greeting["status"] == "FAILED_RETRYABLE"
        assert (
            kernel.db.connection.execute(
                "SELECT COUNT(*) FROM artifact_bindings WHERE transaction_id=?",
                (greeting["id"],),
            ).fetchone()[0]
            == 0
        )
        assert (
            kernel.db.connection.execute(
                "SELECT COUNT(*) FROM asset_transactions WHERE basename='serialize.json'"
            ).fetchone()[0]
            == 0
        )
    finally:
        kernel.close()


def test_production_zone_retry_reuses_transaction(tmp_path, canonical_path) -> None:
    kernel = WorkflowKernel(tmp_path)
    try:
        invalid = _zone_response("OPENING", 5)
        responses = [
            b'{"schema_version":"1.0","phase":"plan","status":"PASS","payload":{"premise":"p","beats":["b"]}}',
            b'{"schema_version":"1.0","phase":"draft","status":"PASS","payload":{"script":["s"]}}',
            b'{"schema_version":"1.0","phase":"review","status":"PASS","payload":{"verdict":"approved","findings":["none"]}}',
            b'{"schema_version":"1.0","phase":"repair","status":"PASS","payload":{"script":["s2"],"resolved_findings":["none"]}}',
            invalid,
        ] + _item_responses([5] * 8, [300] * 8)
        result = Stage1Service(
            kernel, DeterministicMockAdapter(responses=responses), canonical_path
        ).start(Stage1Request("YOUTH_SAFE", duration_minutes=12, duration_confirmed=True))
        assert result.reason_code == "S144_CHARACTER_REFERENCE_PRODUCTION_REQUIRED"
        rows = kernel.db.connection.execute(
            "SELECT t.id,g.id,g.attempt_index,g.status FROM asset_transactions t "
            "JOIN generation_calls g ON g.transaction_id=t.id "
            "WHERE t.basename='segment-greeting-001-01.json' ORDER BY g.attempt_index"
        ).fetchall()
        assert len({row["id"] for row in rows}) == 1
        assert [(row["attempt_index"], row["status"]) for row in rows] == [
            (1, "FAILED"),
            (2, "FINISHED"),
        ]
    finally:
        kernel.close()


def test_production_zone_resume_skips_committed_zones(tmp_path, canonical_path) -> None:
    root = tmp_path / "resume-zones"
    responses = [
        b'{"schema_version":"1.0","phase":"plan","status":"PASS","payload":{"premise":"p","beats":["b"]}}',
        b'{"schema_version":"1.0","phase":"draft","status":"PASS","payload":{"script":["s"]}}',
        b'{"schema_version":"1.0","phase":"review","status":"PASS","payload":{"verdict":"approved","findings":["none"]}}',
        b'{"schema_version":"1.0","phase":"repair","status":"PASS","payload":{"script":["s2"],"resolved_findings":["none"]}}',
    ] + _item_responses([5] * 8, [300] * 8)
    adapter = DeterministicMockAdapter(responses=responses)
    request = Stage1Request("YOUTH_SAFE", duration_minutes=12, duration_confirmed=True)
    first_kernel = WorkflowKernel(root)
    fired = False

    def crash(name: str) -> None:
        nonlocal fired
        if name == "after_zone_opening" and not fired:
            fired = True
            raise RuntimeError("simulated process interruption")

    try:
        service = Stage1Service(first_kernel, adapter, canonical_path, fault_hook=crash)
        with pytest.raises(RuntimeError, match="interruption"):
            service.start(request)
        workflow_id, stage_id = first_kernel.db.connection.execute(
            "SELECT w.id,s.id FROM workflow_runs w JOIN stage_runs s ON s.workflow_id=w.id"
        ).fetchone()
    finally:
        first_kernel.close()
    reopened = WorkflowKernel(root)
    try:
        result = Stage1Service(reopened, adapter, canonical_path).resume_recovery(
            workflow_id, stage_id, request
        )
        assert result.reason_code == "S144_CHARACTER_REFERENCE_PRODUCTION_REQUIRED"
        zone_rows = reopened.db.connection.execute(
            "SELECT t.basename,COUNT(g.id) calls FROM asset_transactions t "
            "JOIN generation_calls g ON g.transaction_id=t.id "
            "WHERE t.basename LIKE 'segment-%.json' GROUP BY t.basename"
        ).fetchall()
        assert len(zone_rows) == 120
        assert all(row["calls"] == 1 for row in zone_rows)
    finally:
        reopened.close()


def test_retry_reuses_transaction_and_changes_call_id(tmp_path, canonical_path) -> None:
    kernel = WorkflowKernel(tmp_path)
    try:
        adapter = DeterministicMockAdapter(
            failures=[LLMAdapterError("LLM003_TIMEOUT", "injected timeout")]
        )
        result = Stage1Service(kernel, adapter, canonical_path).start(
            Stage1Request(
                "YOUTH_SAFE", duration_minutes=12, duration_confirmed=True, test_mode=True
            )
        )
        assert result.status is Stage1Status.PASS
        rows = kernel.db.connection.execute(
            "SELECT t.id transaction_id,g.id call_id,g.attempt_index FROM asset_transactions t "
            "JOIN generation_calls g ON g.transaction_id=t.id WHERE t.basename='plan.json' "
            "ORDER BY g.attempt_index"
        ).fetchall()
        assert len({row["transaction_id"] for row in rows}) == 1
        assert len({row["call_id"] for row in rows}) == 2
        assert [row["attempt_index"] for row in rows] == [1, 2]
    finally:
        kernel.close()


def test_retry_exhaustion_never_publishes(tmp_path, canonical_path) -> None:
    kernel = WorkflowKernel(tmp_path)
    try:
        failures = [LLMAdapterError("LLM003_TIMEOUT", "timeout") for _ in range(2)]
        with pytest.raises(Exception, match="S111_RETRY_EXHAUSTED"):
            Stage1Service(
                kernel, DeterministicMockAdapter(failures=failures), canonical_path
            ).start(
                Stage1Request(
                    "YOUTH_SAFE", duration_minutes=12, duration_confirmed=True, test_mode=True
                )
            )
        assert (
            kernel.db.connection.execute("SELECT COUNT(*) FROM artifact_bindings").fetchone()[0]
            == 0
        )
    finally:
        kernel.close()


@pytest.mark.parametrize(
    "boundary",
    [
        "after_plan",
        "during_draft",
        "after_draft",
        "during_review",
        "during_repair",
        "after_repair",
        "after_final_integrity",
        "after_story_write",
        "after_story_binding",
        "after_report_write",
        "after_manifest_write",
        "after_zip_publish",
        "after_zip_binding",
    ],
)
def test_fresh_instance_recovery_matrix(tmp_path, canonical_path, boundary: str) -> None:
    root = tmp_path / boundary
    request = Stage1Request(
        "YOUTH_SAFE", duration_minutes=12, duration_confirmed=True, seed=11, test_mode=True
    )
    fired = False

    def crash(name: str) -> None:
        nonlocal fired
        if name == boundary and not fired:
            fired = True
            raise SystemExit(f"fault:{name}")

    first = WorkflowKernel(root)
    service = Stage1Service(first, DeterministicMockAdapter(), canonical_path, crash)
    with pytest.raises(SystemExit, match="fault:"):
        service.start(request)
    workflow_id = first.db.connection.execute("SELECT id FROM workflow_runs").fetchone()[0]
    stage_id = first.db.connection.execute("SELECT id FROM stage_runs").fetchone()[0]
    first.close()

    reopened = WorkflowKernel(root)
    result = Stage1Service(reopened, DeterministicMockAdapter(), canonical_path).resume_recovery(
        workflow_id, stage_id, request
    )
    assert result.status is Stage1Status.PASS
    assert reopened.progress(stage_id) == (9, 9)
    assert reopened.db.connection.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0] == 1
    assert reopened.db.connection.execute("SELECT COUNT(*) FROM stage_runs").fetchone()[0] == 1
    assert reopened.db.connection.execute(
        "SELECT COUNT(*)=COUNT(DISTINCT orientation||':'||basename) FROM asset_transactions"
    ).fetchone()[0]
    assert reopened.db.connection.execute(
        "SELECT COUNT(*)=COUNT(DISTINCT transaction_id||':'||role) FROM artifact_bindings"
    ).fetchone()[0]
    assert (
        reopened.db.connection.execute(
            "SELECT COUNT(*) FROM artifact_bindings b JOIN artifacts a ON a.id=b.artifact_id "
            "LEFT JOIN gate_results g ON g.artifact_id=a.id AND g.is_current=1 AND g.status='PASS' "
            "WHERE b.role='COMMITTED' AND g.id IS NULL"
        ).fetchone()[0]
        == 0
    )
    for row in reopened.db.connection.execute("SELECT relative_path,sha256 FROM artifacts"):
        assert sha256_bytes((root / row["relative_path"]).read_bytes()) == row["sha256"]
    assert (
        reopened.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='RESUME_COMPLETED'"
        ).fetchone()[0]
        >= 1
    )
    before = reopened.db.connection.execute("SELECT COUNT(*) FROM generation_calls").fetchone()[0]
    recover(reopened, workflow_id)
    assert (
        reopened.db.connection.execute("SELECT COUNT(*) FROM generation_calls").fetchone()[0]
        == before
    )
    reopened.close()


@pytest.mark.parametrize("phase", ["plan", "draft", "review", "repair", "serialize"])
def test_each_adapter_boundary_retries_without_lineage_drift(
    tmp_path, canonical_path, phase: str
) -> None:
    fired = False

    def fail_once(name: str) -> None:
        nonlocal fired
        if name == f"during_{phase}" and not fired:
            fired = True
            raise RuntimeError("injected adapter exception")

    kernel = WorkflowKernel(tmp_path)
    result = Stage1Service(kernel, DeterministicMockAdapter(), canonical_path, fail_once).start(
        Stage1Request("YOUTH_SAFE", duration_minutes=12, duration_confirmed=True, test_mode=True)
    )
    assert result.status is Stage1Status.PASS
    rows = kernel.db.connection.execute(
        "SELECT t.id,g.id,g.attempt_index FROM asset_transactions t JOIN generation_calls g "
        "ON g.transaction_id=t.id WHERE t.basename=? ORDER BY g.attempt_index",
        (f"{phase}.json",),
    ).fetchall()
    assert len(rows) == 2
    assert len({row[0] for row in rows}) == 1
    assert len({row[1] for row in rows}) == 2
    kernel.close()


def test_stage1_mock_cli_runs_application_path(tmp_path, canonical_path, capsys) -> None:
    assert (
        main(
            [
                "stage1-mock",
                "--workspace",
                str(tmp_path),
                "--canonical",
                str(canonical_path),
                "--profile",
                "YOUTH_SAFE",
                "--duration",
                "12",
                "--seed",
                "9",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PASS"
    assert Path(result["package_path"]).is_file()
    assert len(result["package_digest"]) == 64
