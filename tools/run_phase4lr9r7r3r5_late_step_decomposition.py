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
from PIL import Image
from run_phase4lr9r7r3r3_latent_trajectory_ab import (
    ADAPTER_ROOT,
    GUIDANCE_SCALE,
    LARGE_ROOT,
    NEGATIVE_PROMPT,
    PROMPT,
    REFERENCE,
    REFERENCE_CROP_BOX,
    REFERENCE_SHA256,
    SEED,
    SIGLIP_ROOT,
    STEPS,
    digest,
    gpu_used_mib,
    spatial_metrics,
    tensor_sha256,
)
from run_phase4lr9r7r3r4_late_tail_isolation import FORK_INDEX, run_prediction

PROJECT_ROOT = Path(__file__).resolve().parents[1]
R4_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r4-late-tail-isolation-v1/phase4lr9r7r3r4-result.json"
)
OUTPUT_ROOT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r5-late-step-decomposition-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r5-result.json"
EXPECTED_FORWARD_CALLS = STEPS
RATIO_THRESHOLD = 1.2


def axis_profile(values: torch.Tensor) -> dict:
    values = values.detach().float().cpu()
    median = values.median()
    deviations = (values - median).abs()
    mad = deviations.median()
    maximum, index = values.max(dim=0)
    denominator = max(float(median.item()), 1e-12)
    robust_denominator = max(1.4826 * float(mad.item()), 1e-12)
    return {
        "values": [round(float(value), 8) for value in values.tolist()],
        "maximum": round(float(maximum.item()), 8),
        "maximum_index": int(index.item()),
        "median": round(float(median.item()), 8),
        "mad": round(float(mad.item()), 8),
        "maximum_to_median_ratio": round(
            float(maximum.item()) / denominator, 8
        ),
        "maximum_robust_z": round(
            (float(maximum.item()) - float(median.item()))
            / robust_denominator,
            8,
        ),
    }


