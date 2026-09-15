import json
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from audio_story.backup import BackupResult
from audio_story.cli import main


def test_doctor_cli_emits_one_json_document(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr("audio_story.cli.report_json", lambda: '{"status":"ok"}')
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {"status": "ok"}


def test_restore_cli_uses_runtime_migration_resources(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], tmp_path: Path
) -> None:
    migrations = tmp_path / "packaged-migrations"
    migrations.mkdir()
    (migrations / "001_test.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr("audio_story.cli.migration_directory", lambda: migrations)

    def restored(backup: Path, workspace: Path, actual_migrations: Path) -> BackupResult:
        assert backup == Path("input.asbackup")
        assert workspace == Path("restored")
        assert actual_migrations == migrations
        return BackupResult(backup, "a" * 64, "b" * 64, 2, "FULL")

    monkeypatch.setattr("audio_story.cli.restore_backup", restored)
    assert main(["restore", "--backup", "input.asbackup", "--workspace", "restored"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
