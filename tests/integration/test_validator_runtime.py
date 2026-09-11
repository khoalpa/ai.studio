from __future__ import annotations

import json
from pathlib import Path

from audio_story.domain.enums import Profile, Stage
from audio_story.domain.models import CompileRequest
from audio_story.prompt_compiler import audio_mode_collision_finding, compile_capsule, parse_prompt
from audio_story.validation.strict_json import parse_json_bytes
from audio_story.validation.validate_story_runtime import (
    ValidationRequest,
    _result_projection,
    main,
    validate,
)

ROOT = Path(__file__).parents[2]
CANONICAL = ROOT / "canonical" / "ChatGPT_prompt_v3.16.13.txt"
PROMPT_DIGEST = "4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27"


def _capsule_digest() -> str:
    parsed = parse_prompt(CANONICAL.read_bytes())
    return compile_capsule(parsed, CompileRequest(Stage.STAGE1, Profile.YOUTH_SAFE)).digest


def test_result_binds_artifact_prompt_capsule_and_reopens(tmp_path: Path) -> None:
    artifact = tmp_path / "story.json"
    artifact.write_bytes(b'{"schema_version":"2.3"}')
    output = tmp_path / "deterministic_validation_result.json"
    request = ValidationRequest(
        "STAGE1",
        "YOUTH_SAFE",
        "CREATE",
        "INPUT",
        artifact,
        PROMPT_DIGEST,
        _capsule_digest(),
        output,
    )
    first = validate(request)
    second = validate(request)
    assert first == second
    assert first["overall_status"] == "NOT_VERIFIED"
    assert first["result_self_reopen_status"] == "PASS"
    assert first["input_bindings"][0]["sha256"]
    assert first["invocation"]["capsule_digest"] == _capsule_digest()
    reopened = parse_json_bytes(output.read_bytes(), str(output), engine_generated=True)
    assert reopened.value["result_digest"] == first["result_digest"]


def test_invalid_artifact_returns_fail_and_cli_exit_code(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    artifact = tmp_path / "bad.json"
    artifact.write_bytes(b'{"x":NaN}')
    request = ValidationRequest(
        "STAGE1", "ADULT_STANDARD", "CREATE", "INPUT", artifact, PROMPT_DIGEST, "a" * 64
    )
    result = validate(request)
    assert result["overall_status"] == "FAIL"
    assert result["findings"][0]["detector_class"] == "DETERMINISTIC"
    exit_code = main(
        [
            str(artifact),
            "--stage",
            "STAGE1",
            "--profile",
            "ADULT_STANDARD",
            "--route",
            "CREATE",
            "--phase",
            "INPUT",
            "--canonical-prompt-sha256",
            PROMPT_DIGEST,
            "--capsule-digest",
            "a" * 64,
        ]
    )
    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["overall_status"] == "FAIL"


def test_m1_collision_finding_is_unchanged() -> None:
    finding = audio_mode_collision_finding(parse_prompt(CANONICAL.read_bytes()))
    assert finding is not None
    assert finding.code == "PCF001_STAGE4_AUDIO_MODE_DEFAULT_COLLISION"


def test_missing_bytes_are_not_pass_and_projection_excludes_volatile_fields(tmp_path: Path) -> None:
    request = ValidationRequest(
        "STAGE1",
        "YOUTH_SAFE",
        "CREATE",
        "INPUT",
        tmp_path / "missing.json",
        PROMPT_DIGEST,
        "b" * 64,
    )
    result = validate(request)
    assert result["overall_status"] == "FAIL"
    projection = _result_projection(
        {
            "stable": 1,
            "generated_timestamp": "volatile",
            "result_digest": "self",
            "result_self_reopen_status": "PASS",
        }
    )
    assert projection == {"stable": 1}
