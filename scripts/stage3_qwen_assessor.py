"""Offline Qwen2.5-VL callable factory for Stage 3 semantic gating."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import torch
from PIL import Image
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration

from audio_story.adapters.image import ImageRequest
from audio_story.workflows.image_transaction import SemanticImageGateResult


def build_assessor(model_path: Path):
    processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
    quant = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16
    )
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_path, quantization_config=quant, device_map="auto", local_files_only=True
    )

    def assess(data: bytes, request: ImageRequest) -> SemanticImageGateResult:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            prompt = (
                "Return JSON only with keys status, observable_findings, hard_failures, "
                "rationale. status must be PASS or FAIL. Assess this exact Stage 3 "
                "portrait basename: " + request.basename
            )
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            text = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = processor(text=[text], images=[image], padding=True, return_tensors="pt")
        inputs = {
            key: value.to(model.device) if hasattr(value, "to") else value
            for key, value in inputs.items()
        }
        output = model.generate(**inputs, max_new_tokens=256, do_sample=False)
        raw = processor.batch_decode(
            output[:, inputs["input_ids"].shape[1] :], skip_special_tokens=True
        )[0].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        assessment: dict[str, Any] = json.loads(raw)
        if assessment.get("status") not in {"PASS", "FAIL"}:
            raise ValueError("invalid semantic status")
        evidence = {
            "image_sha256": hashlib.sha256(data).hexdigest(),
            "basename": request.basename,
            "assessment": assessment,
        }
        return SemanticImageGateResult(
            assessment["status"], evidence, "Qwen2.5-VL-7B-Instruct", "offline-local-1.0"
        )

    return assess
