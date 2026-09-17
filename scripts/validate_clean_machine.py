"""Validate the local Studio release from a brand-new temporary workspace."""

from __future__ import annotations

import argparse
import shutil
import tempfile
import time
from pathlib import Path

from audio_story.studio.commands import StudioCommandRunner


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args()
    checks: dict[str, str] = {}
    canonical = root / "canonical" / "ChatGPT_prompt_v3.16.13.txt"
    checks["canonical"] = "PASS" if canonical.is_file() else "FAIL"
    checks["ui"] = "PASS" if (root / "ui" / "dist" / "index.html").is_file() else "FAIL"
    checks["ffmpeg"] = "PASS" if shutil.which("ffmpeg") and shutil.which("ffprobe") else "FAIL"
    workspace = Path(tempfile.mkdtemp(prefix="audio-story-clean-machine-"))
    runner: StudioCommandRunner | None = None
    try:
        runner = StudioCommandRunner(workspace, canonical)
        submitted = runner.submit_stage1(
            {
                "profile": "YOUTH_SAFE",
                "language": "vi",
                "duration_minutes": 12,
                "seed": 24,
                "title": "Clean machine smoke",
            }
        )
        deadline = time.monotonic() + 30
        job = runner.get_job(str(submitted["id"]))
        while job["status"] in {"QUEUED", "RUNNING"} and time.monotonic() < deadline:
            time.sleep(0.05)
            job = runner.get_job(str(submitted["id"]))
        checks["sqlite_bootstrap"] = "PASS" if job["status"] == "PASS" else "FAIL"
        checks["stage1_package"] = (
            "PASS"
            if job.get("package_path") and Path(str(job["package_path"])).is_file()
            else "FAIL"
        )
        checks["status"] = "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL"
        print(checks)
        return 0 if checks["status"] == "PASS" else 1
    finally:
        if runner is not None:
            runner.close()
        if not args.keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
