"""Resume a text-complete Stage 1 workspace through local character authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from audio_story.adapters.image import ComfyUIConfig, ComfyUIImageAdapter, ImageRequest
from audio_story.adapters.image.comfyui_provenance import load_provenance
from audio_story.adapters.llm import LlamaCppAdapter, LlamaCppConfig
from audio_story.adapters.llm.mock import DeterministicMockAdapter
from audio_story.domain.stage1 import Stage1Request
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage1 import final_script_digest
from audio_story.validation.strict_json import parse_json_bytes
from audio_story.workflows import Stage1Service, WorkflowKernel
from audio_story.workflows.image_transaction import SemanticImageGateResult
from audio_story.workflows.stage1_characters import CharacterImageConfig
from audio_story.workflows.story_quality_assessor import assess_story

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--stage-id", required=True)
    parser.add_argument("--vlm-model", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8189")
    parser.add_argument(
        "--canonical", type=Path, default=ROOT / "canonical" / "ChatGPT_prompt_v3.16.13.txt"
    )
    args = parser.parse_args()
    provenance = load_provenance(ROOT / "docs" / "m6-comfyui-evidence.json")
    kernel = WorkflowKernel(args.workspace)
    try:
        row = kernel.db.connection.execute(
            "SELECT a.sha256 FROM asset_transactions t "
            "JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
            "JOIN artifacts a ON a.id=b.artifact_id "
            "WHERE t.stage_run_id=? AND t.basename='serialize.json'",
            (args.stage_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("committed serialize.json is required")
        serialized = parse_json_bytes(
            kernel.store.get_artifact_by_digest(str(row["sha256"])),
            "serialize.json",
            engine_generated=True,
        ).value
        character = serialized["payload"]["story"]["characters"][0]

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
                            "description": character["description"],
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
                        str(args.vlm_model),
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

        config = CharacterImageConfig(
            ComfyUIImageAdapter(
                ComfyUIConfig(args.endpoint, 300.0, workflow_path=provenance.workflow_path)
            ),
            provenance.workflow_sha256,
            provenance.model_sha256,
            300.0,
            assess,
        )
        result = Stage1Service(
            kernel,
            DeterministicMockAdapter(),
            args.canonical,
            character_image_config=config,
            story_quality_assessor=lambda story_bytes, assets: assess_story(
                LlamaCppAdapter(LlamaCppConfig(timeout_seconds=180.0)),
                story_bytes,
                script_digest=final_script_digest(json.loads(story_bytes)["script"]),
                asset_set_digest=sha256_bytes(
                    canonical_json_bytes([[p, sha256_bytes(b)] for p, b in assets.items()])
                ),
            ),
        ).resume_recovery(
            args.workflow_id,
            args.stage_id,
            Stage1Request(
                "YOUTH_SAFE",
                duration_minutes=12,
                duration_confirmed=True,
                seed=1702,
                title=str(serialized["payload"]["story"]["title"]),
            ),
        )
        evidence = {
            "status": result.status,
            "reason_code": result.reason_code,
            "workflow_id": result.workflow_id,
            "stage_id": result.stage_id,
            "progress": kernel.progress(result.stage_id),
        }
        print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
        return 0 if result.reason_code == "S147_PRODUCTION_QUALITY_EVIDENCE_REQUIRED" else 1
    finally:
        kernel.close()


if __name__ == "__main__":
    raise SystemExit(main())
