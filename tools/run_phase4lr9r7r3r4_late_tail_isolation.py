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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
R3_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r3-latent-trajectory-ab-v1/phase4lr9r7r3r3-result.json"
)
OUTPUT_ROOT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r4-late-tail-isolation-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r4-result.json"
FORK_INDEX = 16
TAIL_CONFIGS = (
    {"name": "cfg1_scale0", "guidance": 1.0, "scale": 0.0},
    {"name": "cfg5_scale0", "guidance": 5.0, "scale": 0.0},
    {"name": "cfg5_scale05", "guidance": 5.0, "scale": 0.5},
)
EXPECTED_FORWARD_CALLS = FORK_INDEX + len(TAIL_CONFIGS) * (STEPS - FORK_INDEX)


def run_prediction(
    pipe,
    current_latent: torch.Tensor,
    timestep: torch.Tensor,
    prompt_embedding: torch.Tensor,
    pooled_embedding: torch.Tensor,
    ip_embedding: torch.Tensor,
) -> torch.Tensor:
    model_input = torch.cat([current_latent, current_latent], dim=0)
    with torch.inference_mode():
        return pipe.transformer(
            hidden_states=model_input.to(pipe._execution_device),
            timestep=timestep.expand(2).to(pipe._execution_device),
            encoder_hidden_states=prompt_embedding.to(pipe._execution_device),
            pooled_projections=pooled_embedding.to(pipe._execution_device),
            joint_attention_kwargs={
                "ip_adapter_image_embeds": ip_embedding.to(pipe._execution_device)
            },
            return_dict=False,
        )[0].cpu()


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

    forbidden_calls = {"vae": 0}

    def forbid_vae(*_args, **_kwargs):
        forbidden_calls["vae"] += 1
        raise RuntimeError("VAE call is forbidden during late-tail isolation")

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
    initial_latent = torch.randn(
        (1, 16, 64, 64), generator=generator, dtype=torch.bfloat16
    )
    initial_hash = tensor_sha256(initial_latent)
    prefix_scheduler = FlowMatchEulerDiscreteScheduler.from_config(pipe.scheduler.config)
    prefix_scheduler.set_timesteps(STEPS, device="cpu")
    latent = initial_latent.clone()
    prefix_steps = []
    transformer_calls = 0
    pipe.set_ip_adapter_scale(0.0)

    for index, timestep in enumerate(prefix_scheduler.timesteps[:FORK_INDEX]):
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
        guided = unconditional + GUIDANCE_SCALE * (conditional - unconditional)
        latent = prefix_scheduler.step(
            guided, timestep, latent, return_dict=False
        )[0]
        prefix_steps.append(
            {
                "step": index,
                "timestep": float(timestep.item()),
                "forward_seconds": round(time.perf_counter() - started, 3),
                "prediction": spatial_metrics(guided),
                "latent": spatial_metrics(latent),
                "latent_sha256": tensor_sha256(latent),
            }
        )
        print(
            json.dumps(
                {
                    "progress": f"prefix_{index + 1}_of_{FORK_INDEX}",
                    "transformer_calls": transformer_calls,
                }
            ),
            flush=True,
        )

    fork_latent = latent.clone()
    fork_hash = tensor_sha256(fork_latent)
    tails = []
    for config in TAIL_CONFIGS:
        scheduler = FlowMatchEulerDiscreteScheduler.from_config(pipe.scheduler.config)
        scheduler.set_timesteps(STEPS, device="cpu")
        scheduler.set_begin_index(FORK_INDEX)
        tail_latent = fork_latent.clone()
        pipe.set_ip_adapter_scale(config["scale"])
        tail_steps = []
        for index in range(FORK_INDEX, STEPS):
            timestep = scheduler.timesteps[index]
            started = time.perf_counter()
            prediction = run_prediction(
                pipe,
                tail_latent,
                timestep,
                prompt_embedding,
                pooled_embedding,
                ip_embedding,
            )
            transformer_calls += 1
            unconditional, conditional = prediction.chunk(2)
            guided = unconditional + config["guidance"] * (
                conditional - unconditional
            )
            tail_latent = scheduler.step(
                guided, timestep, tail_latent, return_dict=False
            )[0]
            metrics = spatial_metrics(tail_latent)
            tail_steps.append(
                {
                    "step": index,
                    "timestep": float(timestep.item()),
                    "forward_seconds": round(time.perf_counter() - started, 3),
                    "prediction": spatial_metrics(guided),
                    "latent": metrics,
                    "latent_sha256": tensor_sha256(tail_latent),
                }
            )
            print(
                json.dumps(
                    {
                        "progress": f"{config['name']}_{index + 1}_of_{STEPS}",
                        "transformer_calls": transformer_calls,
                        "row_seam": metrics[
                            "max_row_boundary_to_median_ratio"
                        ],
                    }
                ),
                flush=True,
            )
        tails.append(
            {
                **config,
                "fork_latent_sha256": fork_hash,
                "final_latent_sha256": tensor_sha256(tail_latent),
                "steps": tail_steps,
            }
        )

    vae_hook.remove()
    pipe.maybe_free_model_hooks()
    del initial_latent, fork_latent, latent, ip_embedding
    del prompt_embedding, pooled_embedding, identity_crop
    del feature_extractor, image_encoder, pipe
    gc.collect()
    torch.cuda.empty_cache()
    print(
        json.dumps(
            {
                "seed": SEED,
                "resolution": 512,
                "step_count": STEPS,
                "fork_index": FORK_INDEX,
                "tail_step_count": STEPS - FORK_INDEX,
                "initial_latent_sha256": initial_hash,
                "fork_latent_sha256": fork_hash,
                "prefix": {
                    "guidance": GUIDANCE_SCALE,
                    "scale": 0.0,
                    "steps": prefix_steps,
                },
                "tails": tails,
                "transformer_forward_calls": transformer_calls,
                "expected_transformer_forward_calls": EXPECTED_FORWARD_CALLS,
                "forbidden_calls": forbidden_calls,
                "vae_decode_calls": 0,
                "images_created": 0,
            }
        ),
        flush=True,
    )


