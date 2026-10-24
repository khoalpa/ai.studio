from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import torch
import torch.nn.functional as functional
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
REFERENCE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1/youth-torn-paper-boat/work/characters/bo.png"
R1_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r3r1-ip-adapter-parity-lock-v1/phase4lr9r7r3r1-result.json"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r3r2-latent-resolution-smoke-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r2-result.json"
REFERENCE_CROP_BOX = (384, 0, 1152, 768)
REFERENCE_SHA256 = "5c253d4a48a1e72fa1632be78fdc2ab111a594b8714f4c39af911ab4b4fc3c29"
SEED = 420917


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def tensor_sha256(tensor: torch.Tensor) -> str:
    return hashlib.sha256(tensor.detach().float().cpu().numpy().tobytes()).hexdigest()


def spatial_metrics(tensor: torch.Tensor) -> dict[str, float | bool]:
    value = tensor.detach().float()
    horizontal = (value[..., :, 1:] - value[..., :, :-1]).abs()
    vertical = (value[..., 1:, :] - value[..., :-1, :]).abs()
    row_boundaries = vertical.mean(dim=(0, 1, 3))
    column_boundaries = horizontal.mean(dim=(0, 1, 2))
    row_median = float(row_boundaries.median().item())
    column_median = float(column_boundaries.median().item())
    return {
        "finite": bool(torch.isfinite(value).all().item()),
        "rms": round(float(value.square().mean().sqrt().item()), 8),
        "absolute_mean": round(float(value.abs().mean().item()), 8),
        "horizontal_neighbor_delta_mean": round(float(horizontal.mean().item()), 8),
        "vertical_neighbor_delta_mean": round(float(vertical.mean().item()), 8),
        "vertical_to_horizontal_delta_ratio": round(
            float(vertical.mean().item() / max(horizontal.mean().item(), 1e-12)), 8
        ),
        "max_row_boundary_to_median_ratio": round(
            float(row_boundaries.max().item() / max(row_median, 1e-12)), 8
        ),
        "max_column_boundary_to_median_ratio": round(
            float(column_boundaries.max().item() / max(column_median, 1e-12)), 8
        ),
    }


def token_grid_metrics(tokens: torch.Tensor) -> dict[str, object]:
    count = tokens.shape[1]
    side = int(math.sqrt(count))
    if side * side != count:
        raise RuntimeError(f"Positional token count is not square: {count}")
    grid = tokens.transpose(1, 2).reshape(tokens.shape[0], tokens.shape[2], side, side)
    return {"token_count": count, "grid": [side, side], **spatial_metrics(grid)}


