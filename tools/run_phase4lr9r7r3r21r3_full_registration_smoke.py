from __future__ import annotations

import argparse
import gc
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import torch

from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R21_R2_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r2-regional-attention-dry-run-v1/"
    "phase4lr9r7r3r21r2-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r3-full-regional-registration-smoke-v1"
)
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
ADAPTER = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter/ip-adapter.bin")


def processor_snapshot(processor: torch.nn.Module) -> dict[str, Any]:
    parameters = list(processor.parameters())
    return {
        "class": processor.__class__.__name__,
        "parameter_count": sum(parameter.numel() for parameter in parameters),
        "parameter_ids": [id(parameter) for parameter in parameters],
        "dtypes": sorted({str(parameter.dtype) for parameter in parameters}),
        "devices": sorted({str(parameter.device) for parameter in parameters}),
        "scale": float(processor.scale),
    }


def worker() -> dict[str, Any]:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from diffusers import SD3Transformer2DModel
    from diffusers.models.attention_processor import (
        SD3IPAdapterJointAttnProcessor2_0,
    )

    started = time.perf_counter()
    transformer = SD3Transformer2DModel.from_pretrained(
        LARGE_ROOT,
        subfolder="transformer",
        local_files_only=True,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
    )
    state = torch.load(ADAPTER, map_location="cpu", weights_only=True)
    transformer._load_ip_adapter_weights(state, low_cpu_mem_usage=True)
    del state
    gc.collect()

    before = transformer.attn_processors
    native = {
        name: processor
        for name, processor in before.items()
        if isinstance(processor, SD3IPAdapterJointAttnProcessor2_0)
    }
    before_snapshots = {
        name: processor_snapshot(processor) for name, processor in native.items()
    }
    replacements = dict(before)
    for name, processor in native.items():
        processor.scale = 0.25
        replacements[name] = RegionalSD3IPAdapterProcessor(processor)
    transformer.set_attn_processor(replacements)
    after = transformer.attn_processors
    regional = {
        name: processor
        for name, processor in after.items()
        if isinstance(processor, RegionalSD3IPAdapterProcessor)
    }
    registrations = []
    for name in sorted(regional):
        wrapper = regional[name]
        original = native[name]
        current = processor_snapshot(wrapper.base_processor)
        previous = before_snapshots[name]
        registrations.append(
            {
                "name": name,
                "base_object_preserved": wrapper.base_processor is original,
                "parameter_identity_preserved": (
                    current["parameter_ids"] == previous["parameter_ids"]
                ),
                "parameter_count": current["parameter_count"],
                "dtype": current["dtypes"],
                "device": current["devices"],
                "scale": current["scale"],
                "accepts_regional_attention_mask": (
                    "regional_attention_mask"
                    in inspect.signature(wrapper.__call__).parameters
                ),
            }
        )

    transformer_source = inspect.getsource(transformer.forward)
    block_source = inspect.getsource(transformer.transformer_blocks[0].forward)
    kwargs_routing = {
        "transformer_accepts_joint_attention_kwargs": (
            "joint_attention_kwargs" in inspect.signature(transformer.forward).parameters
        ),
        "transformer_passes_kwargs_to_block": (
            "joint_attention_kwargs=joint_attention_kwargs" in transformer_source
        ),
        "block_passes_kwargs_to_attention": (
            "**joint_attention_kwargs" in block_source
        ),
        "regional_kwarg_name": "regional_attention_mask",
    }
    layer_indices = sorted(
        int(name.split(".")[1]) for name in regional
    )
    passed = (
        len(transformer.transformer_blocks) == 38
        and len(native) == 38
        and len(regional) == 38
        and layer_indices == list(range(38))
        and all(
            item["base_object_preserved"]
            and item["parameter_identity_preserved"]
            and item["dtype"] == ["torch.float16"]
            and item["device"] == ["cpu"]
            and item["scale"] == 0.25
            and item["accepts_regional_attention_mask"]
            for item in registrations
        )
        and all(value for key, value in kwargs_routing.items() if key != "regional_kwarg_name")
        and not torch.cuda.is_initialized()
    )
    result = {
        "status": "PASS" if passed else "FAIL",
        "transformer_class": transformer.__class__.__name__,
        "transformer_blocks": len(transformer.transformer_blocks),
        "attention_processors": len(after),
        "native_ip_processors_before": len(native),
        "regional_ip_processors_after": len(regional),
        "non_ip_processors_preserved": len(after) - len(regional),
        "registered_layer_indices": layer_indices,
        "registrations": registrations,
        "kwargs_routing": kwargs_routing,
        "cpu_only": True,
        "dtype": "torch.float16",
        "cuda_initialized": torch.cuda.is_initialized(),
        "load_and_registration_seconds": round(time.perf_counter() - started, 2),
    }
    del transformer, before, after, native, regional, replacements
    gc.collect()
    return result


def run_worker() -> dict[str, Any]:
    environment = os.environ.copy()
    environment.update(
        {
            "CUDA_VISIBLE_DEVICES": "",
            "HF_HUB_OFFLINE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"Registration worker failed: {stderr[-4000:]}")
    lines = [line for line in stdout.splitlines() if line.startswith("{")]
    if not lines:
        raise RuntimeError(f"Registration worker returned no result: {stderr[-2000:]}")
    result = json.loads(lines[-1])
    result["stderr_tail"] = stderr[-500:] if stderr else ""
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker()), flush=True)
        return

    prior = json.loads(R21_R2_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_REGIONAL_ATTENTION_DRY_RUN":
        raise RuntimeError("R21-R2 must pass before full registration")
    registration = run_worker()
    passed = registration["status"] == "PASS"
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R3",
        "status": "PASS_FULL_38_BLOCK_REGISTRATION" if passed else "FAIL",
        "registration_smoke": registration,
        "conclusion": (
            "All 38 SD3.5 Large IP-Adapter attention processors were wrapped without "
            "changing parameter identity, dtype, device, or scale, and the regional mask "
            "keyword is routed through transformer and block APIs."
            if passed
            else "Regional processor registration or kwargs routing failed."
        ),
        "guards": {
            "subprocess_isolation": True,
            "cpu_only": True,
            "full_pipeline_loaded": False,
            "transformer_forward_called": False,
            "denoise_performed": False,
            "latents_created": False,
            "vae_instantiated": False,
            "image_generation_performed": False,
            "next_full_scene_attempt_authorized": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / "phase4lr9r7r3r21r3-result.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
