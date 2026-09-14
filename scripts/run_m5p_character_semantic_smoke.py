"""Run one production character transaction with a precommit local VLM gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from audio_story.adapters.image import ComfyUIConfig, ComfyUIImageAdapter, ImageRequest
from audio_story.adapters.image.comfyui_provenance import load_provenance
from audio_story.domain.state import WorkflowStatus
from audio_story.workflows import WorkflowKernel
from audio_story.workflows.image_transaction import SemanticImageGateResult
from audio_story.workflows.stage1_characters import (
    CharacterImageConfig,
    generate_character_reference,
)

ROOT = Path(__file__).resolve().parents[1]


def wait_for_comfy(endpoint: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(endpoint + "/system_stats", timeout=3) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1.0)
    raise RuntimeError("ComfyUI health timeout")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8189")
    parser.add_argument("--seed", type=int, default=1701)
    args = parser.parse_args()
    wait_for_comfy(args.endpoint)
    provenance = load_provenance(ROOT / "docs" / "m6-comfyui-evidence.json")
    character = {
        "character_id": "char_001",
        "name": "An",
        "age": 30,
        "role": "protagonist",
        "description": "Vietnamese woman investigator, dark blue coat, calm observant expression",
    }

    def assess(data: bytes, request: ImageRequest) -> SemanticImageGateResult:
        urllib.request.urlopen(
            urllib.request.Request(
                args.endpoint + "/free",
                data=b'{"unload_models":true,"free_memory":true}',
                method="POST",
                headers={"Content-Type": "application/json"},
            ),
            timeout=30,
        ).read()
        with tempfile.TemporaryDirectory(prefix="m5p-character-assess-") as directory:
            temporary = Path(directory)
            image = temporary / "character.png"
            record = temporary / "record.json"
            output = temporary / "assessment.json"
            image.write_bytes(data)
            record.write_text(
                json.dumps(
                    {
                        "asset_role": "single character identity reference",
                        "character_id": character["character_id"],
                        "required": [
                            "exactly one visible person",
                            "full body visible from head through feet",
                            "plain background",
                            "no text or watermark",
                            "usable stable face and clothing identity",
                        ],
                        "hard_failures": [
                            "multiple people or duplicate body",
                            "cropped head or feet",
                            "unreadable face",
                            "text or watermark",
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_m7_semantic_assessor.py"),
                    str(image),
                    "--model",
                    str(args.model),
                    "--asset-record",
                    str(record),
                    "--output",
                    str(output),
                ],
                check=True,
            )
            evidence = json.loads(output.read_text(encoding="utf-8"))
        assessment = evidence["assessment"]
        return SemanticImageGateResult(
            assessment["status"],
            {
                "image_sha256": hashlib.sha256(data).hexdigest(),
                "assessment": assessment,
                "evidence_digest_sha256": evidence["evidence_digest_sha256"],
            },
            "Qwen2.5-VL-7B-Instruct",
            "M5P-CHARACTER-VLM-1.0",
        )

    kernel = WorkflowKernel(args.workspace)
    try:
        workflow = kernel.create_workflow("ADULT_STANDARD", "STAGE1", "CREATE", "a" * 64, "b" * 64)
        kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
        stage = kernel.start_stage(workflow, "STAGE1", "c" * 64)
        result = generate_character_reference(
            kernel,
            stage,
            character,
            "c" * 64,
            args.seed,
            CharacterImageConfig(
                ComfyUIImageAdapter(
                    ComfyUIConfig(args.endpoint, 300.0, workflow_path=provenance.workflow_path)
                ),
                provenance.workflow_sha256,
                provenance.model_sha256,
                300.0,
                assess,
            ),
        )
        evidence = {
            "status": result.status,
            "workflow_id": workflow,
            "stage_id": stage,
            "transaction_id": result.transaction_id,
            "generation_call_id": result.generation_call_id,
            "artifact_id": result.artifact_id,
            "artifact_sha256": result.digest,
            "calls": [
                dict(row)
                for row in kernel.db.connection.execute(
                    "SELECT attempt_index,status,failure_code,response_digest "
                    "FROM generation_calls "
                    "ORDER BY attempt_index"
                )
            ],
        }
        evidence["status_normalized"] = str(result.status)
        print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
        return 0 if str(result.status) == "AUTHORITATIVE" else 1
    finally:
        kernel.close()


if __name__ == "__main__":
    raise SystemExit(main())
