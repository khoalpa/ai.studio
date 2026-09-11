import json

from pytest import CaptureFixture, MonkeyPatch

from audio_story.cli import main


def test_doctor_cli_emits_one_json_document(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.setattr("audio_story.cli.report_json", lambda: '{"status":"ok"}')
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {"status": "ok"}
