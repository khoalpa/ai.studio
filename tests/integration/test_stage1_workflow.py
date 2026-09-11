from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from audio_story.adapters.llm.base import LLMAdapterError
from audio_story.adapters.llm.mock import DeterministicMockAdapter
from audio_story.cli import main
from audio_story.domain.stage1 import Stage1Request, Stage1Status
from audio_story.validation.canonical import sha256_bytes
from audio_story.workflows import Stage1Service, WorkflowKernel
from audio_story.workflows.recovery import recover


@pytest.fixture
def canonical_path() -> Path:
    return Path(__file__).parents[2] / "canonical" / "ChatGPT_prompt_v3.16.13.txt"


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


def test_production_path_waits_for_m6(tmp_path, canonical_path) -> None:
    kernel = WorkflowKernel(tmp_path)
    try:
        result = Stage1Service(kernel, DeterministicMockAdapter(), canonical_path).start(
            Stage1Request("ADULT_STANDARD", duration_minutes=25, duration_confirmed=True)
        )
        assert result.status is Stage1Status.WAITING_DEPENDENCY
        assert result.package_path is None
        assert result.reason_code == "S143_TEST_ASSET_PRODUCTION_PATH"
    finally:
        kernel.close()


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
