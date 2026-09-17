from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Event

import pytest

from audio_story.adapters.image.base import ImageAdapterError
from audio_story.studio.vlm import LocalQwenVlmAssessor, VlmAssessmentError


class _Process:
    returncode = 0

    def __init__(self, command: list[str], **_kwargs: object) -> None:
        output = Path(command[command.index("--output") + 1])
        image = Path(command[2]).read_bytes()
        output.write_text(
            json.dumps(
                {
                    "image_sha256": hashlib.sha256(image).hexdigest(),
                    "assessment": {
                        "status": "PASS",
                        "observable_findings": ["Coherent landscape with no visible text."],
                    },
                    "evidence_digest_sha256": "a" * 64,
                }
            ),
            encoding="utf-8",
        )

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return "ok", ""

    def kill(self) -> None:
        return None


def test_qwen_assessor_binds_exact_bytes_and_forces_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "model"
    model.mkdir()
    runner = tmp_path / "runner.py"
    runner.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("audio_story.studio.vlm.subprocess.Popen", _Process)
    result = LocalQwenVlmAssessor(model, runner).assess(
        b"exact-png-bytes", "opening.png", {"basename": "opening.png"}, Event()
    )
    assert result.status == "PASS"
    assert result.evidence_digest_sha256 == "a" * 64


def test_qwen_assessor_fails_closed_when_runtime_is_missing(tmp_path: Path) -> None:
    with pytest.raises(VlmAssessmentError) as error:
        LocalQwenVlmAssessor(tmp_path / "missing", tmp_path / "missing.py").assess(
            b"png", "opening.png", {}, Event()
        )
    assert error.value.code == "VLM001_LOCAL_RUNTIME_MISSING"
    assert isinstance(error.value, ImageAdapterError)


def test_qwen_assessor_accepts_single_observable_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StringFindingProcess(_Process):
        def __init__(self, command: list[str], **kwargs: object) -> None:
            super().__init__(command, **kwargs)
            output = Path(command[command.index("--output") + 1])
            value = json.loads(output.read_text(encoding="utf-8"))
            value["assessment"] = {
                "status": "FAIL",
                "observable_findings": "Two people are visible.",
            }
            output.write_text(json.dumps(value), encoding="utf-8")

    model = tmp_path / "model"
    model.mkdir()
    runner = tmp_path / "runner.py"
    runner.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("audio_story.studio.vlm.subprocess.Popen", StringFindingProcess)

    result = LocalQwenVlmAssessor(model, runner).assess(b"png", "char_001.png", {}, Event())

    assert result.status == "FAIL"
    assert result.observable_findings == ("Two people are visible.",)
