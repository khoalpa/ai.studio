"""Run the explicitly provisioned offline M6-B production transaction."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from audio_story.adapters.image import ImageRequest
from audio_story.adapters.image.comfyui import ComfyUIConfig, ComfyUIImageAdapter
from audio_story.adapters.image.comfyui_provenance import load_provenance
from audio_story.adapters.ocr import TesseractConfig, TesseractOcrAdapter
from audio_story.domain.state import WorkflowStatus
from audio_story.workflows import WorkflowKernel
from audio_story.workflows.image_transaction import (
    ProductionOcrJob,
    ProductionTypographyJob,
    generate_single_image,
)
from audio_story.workflows.typography_production import ProductionTypographyConfig

ROOT = Path(__file__).resolve().parents[1]
FONT = Path(r"C:\Windows\Fonts\DejaVuSans.ttf")
TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
TESSDATA = Path(r"D:\project\ai.player\models\ocr\tessdata_best")
TSV_CONFIG = Path(r"C:\Program Files\Tesseract-OCR\tessdata\configs\tsv")


def main() -> None:
    provenance = load_provenance(ROOT / "docs" / "m6-comfyui-evidence.json")
    ocr = TesseractOcrAdapter(
        TesseractConfig(
            TESSERACT,
            "ccd044d6cf16eaaad151260e1fcc5e3e1504cd1b8644e940b4f7ae3e315dd0d3",
            "tesseract v5.5.0.20241111",
            TESSDATA,
            (("vie", "b6b49293d95d0b6dbd8780174627e82c75be957b6f4ed9862155540d6b00bb45"),),
            tsv_config_path=TSV_CONFIG,
            tsv_config_sha256="59d079bb75d8b3d7c839a3564580cb559e362c93a9d70f234e421c0c3e767e04",
        )
    )
    title = "Chuyện kể đêm nay"
    with tempfile.TemporaryDirectory(prefix="audio-story-m6b-") as directory:
        workspace = Path(directory)
        kernel = WorkflowKernel(workspace / "runtime")
        try:
            workflow = kernel.create_workflow(
                "ADULT_STANDARD", "STAGE2", "CREATE", "a" * 64, "b" * 64
            )
            kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
            stage = kernel.start_stage(workflow, "STAGE2", "c" * 64)
            request = ImageRequest(
                "m6b_production_cover.png",
                sha256(title.encode("utf-8")).hexdigest(),
                provenance.workflow_sha256,
                provenance.model_sha256,
                314159,
                1,
                1024,
                1024,
                "PNG",
                180.0,
                "pending",
                "pending",
            )
            result = generate_single_image(
                kernel,
                stage,
                request,
                ComfyUIImageAdapter(
                    ComfyUIConfig(
                        "http://127.0.0.1:8189",
                        180.0,
                        workflow_path=provenance.workflow_path,
                    )
                ),
                owner_stage="STAGE2",
                artifact_role="LANDSCAPE",
                max_attempts=1,
                typography=ProductionTypographyJob(
                    title,
                    workspace / "cover.png",
                    ProductionTypographyConfig(
                        FONT,
                        "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954",
                        "DejaVu Sans OS-installed",
                        "PROJECT_OWNER_CONFIRMED",
                        64,
                        64,
                    ),
                ),
                ocr=ProductionOcrJob(ocr, ("vie",), title, 0.8),
            )
            evidence = {
                "status": result.status,
                "transaction_id": result.transaction_id,
                "generation_call_id": result.generation_call_id,
                "artifact_id": result.artifact_id,
                "artifact_sha256": result.digest,
                "typography": asdict(result.typography) if result.typography else None,
                "base_ocr": asdict(result.base_ocr) if result.base_ocr else None,
                "final_ocr": asdict(result.final_ocr) if result.final_ocr else None,
                "progress": kernel.progress(stage),
                "failure_code": kernel.db.connection.execute(
                    "SELECT failure_code FROM generation_calls WHERE id=?",
                    (result.generation_call_id,),
                ).fetchone()[0],
            }
            print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
            if result.status != "AUTHORITATIVE" or result.final_ocr is None:
                raise SystemExit(1)
        finally:
            kernel.close()


if __name__ == "__main__":
    main()
