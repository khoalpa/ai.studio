from __future__ import annotations

import io
import json
import threading
import time
import zipfile
from pathlib import Path

import pytest

from audio_story.adapters.image import ComfyUIImageAdapter
from audio_story.studio.commands import StudioCommandError, StudioCommandRunner, StudioJob
from audio_story.workflows import WorkflowKernel
from audio_story.workflows.kernel import utc_now

CANONICAL = Path("canonical/ChatGPT_prompt_v3.16.13.txt")


def test_command_rejects_unknown_fields(tmp_path: Path) -> None:
    runner = StudioCommandRunner(tmp_path / "workspace", CANONICAL)
    try:
        with pytest.raises(StudioCommandError, match="unknown fields") as error:
            runner.submit_stage1(
                {
                    "profile": "YOUTH_SAFE",
                    "duration_minutes": 12,
                    "unexpected": True,
                }
            )
        assert error.value.code == "UI103_UNKNOWN_FIELD"
    finally:
        runner.close()


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"profile": "YOUTH_SAFE", "duration_minutes": "12"}, "UI104_INVALID_REQUEST"),
        ({"profile": "YOUTH_SAFE", "duration_minutes": 12, "seed": -1}, "UI104_INVALID_REQUEST"),
        ({"profile": "UNKNOWN", "duration_minutes": 12}, "S102_INVALID_PROFILE"),
        ({"profile": "YOUTH_SAFE", "duration_minutes": 11}, "S107_DURATION_RANGE"),
    ],
)
def test_command_validates_stage1_input(
    tmp_path: Path, payload: dict[str, object], code: str
) -> None:
    runner = StudioCommandRunner(tmp_path / "workspace", CANONICAL)
    try:
        with pytest.raises(StudioCommandError) as error:
            runner.submit_stage1(payload)
        assert error.value.code == code
    finally:
        runner.close()


def test_stage1_production_runner_disables_test_mode(tmp_path: Path) -> None:
    runner = StudioCommandRunner(
        tmp_path / "workspace",
        CANONICAL,
        stage1_test_mode=False,
    )
    try:
        request = runner._stage1_request({"profile": "YOUTH_SAFE", "duration_minutes": 12})
        assert request.test_mode is False
    finally:
        runner.close()


def test_stage1_metadata_from_dialog_is_preserved(tmp_path: Path) -> None:
    runner = StudioCommandRunner(tmp_path / "workspace", CANONICAL)
    try:
        request = runner._stage1_request(
            {
                "profile": "ADULT_STANDARD",
                "duration_minutes": 25,
                "title": "Tập mới",
                "series": "Bộ truyện riêng",
                "episode": 7,
            }
        )
        assert (request.title, request.series, request.episode) == (
            "Tập mới",
            "Bộ truyện riêng",
            "7",
        )
        with pytest.raises(StudioCommandError) as unsupported:
            runner._stage1_request(
                {
                    "profile": "SERIAL_DETECTIVE",
                    "duration_minutes": 35,
                    "episode_mode": "CONTINUE_SERIES",
                    "episode": 2,
                }
            )
        assert unsupported.value.code == "UI105_UNSUPPORTED_EPISODE_MODE"
    finally:
        runner.close()


