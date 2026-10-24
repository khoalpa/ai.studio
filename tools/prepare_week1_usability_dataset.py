from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from ai_story.job_engine import JobRegistry
from ai_story.validation_ledger import write_ledger
from ai_story.web import WebService


MARKER = ".ai-story-week1-dataset"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _reset_generated_root(root: Path) -> None:
    if root.exists():
        marker = root / MARKER
        if not marker.is_file():
            raise RuntimeError(
                f"Refusing to replace unmarked directory: {root}. "
                "Choose an empty output directory."
            )
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / MARKER).write_text("generated fixture; safe to replace\n", encoding="utf-8")


def _wait_for_job(service: WebService, job_id: str, timeout_seconds: float = 90) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while True:
        job = service.jobs.get(job_id)
        if job is None:
            raise RuntimeError(f"Job disappeared: {job_id}")
        if job.state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            if job.state != "SUCCEEDED":
                raise RuntimeError(job.error or f"Job ended in {job.state}")
            return job
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for {job_id}")
        time.sleep(0.05)


def _add_research_blocker(work_root: Path) -> None:
    ledger_path = work_root / "validation_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    records = list(ledger.get("records", []))
    records.append(
        {
            "record_id": "RESEARCH:BLOCKER:BRIEF_COVERAGE",
            "stage": "STAGE1",
            "category": "STORY_GATE",
            "severity": "PUBLISH_BLOCKER",
            "status": "FAIL",
            "resolution_status": "OPEN",
            "continuation_policy": "BLOCK",
            "release_impact": "NOT_RECOMMENDED",
            "evidence_ids": ["research:evidence:brief-coverage"],
            "locators": ["story.script[3]"],
            "details": [
                {
                    "error": "MISSING_REQUIRED_OUTCOME",
                    "message": "Kết quả bắt buộc của lời hứa chưa có bằng chứng trong phần kết.",
                }
            ],
        }
    )
    ledger_path.unlink()
    write_ledger(ledger_path, "STAGE1", records)


def prepare(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    _reset_generated_root(output_root)

    clean_workspace = output_root / "clean-workspace"
    source_workspace = output_root / "source-workspace"
    blocked_workspace = output_root / "blocked-workspace"
    ready_workspace = output_root / "ready-workspace"
    packages = output_root / "packages"
    clean_workspace.mkdir()
    source_workspace.mkdir()
    packages.mkdir()

    jobs = JobRegistry(max_workers=1)
    service = WebService(source_workspace, jobs=jobs)
    try:
        submitted = service.submit_stage1(
            {
                "profile": "YOUTH_SAFE",
                "brief": "Một bạn nhỏ giữ lời hứa chăm sóc cây non của lớp sau một trận mưa lớn.",
                "language": "vi",
                "minutes": 15,
                "provider_mode": "deterministic",
                "quality_preset": "balanced",
                "idempotency_key": "week1-usability-dataset-v1",
            }
        )
        completed = _wait_for_job(service, submitted.job_id)
        run_id = str(completed.run_id)
        run_detail = service.get_run(run_id)
        package_source = Path(str(run_detail["output_package"]))
        warning_package = packages / "story-warning.zip"
        shutil.copy2(package_source, warning_package)

        shutil.copytree(source_workspace, blocked_workspace)
        shutil.copytree(source_workspace, ready_workspace)
        _add_research_blocker(blocked_workspace / run_id / "work")

        blocked_service = WebService(blocked_workspace, jobs=JobRegistry(max_workers=1))
        try:
            blocked_detail = blocked_service.get_run(run_id)
            if blocked_detail["validation"]["blocking_count"] < 1:
                raise RuntimeError("Research blocker was not exposed by the web service")
            inspected = blocked_service.inspect_package(warning_package.read_bytes())
            if not inspected.get("valid"):
                raise RuntimeError("Warning package failed canonical verification")
        finally:
            blocked_service.jobs.close()
    finally:
        service.jobs.close()

    manifest = {
        "schema_version": "1.0",
        "dataset_id": "week1-usability-baseline-v1",
        "generated_at_local_date": "2026-10-10",
        "clean_workspace": str(clean_workspace),
        "blocked_workspace": str(blocked_workspace),
        "ready_workspace": str(ready_workspace),
        "blocked_run_id": run_id,
        "warning_package": str(warning_package),
        "expected": {
            "clean_workspace_run_count": 0,
            "blocked_workspace_minimum_open_blockers": 1,
            "ready_workspace_open_blockers": 0,
            "warning_package_integrity": "PASS",
            "warning_package_release_recommendation": "NOT_RECOMMENDED",
        },
    }
    _write_json(output_root / "study-manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the fixed Week 1 usability research dataset."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = prepare(args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
