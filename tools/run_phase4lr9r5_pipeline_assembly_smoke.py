from __future__ import annotations

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
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
R4_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r4-component-dry-run-v1/phase4lr9r4-result.json"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r5-pipeline-assembly-smoke-v1"


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def worker() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from diffusers import StableDiffusion3Pipeline
    from diffusers.models.attention_processor import SD3IPAdapterJointAttnProcessor2_0
    from transformers import SiglipImageProcessor, SiglipVisionModel

    started = time.perf_counter()
    pipe = StableDiffusion3Pipeline.from_pretrained(
        LARGE_ROOT,
        local_files_only=True,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
    )
    assembled_seconds = round(time.perf_counter() - started, 2)
    feature_extractor = SiglipImageProcessor.from_pretrained(SIGLIP_ROOT, local_files_only=True)
    image_encoder = SiglipVisionModel.from_pretrained(
        SIGLIP_ROOT,
        local_files_only=True,
        dtype=torch.float16,
        low_cpu_mem_usage=True,
    )
    pipe.register_modules(feature_extractor=feature_extractor, image_encoder=image_encoder)
    pipe.load_ip_adapter(
        ADAPTER_ROOT,
        weight_name="ip-adapter.bin",
        image_encoder_folder=None,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    adapter_processors = [
        processor
        for processor in pipe.transformer.attn_processors.values()
        if isinstance(processor, SD3IPAdapterJointAttnProcessor2_0)
    ]
    registered = {
        name: component.__class__.__name__ if component is not None else None
        for name, component in pipe.components.items()
    }
    pipe.enable_model_cpu_offload(device="cuda")
    hook_modules = []
    for component_name, component in pipe.components.items():
        if hasattr(component, "named_modules"):
            hook_modules.extend(
                f"{component_name}.{name}" if name else component_name
                for name, module in component.named_modules()
                if hasattr(module, "_hf_hook")
            )
    component_devices = {
        name: str(next(component.parameters()).device)
        for name in ("transformer", "vae", "text_encoder", "text_encoder_2", "text_encoder_3", "image_encoder")
        if (component := getattr(pipe, name, None)) is not None
    }
    result = {
        "pipeline_class": pipe.__class__.__name__,
        "assembly_seconds": assembled_seconds,
        "registered_modules": registered,
        "image_encoder_class": pipe.image_encoder.__class__.__name__,
        "feature_extractor_class": pipe.feature_extractor.__class__.__name__,
        "transformer_blocks": len(pipe.transformer.transformer_blocks),
        "ip_adapter_processors": len(adapter_processors),
        "image_projection_class": pipe.transformer.image_proj.__class__.__name__,
        "ip_adapter_active": pipe.is_ip_adapter_active,
        "offload_hook_count": len(hook_modules),
        "offload_hook_modules": hook_modules,
        "execution_device": str(pipe._execution_device),
        "component_devices_after_hook_install": component_devices,
        "cuda_initialized": torch.cuda.is_initialized(),
        "cuda_allocated_mib_before_cleanup": round(torch.cuda.memory_allocated() / 1024**2, 2),
        "inference_calls": 0,
        "latents_created": 0,
        "images_created": 0,
    }
    pipe.maybe_free_model_hooks()
    del adapter_processors, feature_extractor, image_encoder, pipe
    gc.collect()
    torch.cuda.empty_cache()
    result["cuda_allocated_mib_after_cleanup"] = round(torch.cuda.memory_allocated() / 1024**2, 2)
    print(json.dumps(result), flush=True)


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(R4_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS":
        raise RuntimeError("Phase 4L-R9-R4 must pass before pipeline assembly")
    baseline_gpu = gpu_used_mib()
    env = os.environ.copy()
    env.update(
        {
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TRANSFORMERS_VERBOSITY": "error",
            "DIFFUSERS_VERBOSITY": "error",
            "PYTHONUNBUFFERED": "1",
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    root = psutil.Process(process.pid)
    peak_rss = 0
    peak_gpu = baseline_gpu
    while process.poll() is None:
        try:
            tree = [root, *root.children(recursive=True)]
            peak_rss = max(peak_rss, sum(item.memory_info().rss for item in tree if item.is_running()))
            peak_gpu = max(peak_gpu, gpu_used_mib())
        except (psutil.NoSuchProcess, subprocess.CalledProcessError):
            pass
        time.sleep(0.5)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"Pipeline assembly worker failed: {stderr[-8000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"Pipeline worker returned no JSON: {stdout[-4000:]} {stderr[-4000:]}")
    smoke = json.loads(lines[-1])
    smoke["peak_rss_gib"] = round(peak_rss / 1024**3, 2)
    smoke["gpu_baseline_mib"] = baseline_gpu
    smoke["gpu_peak_mib"] = peak_gpu
    smoke["gpu_delta_mib"] = peak_gpu - baseline_gpu
    passed = (
        smoke["pipeline_class"] == "StableDiffusion3Pipeline"
        and smoke["image_encoder_class"] == "SiglipVisionModel"
        and smoke["feature_extractor_class"] == "SiglipImageProcessor"
        and smoke["transformer_blocks"] == 38
        and smoke["ip_adapter_processors"] == 38
        and smoke["image_projection_class"] == "IPAdapterTimeImageProjection"
        and smoke["offload_hook_count"] > 0
        and smoke["inference_calls"] == 0
        and smoke["latents_created"] == 0
        and smoke["images_created"] == 0
        and smoke["cuda_allocated_mib_after_cleanup"] == 0
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R5",
        "status": "PASS" if passed else "FAIL_PIPELINE_ASSEMBLY",
        "smoke": smoke,
        "guards": {
            "isolated_subprocess": True,
            "local_files_only": True,
            "full_pipeline_assembled": True,
            "inference_performed": False,
            "prompt_supplied": False,
            "latents_created": False,
            "image_generated": False,
            "production_profile_changed": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "phase4lr9r5-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
