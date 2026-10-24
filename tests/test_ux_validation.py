from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "tools" / "evaluate_ux_validation.py"
SPEC = importlib.util.spec_from_file_location("evaluate_ux_validation", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def session(
    participant_id: str,
    role: str,
    *,
    source: str = "HUMAN",
    seconds: int = 20,
    help_level: int = 0,
    identifies: str = "TRUE",
    critical_errors: int = 0,
) -> dict[str, object]:
    return {
        "participant_id": participant_id,
        "session_source": source,
        "role": role,
        "session_valid_bool": True,
        "t2_result": "SUCCESS",
        "t2_seconds_int": seconds,
        "t2_help_level_int": help_level,
        "identifies_first_blocker": identifies,
        "critical_errors_total": critical_errors,
    }


def passing_nvda() -> dict[str, object]:
    return {
        "session_type": "HUMAN_NVDA",
        "completed": True,
        "browse_mode_pass": True,
        "focus_mode_pass": True,
        "unnamed_elements": 0,
        "focus_traps": 0,
        "critical_errors": 0,
    }


def passing_sessions() -> list[dict[str, object]]:
    return [
        session("P01", "OPERATIONS"),
        session("P02", "OPERATIONS"),
        session("P03", "EDITORIAL_QA"),
        session("P04", "EDITORIAL_QA"),
        session("P05", "TECHNICAL", seconds=40),
    ]


def test_empty_evidence_is_incomplete() -> None:
    result = MODULE.evaluate([], None)
    assert result["status"] == "INCOMPLETE"


def test_five_humans_and_nvda_can_complete() -> None:
    result = MODULE.evaluate(passing_sessions(), passing_nvda())
    assert result["status"] == "COMPLETE"


def test_simulated_sessions_are_excluded() -> None:
    sessions = [
        session(f"S{number}", "OPERATIONS", source="SIMULATED_CODEX")
        for number in range(5)
    ]
    result = MODULE.evaluate(sessions, passing_nvda())
    assert result["status"] == "INCOMPLETE"
    assert result["eligible_human_sessions"] == 0
    assert result["excluded_sessions"] == 5


def test_critical_error_blocks_completion() -> None:
    sessions = passing_sessions()
    sessions[0]["critical_errors_total"] = 1
    result = MODULE.evaluate(sessions, passing_nvda())
    assert result["status"] == "INCOMPLETE"
    check = next(item for item in result["checks"] if item["id"] == "critical_errors")
    assert check["pass"] is False
