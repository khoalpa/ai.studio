from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter/ip-adapter.bin")
R3_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r3-sd35-large-filtered-snapshot-v1/phase4lr9r3-result.json"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r4-component-dry-run-v1"


def load_component(name: str) -> dict[str, object]:
    os.environ["HF_HUB_OFFLINE"] = "1"
    started = time.perf_counter()
    if name == "vae":
        from diffusers import AutoencoderKL

        model = AutoencoderKL.from_pretrained(
            LARGE_ROOT, subfolder="vae", local_files_only=True, torch_dtype=torch.float16, low_cpu_mem_usage=True
        )
    elif name == "transformer":
        from diffusers import SD3Transformer2DModel

        model = SD3Transformer2DModel.from_pretrained(
            LARGE_ROOT,
            subfolder="transformer",
            local_files_only=True,
            torch_dtype=torch.float16,
            low_cpu_mem_usage=True,
        )
    elif name in {"text_encoder", "text_encoder_2"}:
        from transformers import CLIPTextModelWithProjection

        model = CLIPTextModelWithProjection.from_pretrained(
            LARGE_ROOT / name, local_files_only=True, dtype=torch.float16, low_cpu_mem_usage=True
        )
    elif name == "text_encoder_3":
        from transformers import T5EncoderModel

        model = T5EncoderModel.from_pretrained(
            LARGE_ROOT / name, local_files_only=True, dtype=torch.float16, low_cpu_mem_usage=True
        )
    elif name == "siglip":
        from transformers import SiglipVisionModel

        model = SiglipVisionModel.from_pretrained(
            SIGLIP_ROOT, local_files_only=True, dtype=torch.float16, low_cpu_mem_usage=True
        )
    elif name == "ip_adapter_mapping":
        from diffusers import SD3Transformer2DModel
        from diffusers.models.attention_processor import SD3IPAdapterJointAttnProcessor2_0

        model = SD3Transformer2DModel.from_pretrained(
            LARGE_ROOT,
            subfolder="transformer",
            local_files_only=True,
            torch_dtype=torch.float16,
            low_cpu_mem_usage=True,
        )
        state = torch.load(ADAPTER, map_location="cpu", weights_only=True)
        model._load_ip_adapter_weights(state, low_cpu_mem_usage=True)
        adapter_layer_ids = sorted({int(key.split(".", maxsplit=1)[0]) for key in state["ip_adapter"]})
        adapter_processors = [
            processor
            for processor in model.attn_processors.values()
            if isinstance(processor, SD3IPAdapterJointAttnProcessor2_0)
        ]
        result = {
            "component": name,
            "class": model.__class__.__name__,
            "dtype": str(next(model.parameters()).dtype),
            "device": str(next(model.parameters()).device),
            "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
            "transformer_blocks": len(model.transformer_blocks),
            "attention_processors": len(model.attn_processors),
            "ip_adapter_processors": len(adapter_processors),
            "non_ip_projection_processors": len(model.attn_processors) - len(adapter_processors),
            "adapter_layer_ids": adapter_layer_ids,
            "complete_layer_coverage": adapter_layer_ids == list(range(38)),
            "image_projection_class": model.image_proj.__class__.__name__,
            "load_seconds": round(time.perf_counter() - started, 2),
            "cuda_initialized": torch.cuda.is_initialized(),
        }
        del state, adapter_layer_ids, adapter_processors, model
        gc.collect()
        return result
    else:
        raise ValueError(f"Unknown component: {name}")

    first_parameter = next(model.parameters())
    result = {
        "component": name,
        "class": model.__class__.__name__,
        "dtype": str(first_parameter.dtype),
        "device": str(first_parameter.device),
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "load_seconds": round(time.perf_counter() - started, 2),
        "cuda_initialized": torch.cuda.is_initialized(),
    }
    if name == "transformer":
        result["transformer_blocks"] = len(model.transformer_blocks)
        result["attention_processors"] = len(model.attn_processors)
    del model
    gc.collect()
    return result


def run_isolated(name: str) -> dict[str, object]:
    env = os.environ.copy()
    env.update({"CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1", "PYTHONUNBUFFERED": "1"})
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--component", name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    child = psutil.Process(process.pid)
    peak_rss = 0
    while process.poll() is None:
        try:
            process_tree = [child, *child.children(recursive=True)]
            rss = sum(item.memory_info().rss for item in process_tree if item.is_running())
            peak_rss = max(peak_rss, rss)
        except psutil.NoSuchProcess:
            break
        time.sleep(0.05)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"{name} failed: {stderr[-4000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"{name} returned no JSON: {stdout[-2000:]} {stderr[-2000:]}")
    result = json.loads(lines[-1])
    result["peak_rss_gib"] = round(peak_rss / 1024**3, 2)
    result["stderr_tail"] = stderr[-500:] if stderr else ""
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", choices=("vae", "transformer", "text_encoder", "text_encoder_2", "text_encoder_3", "siglip", "ip_adapter_mapping"))
    args = parser.parse_args()
    if args.component:
        print(json.dumps(load_component(args.component)))
        return

    prior = json.loads(R3_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS":
        raise RuntimeError("Phase 4L-R9-R3 must pass before component dry-run")
    order = ("vae", "transformer", "text_encoder", "text_encoder_2", "text_encoder_3", "siglip", "ip_adapter_mapping")
    results = []
    for component in order:
        result = run_isolated(component)
        if result["device"] != "cpu" or result["dtype"] != "torch.float16" or result["cuda_initialized"]:
            raise RuntimeError(f"CPU/FP16 guard failed for {component}: {result}")
        results.append(result)
        print(json.dumps(result), flush=True)
    mapping = results[-1]
    mapping_pass = (
        mapping["transformer_blocks"] == 38
        and mapping["ip_adapter_processors"] == 38
        and mapping["complete_layer_coverage"]
        and mapping["image_projection_class"] == "IPAdapterTimeImageProjection"
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R4",
        "status": "PASS" if mapping_pass else "FAIL_IP_ADAPTER_MAPPING",
        "component_loads": results[:-1],
        "ip_adapter_mapping": mapping,
        "guards": {
            "sequential_subprocess_isolation": True,
            "cpu_only": True,
            "fp16": True,
            "full_pipeline_loaded": False,
            "gpu_used": False,
            "image_generated": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "phase4lr9r4-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