def first_threshold_step(steps: list[dict], threshold: float) -> int | None:
    for step in steps:
        latent = step["latent"]
        if max(
            latent["max_row_boundary_to_median_ratio"],
            latent["max_column_boundary_to_median_ratio"],
        ) >= threshold:
            return step["step"]
    return None


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(R3_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_DENOISE_PATH_IDENTIFIED":
        raise RuntimeError("R3-R3 must identify the denoise path before R3-R4")
    if digest(REFERENCE) != REFERENCE_SHA256:
        raise RuntimeError("Locked identity reference changed")
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R4 already exists; refusing to repeat isolation")

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
        raise RuntimeError(f"Late-tail isolation worker failed: {stdout[-12000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"Late-tail worker returned no JSON: {stdout[-4000:]}")
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
    threshold = 1.2
    tail_analysis = []
    for tail in smoke["tails"]:
        maximum = max(
            max(
                step["latent"]["max_row_boundary_to_median_ratio"],
                step["latent"]["max_column_boundary_to_median_ratio"],
            )
            for step in tail["steps"]
        )
        tail_analysis.append(
            {
                "name": tail["name"],
                "first_threshold_step": first_threshold_step(
                    tail["steps"], threshold
                ),
                "maximum_latent_seam_ratio": round(maximum, 8),
                "final_latent": tail["steps"][-1]["latent"],
            }
        )
    by_name = {item["name"]: item for item in tail_analysis}
    prior_base = next(
        trajectory
        for trajectory in prior["smoke"]["trajectories"]
        if trajectory["scale"] == 0.0
    )
    prior_fork_hash = prior_base["steps"][FORK_INDEX - 1]["latent_sha256"]
    prior_final_hash = prior_base["final_latent_sha256"]
    fork_reproduces_prior_base = (
        smoke["fork_latent_sha256"] == prior_fork_hash
        and next(
            tail
            for tail in smoke["tails"]
            if tail["name"] == "cfg5_scale0"
        )["final_latent_sha256"]
        == prior_final_hash
    )
    cfg1_clean = by_name["cfg1_scale0"]["first_threshold_step"] is None
    cfg5_fails = by_name["cfg5_scale0"]["first_threshold_step"] is not None
    adapter_fails_earlier = (
        by_name["cfg5_scale05"]["first_threshold_step"] is not None
        and by_name["cfg5_scale0"]["first_threshold_step"] is not None
        and by_name["cfg5_scale05"]["first_threshold_step"]
        < by_name["cfg5_scale0"]["first_threshold_step"]
    )
    exact_calls = smoke["transformer_forward_calls"] == EXPECTED_FORWARD_CALLS
    passed = (
        exact_calls
        and smoke["progress_event_count"] == EXPECTED_FORWARD_CALLS
        and smoke["forbidden_calls"]["vae"] == 0
        and smoke["images_created"] == 0
        and fork_reproduces_prior_base
        and all(
            step["latent"]["finite"] and step["prediction"]["finite"]
            for tail in smoke["tails"]
            for step in tail["steps"]
        )
    )
    if cfg1_clean and cfg5_fails:
        isolation = "CFG_AMPLIFICATION_IDENTIFIED"
    elif cfg5_fails:
        isolation = "LATE_SCHEDULER_OR_CONDITIONAL_PATH_REMAINS"
    else:
        isolation = "NO_LATE_TAIL_DISCONTINUITY_FROM_COMMON_FORK"
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R4",
        "status": "PASS" if passed else "FAIL",
        "smoke": smoke,
        "analysis": {
            "status": isolation,
            "threshold": threshold,
            "tails": tail_analysis,
            "cfg_amplification_implicated": cfg1_clean and cfg5_fails,
            "ip_adapter_accelerates_onset": adapter_fails_earlier,
        },
        "guards": {
            "shared_prefix_and_fork_latent": len(
                {tail["fork_latent_sha256"] for tail in smoke["tails"]}
            )
            == 1,
            "fork_reproduces_prior_base_trajectory": fork_reproduces_prior_base,
            "exact_transformer_call_budget": exact_calls,
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
