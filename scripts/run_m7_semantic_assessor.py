"""Run a strict offline Qwen2.5-VL assessment for one Stage 2 PNG."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--asset-record", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image_bytes = args.image.read_bytes()
    asset = json.loads(args.asset_record.read_text(encoding="utf-8"))
    prompt = (
        "Assess this exact Stage 2 landscape image against the supplied asset record. "
        "Return JSON only with keys status, method, observable_findings, hard_failures, "
        "and rationale. status must be PASS or FAIL. Do not infer hidden facts. "
        "Do not treat metadata as visual evidence. Asset record: "
        + json.dumps(asset, ensure_ascii=False, separators=(",", ":"))
    )
    processor = AutoProcessor.from_pretrained(args.model, local_files_only=True)
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        args.model,
        quantization_config=quantization,
        device_map="auto",
        local_files_only=True,
    )
    with Image.open(args.image) as image:
        image = image.convert("RGB")
        messages = [
            {
                "role": "user",
                "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}],
            }
        ]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], images=[image], padding=True, return_tensors="pt")
    inputs = {
        key: value.to(model.device) if hasattr(value, "to") else value
        for key, value in inputs.items()
    }
    generated = model.generate(**inputs, max_new_tokens=256, do_sample=False)
    output_tokens = generated[:, inputs["input_ids"].shape[1] :]
    raw = processor.batch_decode(output_tokens, skip_special_tokens=True)[0].strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".raw.txt").write_text(raw, encoding="utf-8")
    candidate = raw
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    parsed = json.loads(candidate)
    if set(parsed) != {"status", "method", "observable_findings", "hard_failures", "rationale"}:
        raise ValueError("assessor output keys are not exact")
    evidence = {"image_sha256": hashlib.sha256(image_bytes).hexdigest(), "assessment": parsed}
    evidence["evidence_digest_sha256"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": parsed["status"],
                "evidence_digest_sha256": evidence["evidence_digest_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
