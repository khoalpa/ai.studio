from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
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
)
from run_phase4lr9r7r3r5_late_step_decomposition import boundary_diagnostics

from ai_story.latent_discontinuity import (
    LatentDiscontinuityConfig,
    evaluate_latent_discontinuity,
    observation_from_profile,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R10_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r10-offline-scale-causal-replay-v1/phase4lr9r7r3r10-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r11-latent-scale025-probe-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r11-result.json"
WORKER_LOG = OUTPUT_ROOT / "worker.log"
SCALE = 0.25
LATE_TAIL_SCALE: float | None = None
SCALE_CUTOFF_STEP: int | None = None
IP_ADAPTER_SCALE_SCHEDULE: list[dict[str, float | int]] | None = None
TAIL_START = 16
CRITIC_CONFIG = LatentDiscontinuityConfig()


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
    configured_schedule = IP_ADAPTER_SCALE_SCHEDULE or [
        {"effective_step": 0, "scale": SCALE},
        *(
            [
                {
                    "effective_step": SCALE_CUTOFF_STEP,
                    "scale": LATE_TAIL_SCALE,
                }
            ]
            if LATE_TAIL_SCALE is not None and SCALE_CUTOFF_STEP is not None
            else []
        ),
    ]
    pipe.set_ip_adapter_scale(float(configured_schedule[0]["scale"]))
    pipe.enable_model_cpu_offload(device="cuda")

    forbidden_calls = {"vae_forward": 0, "vae_decode": 0}

    def forbid_vae_forward(*_args, **_kwargs):
        forbidden_calls["vae_forward"] += 1
        raise RuntimeError("VAE forward is forbidden during latent-only scale probe")

    def forbid_vae_decode(*_args, **_kwargs):
        forbidden_calls["vae_decode"] += 1
        raise RuntimeError("VAE decode is forbidden during latent-only scale probe")

    vae_forward_hook = pipe.vae.register_forward_pre_hook(forbid_vae_forward)
    vae_decode_hook = pipe.vae.decoder.register_forward_pre_hook(forbid_vae_decode)
    tail_profiles: list[dict] = []
    scale_events: list[dict] = [dict(configured_schedule[0])]

    def capture_latents(_pipe, step_index, timestep, callback_kwargs):
        if step_index >= TAIL_START:
            latent = callback_kwargs["latents"].detach().cpu()
            tail_profiles.append(
                {
                    "step": int(step_index),
                    "timestep": float(timestep.item()),
                    "boundaries": boundary_diagnostics(latent),
                }
            )
        next_step = step_index + 1
        for event in configured_schedule[1:]:
            if int(event["effective_step"]) == next_step:
                _pipe.set_ip_adapter_scale(float(event["scale"]))
                scale_events.append(dict(event))
        print(
            json.dumps({"progress": f"step_{step_index + 1}_of_{STEPS}"}),
            flush=True,
        )
        return callback_kwargs

    with Image.open(REFERENCE) as source:
        identity_crop = source.convert("RGB").crop(REFERENCE_CROP_BOX)
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    started = time.perf_counter()
    with torch.inference_mode():
        output = pipe(
            prompt=PROMPT,
            negative_prompt=NEGATIVE_PROMPT,
            ip_adapter_image=identity_crop,
            height=512,
            width=512,
            num_inference_steps=STEPS,
            guidance_scale=GUIDANCE_SCALE,
            num_images_per_prompt=1,
            generator=generator,
            output_type="latent",
            callback_on_step_end=capture_latents,
            callback_on_step_end_tensor_inputs=["latents"],
        )
    final_latent = output.images.detach().cpu()
    observations = []
    for item in tail_profiles:
        for axis, key in (
            ("row", "row_boundaries"),
            ("column", "column_boundaries"),
        ):
            observations.append(
                observation_from_profile(
                    step=item["step"],
                    axis=axis,
                    profile=item["boundaries"][key],
                )
            )
    critic = evaluate_latent_discontinuity(observations, CRITIC_CONFIG)
    metrics = {
        "seed": SEED,
        "resolution": 512,
        "guidance_scale": GUIDANCE_SCALE,
        "steps": STEPS,
        "ip_adapter_scale": SCALE,
        "ip_adapter_scale_schedule": scale_events,
        "pipeline_dtype": "torch.bfloat16",
        "identity_crop_box_in_memory": list(REFERENCE_CROP_BOX),
        "identity_crop_persisted": False,
        "trajectory_seconds": round(time.perf_counter() - started, 3),
        "tail_profiles": tail_profiles,
        "tail_profile_count": len(tail_profiles),
        "latent_critic": asdict(critic),
        "final_latent_shape": list(final_latent.shape),
        "forbidden_calls": forbidden_calls,
        "vae_decode_calls": 0,
        "images_created": 0,
        "cuda_max_allocated_mib": round(
            torch.cuda.max_memory_allocated() / 1024**2, 2
        ),
    }
    vae_forward_hook.remove()
    vae_decode_hook.remove()
    pipe.maybe_free_model_hooks()
    del output, final_latent, generator, identity_crop
    del feature_extractor, image_encoder, pipe
    gc.collect()
    torch.cuda.empty_cache()
    metrics["cuda_allocated_mib_after_cleanup"] = round(
        torch.cuda.memory_allocated() / 1024**2, 2
    )
    print(json.dumps(metrics), flush=True)


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(R10_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS":
        raise RuntimeError("R3-R10 must pass before the scale 0.25 probe")
    if digest(REFERENCE) != REFERENCE_SHA256:
        raise RuntimeError("Locked identity reference changed")
    if RESULT_PATH.exists():
        existing = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        recoverable = (
            existing.get("phase") == "4L-R9-R7-R3-R11"
            and existing.get("status") == "FAIL_EXECUTION"
            and existing.get("probe", {}).get("tail_profile_count")
            == STEPS - TAIL_START
            and existing.get("probe", {}).get("images_created") == 0
            and existing.get("probe", {}).get("forbidden_calls")
            == {"vae_forward": 0, "vae_decode": 0}
        )
        if not recoverable:
            raise RuntimeError("R3-R11 already exists; refusing a second trajectory")
        progress_count = WORKER_LOG.read_text(encoding="utf-8").count(
            '"progress": "step_'
        )
        if progress_count != STEPS:
            raise RuntimeError(
                f"Cannot finalize existing trajectory: {progress_count}/{STEPS} steps"
            )
        existing["probe"]["progress_event_count"] = progress_count
        existing["status"] = (
            "PASS_CLEAN_SCALE_0_25"
            if not existing["probe"]["latent_critic"]["blocked"]
            else "PASS_BLOCKED_SCALE_0_25"
        )
        existing["recovery"] = {
            "checkpoint_only": True,
            "trajectory_rerun": False,
            "reason": "Progress JSON was prefixed by the diffusers progress bar",
        }
        RESULT_PATH.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(existing, ensure_ascii=False))
        return

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
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    with WORKER_LOG.open("w+", encoding="utf-8") as worker_log:
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
                    sum(item.memory_info().rss for item in tree if item.is_running()),
                )
                peak_gpu = max(peak_gpu, gpu_used_mib())
            except (psutil.NoSuchProcess, subprocess.CalledProcessError):
                pass
            time.sleep(0.5)
        worker_log.flush()
        worker_log.seek(0)
        stdout = worker_log.read()
    if process.returncode != 0:
        raise RuntimeError(f"Scale 0.25 worker failed: {stdout[-12000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"Scale 0.25 worker returned no JSON: {stdout[-4000:]}")
    progress = [json.loads(line) for line in lines[:-1]]
    probe = json.loads(lines[-1])
    probe.update(
        {
            "progress_event_count": len(progress),
            "peak_rss_gib": round(peak_rss / 1024**3, 2),
            "gpu_baseline_mib": baseline_gpu,
            "gpu_peak_mib": peak_gpu,
            "gpu_delta_mib": peak_gpu - baseline_gpu,
            "gpu_after_worker_exit_mib": gpu_used_mib(),
        }
    )
    execution_valid = (
        probe["progress_event_count"] == STEPS
        and probe["tail_profile_count"] == STEPS - TAIL_START
        and probe["forbidden_calls"] == {"vae_forward": 0, "vae_decode": 0}
        and probe["vae_decode_calls"] == 0
        and probe["images_created"] == 0
    )
    clean = not probe["latent_critic"]["blocked"]
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R11",
        "status": (
            "PASS_CLEAN_SCALE_0_25"
            if execution_valid and clean
            else (
                "PASS_BLOCKED_SCALE_0_25"
                if execution_valid
                else "FAIL_EXECUTION"
            )
        ),
        "probe": probe,
        "analysis": {
            "scale_0_25_clean": clean,
            "candidate_upper_bound": 0.25 if clean else None,
            "next_lower_probe": None if clean else 0.125,
        },
        "guards": {
            "exactly_one_trajectory": True,
            "scale_probe_count": 1,
            "vae_decode_performed": False,
            "image_generation_performed": False,
            "neutral_generation_authorized": False,
            "climax_generated": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    if not execution_valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
