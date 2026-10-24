"""Evaluate whether the UI/UX validation round meets its completion criteria."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

TASKS = ("t1", "t2", "t3", "t4")
TRUE_VALUES = {"1", "true", "yes", "y"}
VALID_RESULTS = {"SUCCESS", "ASSISTED", "FAILURE"}
VALID_SOURCES = {"HUMAN", "PILOT", "SIMULATED_CODEX"}


def _is_true(value: object) -> bool:
    return str(value).strip().lower() in TRUE_VALUES


def _integer(row: dict[str, str], field: str, row_number: int, errors: list[str]) -> int:
    try:
        value = int(row.get(field, ""))
    except (TypeError, ValueError):
        errors.append(f"Dòng {row_number}: {field} phải là số nguyên.")
        return 0
    if value < 0:
        errors.append(f"Dòng {row_number}: {field} không được âm.")
    return value


def load_sessions(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    sessions: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "participant_id",
            "session_source",
            "role",
            "session_valid",
            "t2_result",
            "t2_seconds",
            "t2_help_level",
            "identifies_first_blocker",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            return [], ["CSV thiếu cột: " + ", ".join(sorted(missing))]

        for row_number, row in enumerate(reader, start=2):
            if not any(str(value).strip() for value in row.values()):
                continue
            source = row["session_source"].strip().upper()
            if source not in VALID_SOURCES:
                errors.append(
                    f"Dòng {row_number}: session_source phải thuộc {sorted(VALID_SOURCES)}."
                )
            for task in TASKS:
                result = row.get(f"{task}_result", "").strip().upper()
                if result and result not in VALID_RESULTS:
                    errors.append(
                        f"Dòng {row_number}: {task}_result phải thuộc {sorted(VALID_RESULTS)}."
                    )
            critical_errors = sum(
                _integer(row, f"{task}_critical_errors", row_number, errors) for task in TASKS
            )
            sessions.append(
                {
                    **row,
                    "session_source": source,
                    "role": row["role"].strip().upper(),
                    "session_valid_bool": _is_true(row["session_valid"]),
                    "t2_seconds_int": _integer(row, "t2_seconds", row_number, errors),
                    "t2_help_level_int": _integer(row, "t2_help_level", row_number, errors),
                    "critical_errors_total": critical_errors,
                }
            )
    return sessions, errors


def load_nvda(path: Path | None) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None or not path.exists():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"Không đọc được kết quả NVDA: {exc}"]
    if not isinstance(data, dict):
        return None, ["Kết quả NVDA phải là một JSON object."]
    return data, []


def evaluate(sessions: list[dict[str, Any]], nvda: dict[str, Any] | None) -> dict[str, Any]:
    humans = [
        row
        for row in sessions
        if row["session_source"] == "HUMAN" and row["session_valid_bool"]
    ]
    roles = Counter(row["role"] for row in humans)
    blocker_passes = sum(
        row.get("t2_result", "").strip().upper() == "SUCCESS"
        and row["t2_seconds_int"] <= 30
        and row["t2_help_level_int"] == 0
        and _is_true(row.get("identifies_first_blocker"))
        for row in humans
    )
    required_blocker_passes = max(4, (len(humans) * 80 + 99) // 100)
    critical_errors = sum(row["critical_errors_total"] for row in humans)
    nvda_pass = bool(
        nvda
        and nvda.get("session_type") == "HUMAN_NVDA"
        and nvda.get("completed") is True
        and nvda.get("browse_mode_pass") is True
        and nvda.get("focus_mode_pass") is True
        and nvda.get("unnamed_elements") == 0
        and nvda.get("focus_traps") == 0
        and nvda.get("critical_errors") == 0
    )

    checks = [
        {
            "id": "valid_human_sessions",
            "label": "Ít nhất 5 phiên người thật hợp lệ",
            "pass": len(humans) >= 5,
            "actual": len(humans),
            "required": 5,
        },
        {
            "id": "operations_sample",
            "label": "Ít nhất 2 người thuộc nhóm vận hành",
            "pass": roles["OPERATIONS"] >= 2,
            "actual": roles["OPERATIONS"],
            "required": 2,
        },
        {
            "id": "editorial_qa_sample",
            "label": "Ít nhất 2 người thuộc nhóm biên tập/QA",
            "pass": roles["EDITORIAL_QA"] >= 2,
            "actual": roles["EDITORIAL_QA"],
            "required": 2,
        },
        {
            "id": "blocker_discovery",
            "label": "Ít nhất 80% và không dưới 4 người tìm blocker trong 30 giây, không gợi ý",
            "pass": len(humans) >= 5 and blocker_passes >= required_blocker_passes,
            "actual": blocker_passes,
            "required": required_blocker_passes,
        },
        {
            "id": "critical_errors",
            "label": "Không có lỗi nghiêm trọng sau ít nhất 5 phiên người thật",
            "pass": len(humans) >= 5 and critical_errors == 0,
            "actual": f"{critical_errors} lỗi / {len(humans)} phiên",
            "required": "0 lỗi / ≥5 phiên",
        },
        {
            "id": "nvda",
            "label": "Một phiên NVDA người thật đạt toàn bộ checklist",
            "pass": nvda_pass,
            "actual": "đạt" if nvda_pass else "chưa đạt",
            "required": "đạt",
        },
    ]
    return {
        "status": "COMPLETE" if all(check["pass"] for check in checks) else "INCOMPLETE",
        "eligible_human_sessions": len(humans),
        "excluded_sessions": len(sessions) - len(humans),
        "checks": checks,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Báo cáo cổng hoàn thành validation UI/UX",
        "",
        f"**Trạng thái: {result['status']}**",
        "",
        f"Phiên người thật hợp lệ: {result['eligible_human_sessions']}. "
        f"Phiên bị loại hoặc không hợp lệ: {result['excluded_sessions']}.",
        "",
        "| Điều kiện | Kết quả | Thực tế | Yêu cầu |",
        "|---|---:|---:|---:|",
    ]
    for check in result["checks"]:
        mark = "Đạt" if check["pass"] else "Chưa đạt"
        lines.append(
            f"| {check['label']} | {mark} | {check['actual']} | {check['required']} |"
        )
    lines.extend(
        [
            "",
            "Dữ liệu mô phỏng và pilot không được tính là phiên người thật hợp lệ.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--nvda", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)

    sessions, errors = load_sessions(args.sessions)
    nvda, nvda_errors = load_nvda(args.nvda)
    errors.extend(nvda_errors)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    result = evaluate(sessions, nvda)
    content = (
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else render_markdown(result)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
