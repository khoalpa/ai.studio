from __future__ import annotations

import gc
import io
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

from ai_story.image_models import resolve_image_model_profile
from ai_story.provider_config import load_provider_config
from ai_story.runtime import GenerationRequest
from ai_story.runtime.diffusers_runtime import DiffusersRuntime

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "depth-controlnet-smoke"
SOURCE = OUTPUT / "bootstrap-source.png"
SIZE = (512, 512)


def depth_image(image: Image.Image, model_id: str) -> Image.Image:
    processor = AutoImageProcessor.from_pretrained(model_id, local_files_only=True)
    model = AutoModelForDepthEstimation.from_pretrained(model_id, local_files_only=True)
    with torch.inference_mode():
        inputs = processor(images=image, return_tensors="pt")
        prediction = model(**inputs).predicted_depth
        prediction = functional.interpolate(
            prediction.unsqueeze(1), size=SIZE[::-1], mode="bicubic", align_corners=False
        ).squeeze()
    low = prediction.min()
    high = prediction.max()
    normalized = (prediction - low) / (high - low).clamp_min(1e-6)
    pixels = (normalized.cpu().numpy() * 255).astype(np.uint8)
    return Image.fromarray(pixels, mode="L").convert("RGB")


def correlation(left: Image.Image, right: Image.Image) -> float:
    a = np.asarray(left.convert("L").resize((64, 64)), dtype=np.float32).reshape(-1)
    b = np.asarray(right.convert("L").resize((64, 64)), dtype=np.float32).reshape(-1)
    a -= a.mean()
    b -= b.mean()
    denominator = math.sqrt(float(np.dot(a, a) * np.dot(b, b)))
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Smoke-test source is missing: {SOURCE}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE).convert("RGB").resize(SIZE, Image.Resampling.LANCZOS)
    source.save(OUTPUT / "source.png")

    config = load_provider_config("local")
    binding = config["adapters"][config["selected"]["landscape"]]
    profile = resolve_image_model_profile(config, binding)
    preprocessor_id = config["runtimes"]["diffusers"]["control_preprocessors"]["depth"]["model"]
    control = depth_image(source, preprocessor_id)
    control.save(OUTPUT / "depth-control.png")

    gc.collect()
    settings = profile.settings(config["runtimes"]["diffusers"])
    settings["local_files_only"] = True
    settings["upscaler"] = {"enabled": False}
    runtime = DiffusersRuntime(settings)
    buffer = io.BytesIO()
    control.save(buffer, format="PNG")
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    generated_bytes = runtime.generate_image(
        GenerationRequest(
            "A cinematic storybook scene of two young friends beside a river at sunrise, "
            "clear foreground subjects, distant hills, warm natural light, detailed digital painting",
            parameters={
                "width": SIZE[0],
                "height": SIZE[1],
                "output_width": SIZE[0],
                "output_height": SIZE[1],
                "seed": 20260929,
                "steps": 12,
                "guidance_scale": 6.0,
                "negative_prompt": "text, watermark, logo, distorted anatomy, blurry",
                "control_inputs": [
                    {"control_type": "depth", "data": buffer.getvalue(), "scale": 0.8}
                ],
            },
        )
    )
    elapsed = time.perf_counter() - started
    generated = Image.open(io.BytesIO(generated_bytes)).convert("RGB")
    generated.save(OUTPUT / "generated.png")
    generated_depth = depth_image(generated, preprocessor_id)
    generated_depth.save(OUTPUT / "generated-depth.png")
    report = {
        "status": "PASS",
        "gpu": torch.cuda.get_device_name(0),
        "cuda": torch.version.cuda,
        "size": list(SIZE),
        "steps": 12,
        "seed": 20260929,
        "controlnet": profile.controlnets["depth"],
        "preprocessor": preprocessor_id,
        "elapsed_seconds": round(elapsed, 2),
        "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
        "peak_reserved_vram_gib": round(torch.cuda.max_memory_reserved() / 2**30, 2),
        "depth_layout_correlation": round(correlation(control, generated_depth), 4),
        "runtime_postprocess": runtime.last_image_metadata,
    }
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