def test_stage1_job_runs_to_persisted_package(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runner = StudioCommandRunner(workspace, CANONICAL)
    try:
        submitted = runner.submit_stage1(
            {
                "profile": "YOUTH_SAFE",
                "language": "vi",
                "duration_minutes": 12,
                "seed": 7,
                "title": "Chuyến tàu đêm",
                "series": "Đường ray ký ức",
                "episode": 3,
            }
        )
        deadline = time.monotonic() + 20
        job = runner.get_job(str(submitted["id"]))
        while job["status"] in {"QUEUED", "RUNNING"} and time.monotonic() < deadline:
            time.sleep(0.02)
            job = runner.get_job(str(submitted["id"]))

        assert job["status"] == "PASS"
        assert job["workflow_id"]
        assert job["stage_id"]
        assert job["package_digest"]
        assert Path(str(job["package_path"])).is_file()
        with zipfile.ZipFile(str(job["package_path"])) as archive:
            meta = json.loads(archive.read("story.json"))["meta"]
        assert (meta["title"], meta["series"], meta["episode"]) == (
            "Chuyến tàu đêm",
            "Đường ray ký ức",
            "3",
        )
    finally:
        runner.close()


def test_missing_job_and_running_job_policy(tmp_path: Path) -> None:
    runner = StudioCommandRunner(tmp_path / "workspace", CANONICAL)
    try:
        with pytest.raises(StudioCommandError) as error:
            runner.get_job("missing")
        assert error.value.code == "UI101_JOB_NOT_FOUND"
    finally:
        runner.close()


def test_dead_worker_rejects_new_stage1_job(tmp_path: Path) -> None:
    runner = StudioCommandRunner(tmp_path / "workspace", CANONICAL)
    runner.close()

    with pytest.raises(StudioCommandError) as error:
        runner.submit_stage1({"profile": "YOUTH_SAFE", "duration_minutes": 12})

    assert error.value.code == "UI198_WORKER_UNAVAILABLE"


def test_stage2_requires_workspace_package(tmp_path: Path) -> None:
    runner = StudioCommandRunner(tmp_path / "workspace", CANONICAL)
    try:
        with pytest.raises(StudioCommandError) as missing:
            runner.submit_stage2({"execution_mode": "MOCK"})
        assert missing.value.code == "UI110_STAGE1_PACKAGE_REQUIRED"

        outside = tmp_path / "outside.zip"
        outside.write_bytes(b"not-a-package")
        with pytest.raises(StudioCommandError) as invalid:
            runner.submit_stage2({"execution_mode": "MOCK", "source_package": str(outside)})
        assert invalid.value.code == "UI111_STAGE1_PACKAGE_INVALID"
    finally:
        runner.close()


def test_stage2_validates_mode_and_comfyui_configuration(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    package = workspace / "outputs" / "story.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"fixture")
    runner = StudioCommandRunner(workspace, CANONICAL)
    try:
        with pytest.raises(StudioCommandError) as mode:
            runner.submit_stage2({"execution_mode": "CLOUD", "source_package": str(package)})
        assert mode.value.code == "UI104_INVALID_REQUEST"

        with pytest.raises(StudioCommandError) as comfy:
            runner.submit_stage2({"execution_mode": "COMFYUI", "source_package": str(package)})
        assert comfy.value.code == "UI112_COMFYUI_WORKFLOW_MISSING"
    finally:
        runner.close()


def test_production_image_stages_resolve_comfyui_adapter(tmp_path: Path) -> None:
    workflow = Path("comfy_workflows/sdxl_txt2img_api.json")
    runner = StudioCommandRunner(
        tmp_path / "workspace",
        CANONICAL,
        comfyui_workflow_path=workflow,
    )
    try:
        assert isinstance(runner._stage2_adapter("COMFYUI"), ComfyUIImageAdapter)
    finally:
        runner.close()


def test_import_story_validates_and_registers_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "workflow_manifest.json",
            json.dumps({"package_stage": "STAGE1", "active_profile": "YOUTH_SAFE"}),
        )
    monkeypatch.setattr("audio_story.studio.commands.load_stage1_package", lambda path: object())
    runner = StudioCommandRunner(tmp_path / "workspace", CANONICAL)
    try:
        result = runner.import_story_package(stream.getvalue(), "story.zip")
        assert result["package_stage"] == "STAGE1"
        assert result["kind"] == "STAGE1_CREATE"
        assert result["status"] == "PASS"
        assert Path(result["package_path"]).read_bytes() == stream.getvalue()
    finally:
        runner.close()


def test_import_story_rejects_malformed_zip(tmp_path: Path) -> None:
    runner = StudioCommandRunner(tmp_path / "workspace", CANONICAL)
    try:
        with pytest.raises(StudioCommandError) as error:
            runner.import_story_package(b"not-a-zip", "story.zip")
        assert error.value.code == "UI122_INVALID_STORY_PACKAGE"
    finally:
        runner.close()


def test_failed_stage2_job_can_be_requeued_with_same_job_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    package = workspace / "outputs" / "story.zip"
    package.parent.mkdir(parents=True)
    package.write_bytes(b"invalid-package-fixture")
    runner = StudioCommandRunner(workspace, CANONICAL)
    try:
        submitted = runner.submit_stage2({"execution_mode": "MOCK", "source_package": str(package)})
        deadline = time.monotonic() + 5
        job = runner.get_job(str(submitted["id"]))
        while job["status"] in {"QUEUED", "RUNNING"} and time.monotonic() < deadline:
            time.sleep(0.01)
            job = runner.get_job(str(submitted["id"]))
        assert job["status"] == "FAILED"

        retried = runner.retry_stage2(str(submitted["id"]))
        assert retried["id"] == submitted["id"]
        assert retried["status"] == "QUEUED"
    finally:
        runner.close()


def test_running_job_can_be_cancelled_cooperatively(tmp_path: Path) -> None:
    runner = StudioCommandRunner(tmp_path / "workspace", CANONICAL)
    try:
        job = StudioJob("job", "STAGE2_CREATE", "RUNNING", "p", "vi", 0, 0, "t")
        with runner._lock:
            runner._jobs[job.id] = job
            runner._cancellations[job.id] = threading.Event()
        result = runner.cancel_job(job.id)
        assert result["status"] == "CANCELLING"
        assert runner._cancellations[job.id].is_set()
    finally:
        runner.close()


def test_semantic_review_is_complete_unique_and_server_digest_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = StudioCommandRunner(tmp_path / "workspace", CANONICAL)
    try:
        job = StudioJob(
            "review",
            "STAGE2_CREATE",
            "WAITING_SEMANTIC_REVIEW",
            "p",
            "vi",
            0,
            0,
            "t",
            workflow_id="workflow",
            stage_id="stage",
            source_package="source.zip",
        )
        with runner._lock:
            runner._jobs[job.id] = job
        assets = [
            {"basename": f"asset-{index}.png", "image_sha256": f"{index:064x}"}
            for index in range(10)
        ]
        monkeypatch.setattr(runner, "semantic_review_assets", lambda _job_id: {"assets": assets})
        monkeypatch.setattr(
            runner, "_finalize_stage2", lambda review_job, _items: {"status": review_job.status}
        )
        monkeypatch.setattr(runner, "_persist_assessments", lambda _job, _items: None)
        payload = {
            "assessments": [
                {
                    "basename": item["basename"],
                    "status": "PASS",
                    "observable_findings": ["No visible text; composition matches the plan."],
                }
                for item in assets
            ]
        }
        result = runner.submit_semantic_review(job.id, payload)
        assert result["status"] == "WAITING_SEMANTIC_REVIEW"
        saved = runner._semantic_assessments[job.id]["asset-0.png"]
        assert saved.method == "HUMAN_REVIEW"
        assert len(saved.evidence_digest_sha256) == 64

        payload["assessments"][0]["observable_findings"] = []
        with pytest.raises(StudioCommandError) as error:
            runner.submit_semantic_review(job.id, payload)
        assert error.value.code == "UI104_INVALID_REQUEST"
    finally:
        runner.close()


def test_stage2_review_job_is_restored_from_sqlite(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    kernel = WorkflowKernel(workspace)
    try:
        workflow = kernel.create_workflow("YOUTH_SAFE", "STAGE2", "CREATE", "a" * 64, "b" * 64)
        stage = kernel.start_stage(workflow, "STAGE2", "c" * 64)
        now = utc_now()
        with kernel.db.transaction() as connection:
            connection.execute(
                "INSERT INTO studio_stage2_runs VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "durable-job",
                    workflow,
                    stage,
                    str(workspace / "source.zip"),
                    "d" * 64,
                    "COMFYUI",
                    "RUNNING",
                    now,
                    now,
                ),
            )
    finally:
        kernel.close()
    runner = StudioCommandRunner(workspace, CANONICAL)
    try:
        restored = runner.get_job("durable-job")
        assert restored["status"] == "WAITING_SEMANTIC_REVIEW"
        assert restored["workflow_id"] == workflow
        assert restored["stage_id"] == stage
    finally:
        runner.close()
