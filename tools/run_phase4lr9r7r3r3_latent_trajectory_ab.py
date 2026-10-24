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
import torch.nn.functional as functional
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
REFERENCE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1/youth-torn-paper-boat/work/characters/bo.png"
R2_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r3r2-latent-resolution-smoke-v1/phase4lr9r7r3r2-result.json"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r3r3-latent-trajectory-ab-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r3-result.json"
REFERENCE_CROP_BOX = (384, 0, 1152, 768)
REFERENCE_SHA256 = "5c253d4a48a1e72fa1632be78fdc2ab111a594b8714f4c39af911ab4b4fc3c29"
SEED = 420917
GUIDANCE_SCALE = 5.0
STEPS = 24
PROMPT = (
    "Photorealistic head-and-shoulders documentary portrait of one Vietnamese teenage boy, "
    "matching the reference identity, centered alone against a plain warm gray background, "
    "natural window daylight, neutral calm expression, realistic skin texture, realistic dark hair, "
    "simple plain shirt, camera photograph, 50mm lens, both hands and arms entirely outside the frame."
)
NEGATIVE_PROMPT = (
    "illustration, painting, anime, cartoon, CGI, 3D render, plastic skin, doll, extra person, twins, "
    "visible hands, fingers, props, objects, text, letters, caption, watermark, logo, deformed face, "
    "duplicated face, repeated eyes, repeated mouth, broken neck, extra limbs, malformed anatomy, blur"
)


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