def worker() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from diffusers import StableDiffusion3Pipeline
    from transformers import SiglipImageProcessor, SiglipVisionModel

    pipe = StableDiffusion3Pipeline.from_pretrained(
        LARGE_ROOT,
        local_files_only=True,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    feature_extractor = SiglipImageProcessor.from_pretrained(SIGLIP_ROOT, local_files_only=True)
    image_encoder = SiglipVisionModel.from_pretrained(
        SIGLIP_ROOT,
        local_files_only=True,
        dtype=torch.bfloat16,
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
    pipe.enable_model_cpu_offload(device="cuda")

    forbidden_calls = {"vae": 0, "text_encoder": 0, "text_encoder_2": 0, "text_encoder_3": 0}

    def forbid(name: str):
        def hook(*_args, **_kwargs):
            forbidden_calls[name] += 1
            raise RuntimeError(f"Forbidden {name} call during latent-only smoke")

        return hook

    hooks = []
    for name in forbidden_calls:
        component = getattr(pipe, name)
        hooks.append(component.register_forward_pre_hook(forbid(name)))

    with Image.open(REFERENCE) as source:
        identity_crop = source.convert("RGB").crop(REFERENCE_CROP_BOX)
    ip_embedding = pipe.prepare_ip_adapter_image_embeds(
        ip_adapter_image=identity_crop,
        device=pipe._execution_device,
        num_images_per_prompt=1,
        do_classifier_free_guidance=False,
    ).cpu()
    pipe.maybe_free_model_hooks()

    scheduler = pipe.scheduler
    scheduler.set_timesteps(24, device="cpu")
    timesteps = scheduler.timesteps.detach().float().cpu()
    timestep_index = len(timesteps) // 2
    selected_timestep = timesteps[timestep_index]
    scheduler_evidence = {
        "class": scheduler.__class__.__name__,
        "configured_shift": float(scheduler.config.shift),
        "use_dynamic_shifting": bool(scheduler.config.get("use_dynamic_shifting", False)),
        "step_count": len(timesteps),
        "selected_index": timestep_index,
        "selected_timestep": float(selected_timestep.item()),
        "schedule_sha256": tensor_sha256(timesteps),
        "first_timestep": float(timesteps[0].item()),
        "last_timestep": float(timesteps[-1].item()),
    }

    outputs: dict[str, torch.Tensor] = {}
    runs = []
    transformer_calls = 0
    for resolution in (512, 1024):
        latent_side = resolution // 8
        prompt_generator = torch.Generator(device="cpu").manual_seed(SEED + 1)
        latent_generator = torch.Generator(device="cpu").manual_seed(SEED)
        latent = torch.randn(
            (1, 16, latent_side, latent_side),
            generator=latent_generator,
            dtype=torch.bfloat16,
        )
        prompt = torch.randn(
            (1, 16, 4096), generator=prompt_generator, dtype=torch.bfloat16
        )
        pooled = torch.randn(
            (1, 2048), generator=prompt_generator, dtype=torch.bfloat16
        )
        latent_hash = tensor_sha256(latent)
        for scale in (0.0, 0.5):
            pipe.set_ip_adapter_scale(scale)
            positional = {}

            def capture_positional(_module, _inputs, output):
                positional.update(token_grid_metrics(output))

            position_hook = pipe.transformer.pos_embed.register_forward_hook(capture_positional)
            started = time.perf_counter()
            with torch.inference_mode():
                output = pipe.transformer(
                    hidden_states=latent.to(pipe._execution_device),
                    timestep=selected_timestep.expand(1).to(pipe._execution_device),
                    encoder_hidden_states=prompt.to(pipe._execution_device),
                    pooled_projections=pooled.to(pipe._execution_device),
                    joint_attention_kwargs={
                        "ip_adapter_image_embeds": ip_embedding.to(pipe._execution_device)
                    },
                    return_dict=False,
                )[0].cpu()
            transformer_calls += 1
            position_hook.remove()
            key = f"{resolution}_scale_{scale}"
            outputs[key] = output
            runs.append({
                "resolution": resolution,
                "latent_shape": list(latent.shape),
                "latent_sha256": latent_hash,
                "scale": scale,
                "timestep": float(selected_timestep.item()),
                "forward_seconds": round(time.perf_counter() - started, 3),
                "positional_embedding": positional,
                "output": spatial_metrics(output),
                "output_sha256": tensor_sha256(output),
            })
            print(json.dumps({"progress": key, "forward_calls": transformer_calls}), flush=True)

    comparisons = []
    for resolution in (512, 1024):
        base = outputs[f"{resolution}_scale_0.0"].float()
        conditioned = outputs[f"{resolution}_scale_0.5"].float()
        delta = conditioned - base
        comparisons.append({
            "resolution": resolution,
            "scale_delta_rms": round(float(delta.square().mean().sqrt().item()), 8),
            "scale_delta_absolute_mean": round(float(delta.abs().mean().item()), 8),
            "base_conditioned_cosine": round(float(functional.cosine_similarity(
                base.flatten(), conditioned.flatten(), dim=0
            ).item()), 8),
            "delta_spatial": spatial_metrics(delta),
        })

    for hook in hooks:
        hook.remove()
    pipe.maybe_free_model_hooks()
    del outputs, ip_embedding, identity_crop, feature_extractor, image_encoder, pipe
    gc.collect()
    torch.cuda.empty_cache()
    result = {
        "scheduler": scheduler_evidence,
        "runs": runs,
        "scale_comparisons": comparisons,
        "transformer_forward_calls": transformer_calls,
        "expected_transformer_forward_calls": 4,
        "forbidden_calls": forbidden_calls,
        "vae_decode_calls": 0,
        "denoise_steps": 0,
        "images_created": 0,
        "cuda_allocated_mib_after_cleanup": round(torch.cuda.memory_allocated() / 1024**2, 2),
    }
    print(json.dumps(result), flush=True)


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(R1_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_WITH_GENERATION_BLOCKED":
        raise RuntimeError("R3-R1 parity lock must pass before latent-only smoke")
    if digest(REFERENCE) != REFERENCE_SHA256:
        raise RuntimeError("Locked identity reference changed")
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R2 smoke already exists; refusing to repeat transformer forwards")

    baseline_gpu = gpu_used_mib()
    env = os.environ.copy()
    env.update({
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        "TRANSFORMERS_VERBOSITY": "error",
        "DIFFUSERS_VERBOSITY": "error",
        "PYTHONUNBUFFERED": "1",
    })
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    worker_log_path = OUTPUT_ROOT / "worker.log"
    with worker_log_path.open("w+", encoding="utf-8") as worker_log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            stdout=worker_log,
            stderr=worker_log,
            text=True,
            env=env,
        )
        root = psutil.Process(process.pid)
        peak_rss = 0
        peak_gpu = baseline_gpu
        progress_lines = []
        while process.poll() is None:
            try:
                tree = [root, *root.children(recursive=True)]
                peak_rss = max(peak_rss, sum(item.memory_info().rss for item in tree if item.is_running()))
                peak_gpu = max(peak_gpu, gpu_used_mib())
            except (psutil.NoSuchProcess, subprocess.CalledProcessError):
                pass
            time.sleep(0.5)
        worker_log.flush()
        worker_log.seek(0)
        stdout = worker_log.read()
    if process.returncode != 0:
        raise RuntimeError(f"Latent-only worker failed: {stdout[-12000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"Latent-only worker returned no JSON: {stdout[-4000:]}")
    for line in lines[:-1]:
        progress_lines.append(json.loads(line))
    smoke = json.loads(lines[-1])
    smoke.update({
        "progress_events": progress_lines,
        "peak_rss_gib": round(peak_rss / 1024**3, 2),
        "gpu_baseline_mib": baseline_gpu,
        "gpu_peak_mib": peak_gpu,
        "gpu_delta_mib": peak_gpu - baseline_gpu,
        "gpu_after_worker_exit_mib": gpu_used_mib(),
    })
    runs_finite = all(run["output"]["finite"] for run in smoke["runs"])
    scheduler_same_by_design = smoke["scheduler"]["use_dynamic_shifting"] is False
    exact_call_count = smoke["transformer_forward_calls"] == 4
    forbidden_clear = all(value == 0 for value in smoke["forbidden_calls"].values())
    passed = (
        runs_finite
        and scheduler_same_by_design
        and exact_call_count
        and forbidden_clear
        and smoke["vae_decode_calls"] == 0
        and smoke["denoise_steps"] == 0
        and smoke["images_created"] == 0
    )
    maximum_output_seam_ratio = max(
        max(
            run["output"]["max_row_boundary_to_median_ratio"],
            run["output"]["max_column_boundary_to_median_ratio"],
        )
        for run in smoke["runs"]
    )
    maximum_delta_seam_ratio = max(
        max(
            comparison["delta_spatial"]["max_row_boundary_to_median_ratio"],
            comparison["delta_spatial"]["max_column_boundary_to_median_ratio"],
        )
        for comparison in smoke["scale_comparisons"]
    )
    discontinuity_detected = maximum_output_seam_ratio >= 1.2 or maximum_delta_seam_ratio >= 1.2
    analysis = {
        "status": "NO_SINGLE_FORWARD_DISCONTINUITY" if not discontinuity_detected else "DISCONTINUITY_DETECTED",
        "scheduler_resolution_dependent": not scheduler_same_by_design,
        "maximum_output_seam_ratio": round(maximum_output_seam_ratio, 8),
        "maximum_scale_delta_seam_ratio": round(maximum_delta_seam_ratio, 8),
        "discontinuity_threshold": 1.2,
        "single_forward_implicates_resolution_or_position_embedding": discontinuity_detected,
        "single_forward_implicates_ip_adapter_scale": discontinuity_detected,
        "remaining_paths": ["iterative_denoise_accumulation", "vae_decode"] if not discontinuity_detected else [],
    }
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R2",
        "status": "PASS_NO_SINGLE_FORWARD_DISCONTINUITY" if passed and not discontinuity_detected else ("PASS_DISCONTINUITY_DETECTED" if passed else "FAIL"),
        "smoke": smoke,
        "analysis": analysis,
        "guards": {
            "fixed_seed": SEED,
            "one_forward_per_configuration": exact_call_count,
            "configuration_count": 4,
            "latent_only": True,
            "vae_decode_performed": False,
            "image_generation_performed": False,
            "next_neutral_attempt_authorized": False,
            "climax_generated": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
