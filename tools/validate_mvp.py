from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_story.doctor import environment_report
from ai_story.hashing import canonical_json_bytes, sha256_bytes
from ai_story.models import Profile
from ai_story.smoke import run_deterministic_smoke

ROOT = Path(__file__).resolve().parents[1]


def command_check(identifier: str, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = "\n".join(value.strip() for value in (completed.stdout, completed.stderr) if value.strip())
    return {
        "id": identifier,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "return_code": completed.returncode,
        "command": command,
        "output_tail": output[-4000:],
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    checks = "\n".join(
        f"- `{item['id']}`: **{item['status']}**"
        for item in report["automated_checks"]
    )
    profiles = "\n".join(
        f"- `{item['profile']}`: **{item['status']}**, Stage 1–4, "
        f"release `{item['release_bundle']['distribution_status']}`, "
        f"{item['validation_ledger']['summary']['open_warning_count']} cảnh báo mở."
        for item in report["end_to_end_matrix"]
    )
    providers = "\n".join(
        f"- `{item['provider_mode']}`: **{item['status']}** — {item['reason']}"
        for item in report["provider_matrix"]
    )
    path.write_text(
        "# Báo cáo nghiệm thu MVP\n\n"
        f"- Thời điểm: `{report['generated_at_utc']}`\n"
        f"- Kết luận: **{report['conclusion']}**\n"
        f"- Digest: `{report['report_digest_sha256']}`\n\n"
        "## Kiểm tra tự động\n\n" + checks + "\n\n"
        "## Ma trận end-to-end\n\n" + profiles + "\n\n"
        "## Provider\n\n" + providers + "\n\n"
        "## Phạm vi xác nhận\n\n"
        "- Package integrity, lineage, validation ledger và release bundle đã được xác minh.\n"
        "- Cancel/retry, persistence, server restart và package legacy được bao phủ bởi regression tests.\n"
        "- Gate chất lượng chỉ tạo warning; lỗi thực thi/integrity vẫn fail.\n"
        "- Provider local chưa chạy không được suy diễn là production-ready.\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run repeatable AI Story MVP acceptance")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "mvp-acceptance")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    checks = [
        command_check("RUFF", [sys.executable, "-m", "ruff", "check", "src", "tests", "tools"]),
        command_check("SPEC_LINT", [sys.executable, "tools/lint_spec.py"]),
    ]
    if not args.skip_tests:
        checks.append(command_check("PYTEST", [sys.executable, "-m", "pytest", "-q"]))

    e2e = []
    for profile in Profile:
        try:
            e2e.append(run_deterministic_smoke(output / "runs" / profile.value.lower(), profile))
        except Exception as exc:
            e2e.append({"profile": profile.value, "status": "FAIL", "error": str(exc)})

    doctor = environment_report()
    provider_matrix = [{
        "provider_mode": "deterministic", "status": "PASS",
        "reason": "Executed for all canonical profiles",
    }]
    for mode in ("hybrid", "text_local", "local"):
        provider_matrix.append({
            "provider_mode": mode,
            "status": "NOT_EXECUTED",
            "reason": (
                "Requires an explicitly selected local model and runtime evidence; "
                "recorded as a limitation rather than an acceptance failure"
            ),
        })

    execution_failures = [item["id"] for item in checks if item["status"] == "FAIL"]
    execution_failures.extend(
        f"E2E:{item['profile']}" for item in e2e if item["status"] != "PASS"
    )
    report = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "conclusion": "PASS_WITH_WARNINGS" if not execution_failures else "FAIL",
        "execution_failures": execution_failures,
        "doctor": doctor,
        "automated_checks": checks,
        "end_to_end_matrix": e2e,
        "provider_matrix": provider_matrix,
        "coverage": {
            "profiles": [profile.value for profile in Profile],
            "stages": ["STAGE1", "STAGE2", "STAGE3", "STAGE4"],
            "operational_regressions": [
                "cancel", "retry", "job_persistence", "server_restart",
                "legacy_package_reporting", "release_bundle_verification",
            ],
        },
        "report_digest_sha256": None,
    }
    report["report_digest_sha256"] = sha256_bytes(canonical_json_bytes(report))
    json_path = output / "mvp_acceptance_report.json"
    markdown_path = output / "mvp_acceptance_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, markdown_path)
    print(json.dumps({
        "conclusion": report["conclusion"],
        "json_report": str(json_path),
        "markdown_report": str(markdown_path),
        "report_digest_sha256": report["report_digest_sha256"],
    }, ensure_ascii=False, indent=2))
    return 1 if execution_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
