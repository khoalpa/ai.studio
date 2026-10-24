from __future__ import annotations

import gc
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import torch
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
REFERENCE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1/youth-torn-paper-boat/work/characters/bo.png"
R5_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r5-pipeline-assembly-smoke-v1/phase4lr9r5-result.json"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r6-reference-embedding-smoke-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    from transformers import SiglipImageProcessor, SiglipVisionModel

    pipe = StableDiffusion3Pipeline.from_pretrained(
        LARGE_ROOT,
        local_files_only=True,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
    )
    feature_extractor = SiglipImageProcessor.from_pretrained(SIGLIP_ROOT, local_files_only=True)
    image_encoder = SiglipVisionModel.from_pretrained(
        SIGLIP_ROOT, local_files_only=True, dtype=torch.float16, low_cpu_mem_usage=True
    )
    pipe.register_modules(feature_extractor=feature_extractor, image_encoder=image_encoder)
    pipe.load_ip_adapter(
        ADAPTER_ROOT,
        weight_name="ip-adapter.bin",
        image_encoder_folder=None,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    pipe.enable_model_cpu_offload(device="cuda")

    forbidden_calls = {"transformer": 0, "vae": 0}

    def forbid(name: str):
        def hook(*_args, **_kwargs):
            forbidden_calls[name] += 1
            raise RuntimeError(f"Forbidden {name} forward call during embedding-only smoke")

        return hook

    transformer_hook = pipe.transformer.register_forward_pre_hook(forbid("transformer"))
    vae_hook = pipe.vae.register_forward_pre_hook(forbid("vae"))
    with Image.open(REFERENCE) as source:
        reference_size = list(source.size)
        reference_mode = source.mode
        image = source.convert("RGB")
    started = time.perf_counter()
    embeds = pipe.prepare_ip_adapter_image_embeds(
        ip_adapter_image=image,
        device=pipe._execution_device,
        num_images_per_prompt=1,
        do_classifier_free_guidance=True,
    )
    embedding_seconds = round(time.perf_counter() - started, 3)
    negative, positive = embeds.chunk(2)
    embedding_shape = list(embeds.shape)
    embedding_dtype = str(embeds.dtype)
    embedding_device = str(embeds.device)
    positive_finite = bool(torch.isfinite(positive).all().item())
    positive_nonzero = bool(torch.count_nonzero(positive).item() > 0)
    positive_abs_mean = round(float(positive.abs().float().mean().item()), 6)
    negative_is_zero = bool(torch.count_nonzero(negative).item() == 0)
    del negative, positive
    embeds_cpu = embeds.cpu()
    del embeds
    gc.collect()
    pipe.maybe_free_model_hooks()
    image_encoder_device_after_offload = str(next(pipe.image_encoder.parameters()).device)
    result = {
        "reference_path": str(REFERENCE.resolve()),
        "reference_sha256": sha256(REFERENCE),
        "reference_size": reference_size,
        "reference_mode": reference_mode,
        "processor_class": pipe.feature_extractor.__class__.__name__,
        "encoder_class": pipe.image_encoder.__class__.__name__,
        "embedding_shape": embedding_shape,
        "embedding_dtype": embedding_dtype,
        "embedding_device": embedding_device,
        "embedding_seconds": embedding_seconds,
        "positive_finite": positive_finite,
        "positive_nonzero": positive_nonzero,
        "positive_abs_mean": positive_abs_mean,
        "negative_is_zero": negative_is_zero,
        "classifier_free_guidance_pair": embedding_shape[0] == 2,
        "image_encoder_device_after_offload": image_encoder_device_after_offload,
        "transformer_forward_calls": forbidden_calls["transformer"],
        "vae_forward_calls": forbidden_calls["vae"],
        "cuda_max_allocated_mib": round(torch.cuda.max_memory_allocated() / 1024**2, 2),
        "latents_created": 0,
        "images_created": 0,
    }
    transformer_hook.remove()
    vae_hook.remove()
    del embeds_cpu, image
    del feature_extractor, image_encoder, pipe
    gc.collect()
    torch.cuda.empty_cache()
    result["cuda_allocated_mib_after_cleanup"] = round(torch.cuda.memory_allocated() / 1024**2, 2)
    print(json.dumps(result), flush=True)


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(R5_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS":
        raise RuntimeError("Phase 4L-R9-R5 must pass before reference embedding smoke")
    expected_reference_hash = "5c253d4a48a1e72fa1632be78fdc2ab111a594b8714f4c39af911ab4b4fc3c29"
    if not REFERENCE.is_file() or sha256(REFERENCE) != expected_reference_hash:
        raise RuntimeError("Locked reference image is missing or changed")

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
        raise RuntimeError(f"Reference embedding worker failed: {stderr[-8000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"Reference embedding worker returned no JSON: {stdout[-4000:]} {stderr[-4000:]}")
    smoke = json.loads(lines[-1])
    smoke["peak_rss_gib"] = round(peak_rss / 1024**3, 2)
    smoke["gpu_baseline_mib"] = baseline_gpu
    smoke["gpu_peak_mib"] = peak_gpu
    smoke["gpu_delta_mib"] = peak_gpu - baseline_gpu
    smoke["gpu_after_worker_exit_mib"] = gpu_used_mib()
    passed = (
        smoke["reference_sha256"] == expected_reference_hash
        and smoke["processor_class"] == "SiglipImageProcessor"
        and smoke["encoder_class"] == "SiglipVisionModel"
        and smoke["embedding_dtype"] == "torch.float16"
        and smoke["embedding_shape"][0] == 2
        and smoke["embedding_shape"][-1] == 1152
        and smoke["positive_finite"]
        and smoke["positive_nonzero"]
        and smoke["negative_is_zero"]
        and smoke["image_encoder_device_after_offload"] == "cpu"
        and smoke["transformer_forward_calls"] == 0
        and smoke["vae_forward_calls"] == 0
        and smoke["latents_created"] == 0
        and smoke["images_created"] == 0
        and smoke["cuda_allocated_mib_after_cleanup"] <= 16
        and smoke["gpu_after_worker_exit_mib"] <= baseline_gpu + 2
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R6",
        "status": "PASS" if passed else "FAIL_REFERENCE_EMBEDDING",
        "smoke": smoke,
        "guards": {
            "isolated_subprocess": True,
            "transformer_called": False,
            "vae_called": False,
            "denoise_performed": False,
            "latents_created": False,
            "image_generated": False,
            "production_profile_changed": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "phase4lr9r6-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
