from __future__ import annotations

import json
from pathlib import Path

import pytest

from audio_story.domain.state import CallStatus, DetectorClass, GateStatus
from audio_story.studio.instance_lock import StudioInstanceLock, StudioInstanceLockError
from audio_story.studio.server import StudioServerError, serve_studio
from audio_story.studio.snapshot import StudioSnapshotService
from audio_story.workflows import WorkflowKernel

DIGEST = "a" * 64
CAPSULE = "b" * 64


def test_studio_runtime_states_never_ship_demo_story_data() -> None:
    ui = Path(__file__).parents[2] / "ui" / "dist"
    html = (ui / "index.html").read_text(encoding="utf-8")
    javascript = (ui / "app.js").read_text(encoding="utf-8")
    ux_css = (ui / "ux.css").read_text(encoding="utf-8")

    assert 'class="runtime-booting"' in html
    assert 'href="./ux.css"' in html
    assert "function setRuntimeState(state, detail = '')" in javascript
    assert "setRuntimeState('OFFLINE')" in javascript
    assert "setRuntimeState('EMPTY'" in javascript
    assert "setRuntimeState('LIVE'" in javascript
    assert "runtimeRefreshInFlight" in javascript
    assert "document.hidden || runtimeState === 'OFFLINE'" in javascript
    assert ".runtime-banner-action" in ux_css
    assert ".story-dialog-wide" in ux_css

    demo_values = (
        "Tiếng vọng dưới lòng hồ",
        "Bến thuyền trong sương sớm",
        "Đường hầm thoát nước",
        "Hồ sơ số 07",
        "8f3c74b1d8968ce091a2",
        "warning-sign.png",
        "lakeside-path.png",
    )
    for value in demo_values:
        assert value not in html


def test_execution_result_is_hidden_and_reset_before_stage_completion() -> None:
    ui = Path(__file__).parents[2] / "ui" / "dist"
    css = (ui / "styles.css").read_text(encoding="utf-8")
    javascript = (ui / "app.js").read_text(encoding="utf-8")

    assert ".execution-result[hidden]{display:none!important}" in css
    assert "if (result.hidden)" in javascript
    assert "setText('#execution-result-title', 'Chưa có kết quả Stage')" in javascript
    assert "setText('#execution-result-summary', 'Stage chưa kết thúc.')" in javascript


def test_studio_navigation_and_overlays_preserve_accessibility_contract() -> None:
    ui = Path(__file__).parents[2] / "ui" / "dist"
    html = (ui / "index.html").read_text(encoding="utf-8")
    javascript = (ui / "app.js").read_text(encoding="utf-8")
    ux_css = (ui / "ux.css").read_text(encoding="utf-8")

    assert 'class="skip-link" href="#workspace-main"' in html
    assert 'id="workspace-main" tabindex="-1"' in html
    assert 'aria-controls="primary-navigation" aria-expanded="false"' in html
    assert 'role="dialog" aria-modal="true"' in html
    assert 'aria-labelledby="story-dialog-title"' in html
    assert 'aria-labelledby="review-dialog-title"' in html
    assert 'aria-labelledby="stage2-dialog-title"' in html
    assert html.count('role="alert"') == 3
    assert "item.setAttribute('aria-current', 'page')" in javascript
    assert "mobileMenu.setAttribute('aria-expanded', String(open))" in javascript
    assert "lastInspectorTrigger?.isConnected" in javascript
    assert "event.key === 'Tab' && inspector.classList.contains('open')" in javascript
    assert ":focus-visible" in ux_css
    assert "@media (forced-colors: active)" in ux_css


def test_serial_presets_are_partitioned_by_content_profile() -> None:
    ui = Path(__file__).parents[2] / "ui" / "dist"
    html = (ui / "index.html").read_text(encoding="utf-8")
    javascript = (ui / "app.js").read_text(encoding="utf-8")

    assert 'name="preset" disabled' in html
    assert "const profilePresets = {" in javascript
    assert "YOUTH_SAFE:" in javascript
    assert "ADULT_STANDARD:" in javascript
    assert "SERIAL_DETECTIVE:" in javascript
    assert "renderPresetOptions(profile);" in javascript


def test_empty_snapshot_uses_persisted_workspace(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path / "workspace")
    try:
        snapshot = StudioSnapshotService(kernel).latest()
        assert snapshot["mode"] == "EMPTY"
        assert snapshot["workflow"] is None
        assert snapshot["gate_summary"] == {
            "total": 0,
            "pass": 0,
            "fail": 0,
            "not_verified": 0,
        }
    finally:
        kernel.close()