def worker() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from diffusers import StableDiffusion3Pipeline
    from diffusers.schedulers import FlowMatchEulerDiscreteScheduler
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

    forbidden_calls = {"vae": 0}

    def forbid_vae(*_args, **_kwargs):
        forbidden_calls["vae"] += 1
        raise RuntimeError("VAE call is forbidden during latent trajectory smoke")

    vae_hook = pipe.vae.register_forward_pre_hook(forbid_vae)
    prompt_call_counts = {"text_encoder": 0, "text_encoder_2": 0, "text_encoder_3": 0}
    prompt_hooks = []
    for name in prompt_call_counts:
        component = getattr(pipe, name)

        def count_call(_module, _inputs, _name=name):
            prompt_call_counts[_name] += 1

        prompt_hooks.append(component.register_forward_pre_hook(count_call))

    (
        prompt_embedding,
        negative_prompt_embedding,
        pooled_embedding,
        negative_pooled_embedding,
    ) = pipe.encode_prompt(
        prompt=PROMPT,
        prompt_2=PROMPT,
        prompt_3=PROMPT,
        negative_prompt=NEGATIVE_PROMPT,
        negative_prompt_2=NEGATIVE_PROMPT,
        negative_prompt_3=NEGATIVE_PROMPT,
        do_classifier_free_guidance=True,
        device=pipe._execution_device,
        num_images_per_prompt=1,
        max_sequence_length=256,
    )
    prompt_embedding = torch.cat([negative_prompt_embedding, prompt_embedding], dim=0).cpu()
    pooled_embedding = torch.cat([negative_pooled_embedding, pooled_embedding], dim=0).cpu()
    prompt_embedding_shape = list(prompt_embedding.shape)
    pooled_embedding_shape = list(pooled_embedding.shape)
    with Image.open(REFERENCE) as source:
        identity_crop = source.convert("RGB").crop(REFERENCE_CROP_BOX)
    ip_embedding = pipe.prepare_ip_adapter_image_embeds(
        ip_adapter_image=identity_crop,
        device=pipe._execution_device,
        num_images_per_prompt=1,
        do_classifier_free_guidance=True,
    ).cpu()
    ip_embedding_shape = list(ip_embedding.shape)
    pipe.maybe_free_model_hooks()

    initial_generator = torch.Generator(device="cpu").manual_seed(SEED)
    initial_latent = torch.randn(
        (1, 16, 64, 64), generator=initial_generator, dtype=torch.bfloat16
    )
    initial_hash = tensor_sha256(initial_latent)
    trajectories = []
    final_latents: dict[str, torch.Tensor] = {}
    transformer_calls = 0
    for scale in (0.0, 0.5):
        scheduler = FlowMatchEulerDiscreteScheduler.from_config(pipe.scheduler.config)
        scheduler.set_timesteps(STEPS, device="cpu")
        latent = initial_latent.clone()
        pipe.set_ip_adapter_scale(scale)
        steps = []
        trajectory_started = time.perf_counter()
        for index, timestep in enumerate(scheduler.timesteps):
            model_input = torch.cat([latent, latent], dim=0)
            expanded_timestep = timestep.expand(2)
            started = time.perf_counter()
            with torch.inference_mode():
                prediction = pipe.transformer(
                    hidden_states=model_input.to(pipe._execution_device),
                    timestep=expanded_timestep.to(pipe._execution_device),
                    encoder_hidden_states=prompt_embedding.to(pipe._execution_device),
                    pooled_projections=pooled_embedding.to(pipe._execution_device),
                    joint_attention_kwargs={
                        "ip_adapter_image_embeds": ip_embedding.to(pipe._execution_device)
                    },
                    return_dict=False,
                )[0].cpu()
            transformer_calls += 1
            unconditional, conditional = prediction.chunk(2)
            guided = unconditional + GUIDANCE_SCALE * (conditional - unconditional)
            latent = scheduler.step(guided, timestep, latent, return_dict=False)[0]
            metrics = spatial_metrics(latent)
            steps.append({
                "step": index,
                "timestep": float(timestep.item()),
                "sigma": float(scheduler.sigmas[index].item()),
                "forward_seconds": round(time.perf_counter() - started, 3),
                "prediction": spatial_metrics(guided),
                "latent": metrics,
                "latent_sha256": tensor_sha256(latent),
            })
            print(json.dumps({
                "progress": f"scale_{scale}_step_{index + 1}_of_{STEPS}",
                "transformer_calls": transformer_calls,
                "row_seam": metrics["max_row_boundary_to_median_ratio"],
            }), flush=True)
        key = str(scale)
        final_latents[key] = latent.cpu()
        trajectories.append({
            "scale": scale,
            "step_count": len(steps),
            "trajectory_seconds": round(time.perf_counter() - trajectory_started, 3),
            "scheduler_class": scheduler.__class__.__name__,
            "scheduler_shift": float(scheduler.config.shift),
            "schedule_sha256": tensor_sha256(scheduler.timesteps),
            "initial_latent_sha256": initial_hash,
            "final_latent_sha256": tensor_sha256(latent),
            "steps": steps,
        })

    comparisons = []
    base_steps = trajectories[0]["steps"]
    conditioned_steps = trajectories[1]["steps"]
    for base_step, conditioned_step in zip(base_steps, conditioned_steps):
        comparisons.append({
            "step": base_step["step"],
            "timestep": base_step["timestep"],
            "base_row_seam": base_step["latent"]["max_row_boundary_to_median_ratio"],
            "conditioned_row_seam": conditioned_step["latent"]["max_row_boundary_to_median_ratio"],
            "base_vertical_horizontal_ratio": base_step["latent"]["vertical_to_horizontal_delta_ratio"],
            "conditioned_vertical_horizontal_ratio": conditioned_step["latent"]["vertical_to_horizontal_delta_ratio"],
        })
    base_final = final_latents["0.0"].float()
    conditioned_final = final_latents["0.5"].float()
    final_delta = conditioned_final - base_final
    final_comparison = {
        "base_conditioned_cosine": round(float(functional.cosine_similarity(
            base_final.flatten(), conditioned_final.flatten(), dim=0
        ).item()), 8),
        "delta": spatial_metrics(final_delta),
    }
    vae_hook.remove()
    for hook in prompt_hooks:
        hook.remove()
    pipe.maybe_free_model_hooks()
    del final_latents, initial_latent, ip_embedding, prompt_embedding, pooled_embedding
    del feature_extractor, image_encoder, identity_crop, pipe
    gc.collect()
    torch.cuda.empty_cache()
    result = {
        "prompt": PROMPT,
        "negative_prompt": NEGATIVE_PROMPT,
        "seed": SEED,
        "guidance_scale": GUIDANCE_SCALE,
        "resolution": 512,
        "initial_latent_sha256": initial_hash,
        "prompt_embedding_shapes": {
            "sequence": prompt_embedding_shape,
            "pooled": pooled_embedding_shape,
            "ip_adapter": ip_embedding_shape,
        },
        "prompt_encoder_calls": prompt_call_counts,
        "trajectories": trajectories,
        "step_comparisons": comparisons,
        "final_comparison": final_comparison,
        "transformer_forward_calls": transformer_calls,
        "expected_transformer_forward_calls": 48,
        "forbidden_calls": forbidden_calls,
        "vae_decode_calls": 0,
        "images_created": 0,
        "cuda_allocated_mib_after_cleanup": round(torch.cuda.memory_allocated() / 1024**2, 2),
    }
    print(json.dumps(result), flush=True)


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(R2_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_NO_SINGLE_FORWARD_DISCONTINUITY":
        raise RuntimeError("R3-R2 must pass before full latent trajectory smoke")
    if digest(REFERENCE) != REFERENCE_SHA256:
        raise RuntimeError("Locked identity reference changed")
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R3 already exists; refusing to repeat denoise trajectories")

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
        raise RuntimeError(f"Latent trajectory worker failed: {stdout[-12000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"Latent trajectory worker returned no JSON: {stdout[-4000:]}")
    progress = [json.loads(line) for line in lines[:-1]]
    smoke = json.loads(lines[-1])
    smoke.update({
        "progress_event_count": len(progress),
        "peak_rss_gib": round(peak_rss / 1024**3, 2),
        "gpu_baseline_mib": baseline_gpu,
        "gpu_peak_mib": peak_gpu,
        "gpu_delta_mib": peak_gpu - baseline_gpu,
        "gpu_after_worker_exit_mib": gpu_used_mib(),
    })
    all_steps = [step for trajectory in smoke["trajectories"] for step in trajectory["steps"]]
    maximum_latent_seam = max(
        max(
            step["latent"]["max_row_boundary_to_median_ratio"],
            step["latent"]["max_column_boundary_to_median_ratio"],
        )
        for step in all_steps
    )
    maximum_prediction_seam = max(
        max(
            step["prediction"]["max_row_boundary_to_median_ratio"],
            step["prediction"]["max_column_boundary_to_median_ratio"],
        )
        for step in all_steps
    )
    discontinuity_detected = maximum_latent_seam >= 1.2 or maximum_prediction_seam >= 1.2
    exact_calls = smoke["transformer_forward_calls"] == 48
    passed = (
        exact_calls
        and smoke["progress_event_count"] == 48
        and all(step["latent"]["finite"] and step["prediction"]["finite"] for step in all_steps)
        and smoke["forbidden_calls"]["vae"] == 0
        and smoke["vae_decode_calls"] == 0
        and smoke["images_created"] == 0
    )
    analysis = {
        "status": "DENOISE_DISCONTINUITY_DETECTED" if discontinuity_detected else "LATENT_TRAJECTORIES_CLEAN",
        "maximum_latent_seam_ratio": round(maximum_latent_seam, 8),
        "maximum_prediction_seam_ratio": round(maximum_prediction_seam, 8),
        "discontinuity_threshold": 1.2,
        "iterative_denoise_implicated": discontinuity_detected,
        "remaining_path": None if discontinuity_detected else "vae_decode",
    }
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R3",
        "status": "PASS_DENOISE_PATH_IDENTIFIED" if passed and discontinuity_detected else ("PASS_VAE_PATH_REMAINS" if passed else "FAIL"),
        "smoke": smoke,
        "analysis": analysis,
        "guards": {
            "same_initial_latent": True,
            "real_r3_prompt_embeddings": True,
            "exact_transformer_call_budget": exact_calls,
            "vae_decode_performed": False,
            "image_generation_performed": False,
            "next_neutral_attempt_authorized": False,
            "climax_generated": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