def boundary_diagnostics(tensor: torch.Tensor) -> dict:
    value = tensor.detach().float()
    horizontal = (value[..., :, 1:] - value[..., :, :-1]).abs()
    vertical = (value[..., 1:, :] - value[..., :-1, :]).abs()
    return {
        "row_boundaries": axis_profile(vertical.mean(dim=(0, 1, 3))),
        "column_boundaries": axis_profile(horizontal.mean(dim=(0, 1, 2))),
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
    feature_extractor = SiglipImageProcessor.from_pretrained(
        SIGLIP_ROOT, local_files_only=True
    )
    image_encoder = SiglipVisionModel.from_pretrained(
        SIGLIP_ROOT,
        local_files_only=True,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    pipe.register_modules(
        feature_extractor=feature_extractor, image_encoder=image_encoder
    )
    pipe.load_ip_adapter(
        ADAPTER_ROOT,
        weight_name="ip-adapter.bin",
        image_encoder_folder=None,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    pipe.enable_model_cpu_offload(device="cuda")
    pipe.set_ip_adapter_scale(0.0)

    forbidden_calls = {"vae": 0}

    def forbid_vae(*_args, **_kwargs):
        forbidden_calls["vae"] += 1
        raise RuntimeError("VAE call is forbidden during late-step decomposition")

    vae_hook = pipe.vae.register_forward_pre_hook(forbid_vae)
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
    prompt_embedding = torch.cat(
        [negative_prompt_embedding, prompt_embedding], dim=0
    ).cpu()
    pooled_embedding = torch.cat(
        [negative_pooled_embedding, pooled_embedding], dim=0
    ).cpu()
    with Image.open(REFERENCE) as source:
        identity_crop = source.convert("RGB").crop(REFERENCE_CROP_BOX)
    ip_embedding = pipe.prepare_ip_adapter_image_embeds(
        ip_adapter_image=identity_crop,
        device=pipe._execution_device,
        num_images_per_prompt=1,
        do_classifier_free_guidance=True,
    ).cpu()
    pipe.maybe_free_model_hooks()

    generator = torch.Generator(device="cpu").manual_seed(SEED)
    latent = torch.randn(
        (1, 16, 64, 64), generator=generator, dtype=torch.bfloat16
    )
    initial_hash = tensor_sha256(latent)
    scheduler = FlowMatchEulerDiscreteScheduler.from_config(pipe.scheduler.config)
    scheduler.set_timesteps(STEPS, device="cpu")
    transformer_calls = 0
    prefix_hashes = []
    tail_steps = []

    for index, timestep in enumerate(scheduler.timesteps):
        started = time.perf_counter()
        prediction = run_prediction(
            pipe,
            latent,
            timestep,
            prompt_embedding,
            pooled_embedding,
            ip_embedding,
        )
        transformer_calls += 1
        unconditional, conditional = prediction.chunk(2)
        guided = unconditional + GUIDANCE_SCALE * (
            conditional - unconditional
        )
        before = latent
        after = scheduler.step(
            guided, timestep, before, return_dict=False
        )[0]
        if index < FORK_INDEX:
            prefix_hashes.append(tensor_sha256(after))
        else:
            update_delta = after.float() - before.float()
            sigma = float(scheduler.sigmas[index].item())
            next_sigma = float(scheduler.sigmas[index + 1].item())
            tail_steps.append(
                {
                    "step": index,
                    "timestep": float(timestep.item()),
                    "sigma": sigma,
                    "next_sigma": next_sigma,
                    "sigma_delta": next_sigma - sigma,
                    "forward_seconds": round(
                        time.perf_counter() - started, 3
                    ),
                    "latent_before": {
                        "summary": spatial_metrics(before),
                        "boundaries": boundary_diagnostics(before),
                    },
                    "unconditional_prediction": {
                        "summary": spatial_metrics(unconditional),
                        "boundaries": boundary_diagnostics(unconditional),
                    },
                    "conditional_prediction": {
                        "summary": spatial_metrics(conditional),
                        "boundaries": boundary_diagnostics(conditional),
                    },
                    "guided_prediction": {
                        "summary": spatial_metrics(guided),
                        "boundaries": boundary_diagnostics(guided),
                    },
                    "scheduler_update_delta": {
                        "summary": spatial_metrics(update_delta),
                        "boundaries": boundary_diagnostics(update_delta),
                    },
                    "latent_after": {
                        "summary": spatial_metrics(after),
                        "boundaries": boundary_diagnostics(after),
                    },
                    "latent_after_sha256": tensor_sha256(after),
                }
            )
        latent = after
        print(
            json.dumps(
                {
                    "progress": f"step_{index + 1}_of_{STEPS}",
                    "transformer_calls": transformer_calls,
                }
            ),
            flush=True,
        )

    final_hash = tensor_sha256(latent)
    vae_hook.remove()
    pipe.maybe_free_model_hooks()
    del latent, ip_embedding, prompt_embedding, pooled_embedding
    del identity_crop, feature_extractor, image_encoder, pipe
    gc.collect()
    torch.cuda.empty_cache()
    print(
        json.dumps(
            {
                "seed": SEED,
                "resolution": 512,
                "guidance": GUIDANCE_SCALE,
                "scale": 0.0,
                "fork_index": FORK_INDEX,
                "initial_latent_sha256": initial_hash,
                "prefix_hashes": prefix_hashes,
                "final_latent_sha256": final_hash,
                "tail_steps": tail_steps,
                "transformer_forward_calls": transformer_calls,
                "expected_transformer_forward_calls": EXPECTED_FORWARD_CALLS,
                "forbidden_calls": forbidden_calls,
                "vae_decode_calls": 0,
                "images_created": 0,
            }
        ),
        flush=True,
    )


def boundary_maximum(component: dict) -> float:
    boundaries = component["boundaries"]
    return max(
        boundaries["row_boundaries"]["maximum"],
        boundaries["column_boundaries"]["maximum"],
    )


def boundary_ratio(component: dict) -> float:
    boundaries = component["boundaries"]
    return max(
        boundaries["row_boundaries"]["maximum_to_median_ratio"],
        boundaries["column_boundaries"]["maximum_to_median_ratio"],
    )


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(R4_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS":
        raise RuntimeError("R3-R4 must pass before R3-R5")
    if digest(REFERENCE) != REFERENCE_SHA256:
        raise RuntimeError("Locked identity reference changed")
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R5 already exists; refusing to repeat decomposition")

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
                peak_rss = max(
                    peak_rss,
                    sum(
                        item.memory_info().rss
                        for item in tree
                        if item.is_running()
                    ),
                )
                peak_gpu = max(peak_gpu, gpu_used_mib())
            except (psutil.NoSuchProcess, subprocess.CalledProcessError):
                pass
            time.sleep(0.5)
        worker_log.flush()
        worker_log.seek(0)
        stdout = worker_log.read()
    if process.returncode != 0:
        raise RuntimeError(f"Late-step decomposition failed: {stdout[-12000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"Decomposition worker returned no JSON: {stdout[-4000:]}")
    progress = [json.loads(line) for line in lines[:-1]]
    smoke = json.loads(lines[-1])
    smoke.update(
        {
            "progress_event_count": len(progress),
            "peak_rss_gib": round(peak_rss / 1024**3, 2),
            "gpu_baseline_mib": baseline_gpu,
            "gpu_peak_mib": peak_gpu,
            "gpu_after_worker_exit_mib": gpu_used_mib(),
        }
    )
    prior_control = next(
        tail
        for tail in prior["smoke"]["tails"]
        if tail["name"] == "cfg5_scale0"
    )
    reproduces_prior = (
        smoke["prefix_hashes"][-1] == prior["smoke"]["fork_latent_sha256"]
        and smoke["final_latent_sha256"]
        == prior_control["final_latent_sha256"]
    )
    onset = next(
        (
            step
            for step in smoke["tail_steps"]
            if boundary_ratio(step["latent_after"]) >= RATIO_THRESHOLD
        ),
        None,
    )
    if onset is None:
        classification = "NO_DISCONTINUITY_REPRODUCED"
        evidence = {}
    else:
        before_absolute = boundary_maximum(onset["latent_before"])
        after_absolute = boundary_maximum(onset["latent_after"])
        guided_ratio = boundary_ratio(onset["guided_prediction"])
        update_ratio = boundary_ratio(onset["scheduler_update_delta"])
        absolute_growth = after_absolute / max(before_absolute, 1e-12)
        if absolute_growth <= 1.0:
            classification = "NORMALIZATION_DENOMINATOR_COLLAPSE"
        elif guided_ratio >= RATIO_THRESHOLD:
            classification = "PREDICTION_SEAM_PROPAGATED_BY_SCHEDULER"
        elif update_ratio >= RATIO_THRESHOLD:
            classification = "SCHEDULER_UPDATE_SEAM"
        else:
            classification = "ACCUMULATED_LATENT_SEAM"
        evidence = {
            "onset_step": onset["step"],
            "latent_before_absolute_max": round(before_absolute, 8),
            "latent_after_absolute_max": round(after_absolute, 8),
            "absolute_max_growth_ratio": round(absolute_growth, 8),
            "guided_prediction_ratio": round(guided_ratio, 8),
            "scheduler_update_ratio": round(update_ratio, 8),
            "latent_after_ratio": round(
                boundary_ratio(onset["latent_after"]), 8
            ),
        }
    exact_calls = smoke["transformer_forward_calls"] == EXPECTED_FORWARD_CALLS
    passed = (
        exact_calls
        and smoke["progress_event_count"] == EXPECTED_FORWARD_CALLS
        and smoke["forbidden_calls"]["vae"] == 0
        and smoke["images_created"] == 0
        and reproduces_prior
        and all(
            step[component]["summary"]["finite"]
            for step in smoke["tail_steps"]
            for component in (
                "latent_before",
                "unconditional_prediction",
                "conditional_prediction",
                "guided_prediction",
                "scheduler_update_delta",
                "latent_after",
            )
        )
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R5",
        "status": "PASS" if passed else "FAIL",
        "smoke": smoke,
        "analysis": {
            "status": classification,
            "ratio_threshold": RATIO_THRESHOLD,
            **evidence,
        },
        "guards": {
            "reproduces_r4_control_trajectory": reproduces_prior,
            "exact_transformer_call_budget": exact_calls,
            "absolute_boundary_profiles_saved": True,
            "vae_decode_performed": False,
            "image_generation_performed": False,
            "next_neutral_attempt_authorized": False,
            "climax_generated": False,
            "phase4n_opened": False,
        },
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