def test_snapshot_projects_transactions_gates_and_events(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path / "workspace")
    try:
        workflow_id = kernel.create_workflow("SERIAL_DETECTIVE", "STAGE2", "CREATE", DIGEST, DIGEST)
        stage_id = kernel.start_stage(workflow_id, "STAGE2", CAPSULE)
        transaction_id = kernel.get_or_create_transaction(stage_id, "LANDSCAPE", "lake-zone.png")
        call_id = kernel.begin_generation_call(
            transaction_id,
            DIGEST,
            model_identity="local-model",
            adapter_version="1.0",
        )
        kernel.finish_generation_call(call_id, CallStatus.FINISHED, DIGEST)
        artifact_id = kernel.register_candidate(
            call_id, b"candidate", "image/png", "STAGE2", "LANDSCAPE"
        )
        kernel.record_gate(
            stage_id,
            artifact_id,
            "SAFE_MARGIN",
            DetectorClass.TOOL_MEASURED,
            GateStatus.FAIL,
            {"margin": 0.07},
            DIGEST,
            CAPSULE,
            "1.0",
        )

        snapshot = StudioSnapshotService(kernel).latest()

        assert snapshot["mode"] == "LIVE"
        assert snapshot["workflow"]["id"] == workflow_id
        assert snapshot["pipeline_stages"][0]["stage"] == "STAGE2"
        assert snapshot["stages"][0]["progress"] == {"committed": 0, "total": 1}
        transaction = snapshot["stages"][0]["transactions"][0]
        assert transaction["basename"] == "lake-zone.png"
        assert transaction["latest_call"]["model_identity"] == "local-model"
        assert transaction["calls"] == [transaction["latest_call"]]
        assert transaction["created_at"]
        assert transaction["latest_call"]["request_digest"] == DIGEST
        assert snapshot["gate_summary"] == {
            "total": 1,
            "pass": 0,
            "fail": 1,
            "not_verified": 0,
        }
        assert snapshot["gates"][0]["evidence"] == {"margin": 0.07}
        assert snapshot["events"]
    finally:
        kernel.close()


def test_snapshot_uses_committed_story_metadata_for_workspace_heading(tmp_path: Path) -> None:
    kernel = WorkflowKernel(tmp_path / "workspace")
    try:
        workflow_id = kernel.create_workflow("YOUTH_SAFE", "STAGE1", "CREATE", DIGEST, DIGEST)
        stage_id = kernel.start_stage(workflow_id, "STAGE1", CAPSULE)
        transaction_id = kernel.get_or_create_transaction(stage_id, "TEXT", "story.json")
        call_id = kernel.begin_generation_call(transaction_id, DIGEST)
        story = json.dumps(
            {
                "meta": {
                    "title": "Tên truyện thật",
                    "series": "Tủ sách mùa hạ",
                    "episode": "7",
                }
            }
        ).encode("utf-8")
        artifact_id = kernel.register_candidate(
            call_id, story, "application/json", "STAGE1", "STORY"
        )
        kernel.finish_generation_call(call_id, CallStatus.FINISHED, DIGEST)
        kernel.commit_artifact(transaction_id, artifact_id)

        snapshot = StudioSnapshotService(kernel).latest()

        assert snapshot["story"] == {
            "title": "Tên truyện thật",
            "series": "Tủ sách mùa hạ",
            "episode": "7",
        }
        javascript = (Path(__file__).parents[2] / "ui" / "dist" / "app.js").read_text(
            encoding="utf-8"
        )
        assert "setText('.page-heading h1', story.title);" in javascript
        assert "setText('.eyebrow span:not(.episode-code)', story.series);" in javascript
    finally:
        kernel.close()


def test_server_rejects_non_loopback_binding(tmp_path: Path) -> None:
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("ok", encoding="utf-8")

    with pytest.raises(StudioServerError, match="UI004_NON_LOOPBACK_BIND"):
        serve_studio(tmp_path / "workspace", host="0.0.0.0", ui_directory=ui)


def test_server_rejects_invalid_port_before_opening_workspace(tmp_path: Path) -> None:
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("ok", encoding="utf-8")

    with pytest.raises(StudioServerError, match="UI005_INVALID_PORT"):
        serve_studio(tmp_path / "workspace", port=0, ui_directory=ui)


def test_workspace_instance_lock_rejects_live_owner(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    first = StudioInstanceLock.acquire(workspace)
    try:
        with pytest.raises(StudioInstanceLockError, match="UI015_WORKSPACE_ALREADY_OPEN"):
            StudioInstanceLock.acquire(workspace)
    finally:
        first.release()


def test_workspace_instance_lock_reclaims_stale_owner(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lock_path = workspace / ".audio-story-studio.lock"
    lock_path.write_text('{"pid":99999999,"token":"stale","workspace":"stale"}', encoding="utf-8")

    lock = StudioInstanceLock.acquire(workspace)
    try:
        assert lock.path == lock_path
        assert '"token":"stale"' not in lock_path.read_text(encoding="utf-8")
    finally:
        lock.release()
