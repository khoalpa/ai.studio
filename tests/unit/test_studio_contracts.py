from __future__ import annotations

from pathlib import Path

from audio_story.studio.commands import StudioCommandRunner


def test_diagnostics_is_local_and_reports_empty_workspace(tmp_path: Path) -> None:
    runner = StudioCommandRunner(
        tmp_path / "workspace", Path("canonical/ChatGPT_prompt_v3.16.13.txt")
    )
    try:
        value = runner.diagnostics()
        assert value["status"] == "PASS"
        assert value["sqlite"]["integrity"] == "OK"
        assert value["sqlite"]["journal_mode"] == "WAL"
        assert value["jobs"]["total"] == 0
        assert value["disk"]["free_bytes"] > 0
    finally:
        runner.close()


def test_release_readiness_fail_closes_without_stage4(tmp_path: Path) -> None:
    runner = StudioCommandRunner(
        tmp_path / "workspace", Path("canonical/ChatGPT_prompt_v3.16.13.txt")
    )
    try:
        value = runner.release_readiness()
        assert value["status"] == "BLOCKED"
        assert "M22_STAGE4_OUTPUT_MISSING" in value["blockers"]
    finally:
        runner.close()
