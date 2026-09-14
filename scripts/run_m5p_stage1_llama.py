"""Run the live five-phase Stage 1 route against an already provisioned llama.cpp server."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path

from audio_story.adapters.llm import LlamaCppAdapter, LlamaCppConfig
from audio_story.domain.stage1 import Stage1Request
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage1 import final_script_digest
from audio_story.workflows import WorkflowKernel
from audio_story.workflows.stage1 import Stage1Service
from audio_story.workflows.story_quality_assessor import assess_story


def wait_health(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("llama.cpp health timeout")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llama-server", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument(
        "--canonical", type=Path, default=Path("canonical/ChatGPT_prompt_v3.16.13.txt")
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--workflow-id")
    parser.add_argument("--stage-id")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    process = subprocess.Popen(
        [
            str(args.llama_server),
            "-m",
            str(args.model),
            "--host",
            "127.0.0.1",
            "--port",
            "8080",
            "-ngl",
            "99",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    kernel = WorkflowKernel(args.workspace)
    try:
        wait_health("http://127.0.0.1:8080/health", 60.0)
        service = Stage1Service(
            kernel,
            LlamaCppAdapter(LlamaCppConfig(timeout_seconds=args.timeout)),
            args.canonical,
            story_quality_assessor=lambda story_bytes, assets: assess_story(
                LlamaCppAdapter(LlamaCppConfig(timeout_seconds=args.timeout)),
                story_bytes,
                script_digest=final_script_digest(json.loads(story_bytes)["script"]),
                asset_set_digest=sha256_bytes(
                    canonical_json_bytes(
                        [[path, sha256_bytes(data)] for path, data in assets.items()]
                    )
                ),
            ),
        )
        request = Stage1Request(
            "YOUTH_SAFE",
            duration_minutes=12,
            duration_confirmed=True,
            seed=1702,
            title="Ngọn Đèn Sau Mưa",
        )
        if (args.workflow_id is None) != (args.stage_id is None):
            raise ValueError("--workflow-id and --stage-id must be supplied together")
        result = (
            service.resume_recovery(args.workflow_id, args.stage_id, request)
            if args.workflow_id is not None and args.stage_id is not None
            else service.start(request)
        )
        evidence = {
            "status": result.status,
            "reason_code": result.reason_code,
            "workflow_id": result.workflow_id,
            "stage_id": result.stage_id,
            "progress": kernel.progress(result.stage_id),
        }
        print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
        return 0 if result.reason_code == "S144_CHARACTER_REFERENCE_PRODUCTION_REQUIRED" else 1
    finally:
        kernel.close()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
