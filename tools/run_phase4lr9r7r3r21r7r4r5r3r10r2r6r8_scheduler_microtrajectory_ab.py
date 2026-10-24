from __future__ import annotations

import gc
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as functional
from PIL import Image
from run_phase4lr9r7r3r21r7r4r2_late_window_trajectory import (
    ADAPTER_ROOT,
    BO_REFERENCE,
    IDENTITY_CROP,
    LARGE_ROOT,
    SEED,
    SIGLIP_ROOT,
    STEPS,
)
from run_phase4lr9r7r3r21r7r4r5r3r10r2r6r3_geometry_dry_run import (
    CHANNELS,
    GRID,
    HIDDEN_SIZE,
    build_controls,
)

from ai_story.explicit_spatial_control import (
    ExplicitSpatialControlResidual,
    StagedExplicitControlRegistration,
    raster_controls_to_tokens,
)
from ai_story.image_gate_profiles import PHOTOREALISTIC_INTERACTION_PROMPT
from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R7_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r7-real-transformer-gain-ab-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r7-result.json"
)
BASELINE_CACHE = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r7-scale-terminal-isolation-v1/baseline-cache.pt"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r8-scheduler-microtrajectory-ab-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r6r8-result.json"
MOTHER_CHANNELS = {"me_face", "me_hand", "me_contact"}
GAINS = {"a_gain_1": 1.0, "b_gain_1_5": 1.5}
ACTIVE_BLOCKS = [0, 1, 2, 3, 4]
CONTROL_STEPS = {2, 3}
PROBE_STEPS = [2, 3, 4]
SCALE = 0.00125


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def grid_delta(current: torch.Tensor, baseline: torch.Tensor) -> torch.Tensor:
    delta = (current.float() - baseline.float()).abs().mean(dim=1, keepdim=True)
    return functional.adaptive_avg_pool2d(delta, GRID).reshape(-1)


def region_metrics(delta: torch.Tensor, mask: torch.Tensor) -> dict[str, float]:
    flat_mask = mask.reshape(-1)
    inside = float(delta[flat_mask].mean())
    outside = float(delta[~flat_mask].mean())
    return {
        "inside_mean_abs_delta": inside,
        "outside_mean_abs_delta": outside,
        "localization_ratio": inside / max(outside, 1e-12),
    }


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists():
        raise RuntimeError("R8 checkpoint already exists; refusing overwrite")
    prior = json.loads(R7_RESULT.read_text(encoding="utf-8"))
    if prior["status"] != "PASS_REAL_TRANSFORMER_GAIN_OBSERVABILITY_AB":
        raise RuntimeError("R7 real-transformer gain A/B is not locked PASS")
    gpu_before = gpu_used_mib()
    if gpu_before > 512:
        raise RuntimeError(f"GPU is not exclusive: {gpu_before} MiB")

    from diffusers import StableDiffusion3Pipeline
    from diffusers.models.attention_processor import SD3IPAdapterJointAttnProcessor2_0
    from diffusers.schedulers import FlowMatchEulerDiscreteScheduler
    from transformers import SiglipImageProcessor, SiglipVisionModel

    started = time.perf_counter()
    pipe = StableDiffusion3Pipeline.from_pretrained(
        LARGE_ROOT,
        local_files_only=True,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    pipe.register_modules(
        feature_extractor=SiglipImageProcessor.from_pretrained(SIGLIP_ROOT, local_files_only=True),
        image_encoder=SiglipVisionModel.from_pretrained(
            SIGLIP_ROOT,
            local_files_only=True,
            dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
        ),
    )
    pipe.load_ip_adapter(
        ADAPTER_ROOT,
        weight_name="ip-adapter.bin",
        image_encoder_folder=None,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    replacements = dict(pipe.transformer.attn_processors)
    for name, processor in replacements.items():
        if isinstance(processor, SD3IPAdapterJointAttnProcessor2_0):
            processor.scale = 0.0
            replacements[name] = RegionalSD3IPAdapterProcessor(processor)
    pipe.transformer.set_attn_processor(replacements)

    raster, _ = build_controls()
    base_controls = raster_controls_to_tokens(raster, GRID, threshold=0.25)
    masks = {
        name: base_controls[..., index].bool() for index, name in enumerate(CHANNELS)
    }
    vector_generator = torch.Generator(device="cpu").manual_seed(SEED)
    vectors = torch.randn((len(CHANNELS), HIDDEN_SIZE), generator=vector_generator)
    adapter = ExplicitSpatialControlResidual(
        vectors, accumulate_in_fp32=True, error_feedback=True
    ).to(torch.bfloat16)
    registration = StagedExplicitControlRegistration(pipe.transformer, {"geometry": adapter})

    pipe.enable_model_cpu_offload(device="cuda")
    prompt_embeds, _, pooled_embeds, _ = pipe.encode_prompt(
        prompt=PHOTOREALISTIC_INTERACTION_PROMPT,
        prompt_2=PHOTOREALISTIC_INTERACTION_PROMPT,
        prompt_3=PHOTOREALISTIC_INTERACTION_PROMPT,
        device=pipe._execution_device,
        do_classifier_free_guidance=False,
    )
    with Image.open(BO_REFERENCE) as source:
        identity_crop = source.convert("RGB").crop(IDENTITY_CROP)
    with torch.inference_mode():
        identity_embedding = pipe.encode_image(identity_crop, pipe._execution_device)
    attention_kwargs = {
        "ip_adapter_image_embeds": identity_embedding,
        "regional_attention_mask": torch.zeros((1, GRID[0] * GRID[1], 1)).to(
            pipe._execution_device
        ),
    }
    baseline_cache = torch.load(BASELINE_CACHE, map_location="cpu", weights_only=False)
    fixed_latent = baseline_cache["branch"]["latents"][PROBE_STEPS[0] - 1].clone()

    branches: dict[str, dict[str, Any]] = {}
    branch_latents: dict[str, list[torch.Tensor]] = {}
    transformer_calls = 0
    scheduler_calls = 0
    with torch.inference_mode():
        for branch_name, gain in GAINS.items():
            weighted = base_controls.float().clone()
            for index, channel in enumerate(CHANNELS):
                if channel in MOTHER_CHANNELS:
                    weighted[..., index] *= gain
            scheduler = FlowMatchEulerDiscreteScheduler.from_config(pipe.scheduler.config)
            scheduler.set_timesteps(STEPS, device="cpu")
            latent = fixed_latent.clone()
            adapter.reset_error_feedback()
            steps: list[dict[str, Any]] = []
            branch_latents[branch_name] = []
            for step_index in PROBE_STEPS:
                control_active = step_index in CONTROL_STEPS
                registration.configure_stage(
                    "geometry",
                    weighted,
                    [
                        SCALE if control_active and index in ACTIVE_BLOCKS else 0.0
                        for index in range(38)
                    ],
                )
                timestep = scheduler.timesteps[step_index]
                prediction = pipe.transformer(
                    hidden_states=latent.to(pipe._execution_device),
                    timestep=timestep.reshape(1).to(pipe._execution_device),
                    encoder_hidden_states=prompt_embeds,
                    pooled_projections=pooled_embeds,
                    joint_attention_kwargs=dict(attention_kwargs),
                    return_dict=False,
                )[0].detach().cpu()
                transformer_calls += 1
                before = latent
                latent = scheduler.step(
                    prediction, timestep, before, return_dict=False
                )[0].detach().cpu()
                scheduler_calls += 1
                branch_latents[branch_name].append(latent.clone())
                steps.append(
                    {
                        "step_index": step_index,
                        "timestep": float(timestep.item()),
                        "sigma": float(scheduler.sigmas[step_index].item()),
                        "next_sigma": float(scheduler.sigmas[step_index + 1].item()),
                        "control_active": control_active,
                        "prediction_norm": float(prediction.float().norm()),
                        "scheduler_update_norm": float((latent.float() - before.float()).norm()),
                        "latent_norm": float(latent.float().norm()),
                        "finite": bool(torch.isfinite(latent).all()),
                    }
                )
                print(json.dumps({"branch": branch_name, "step": step_index}), flush=True)
            branches[branch_name] = {"gain": gain, "steps": steps}

    comparisons = []
    for offset, step_index in enumerate(PROBE_STEPS):
        a_latent = branch_latents["a_gain_1"][offset]
        b_latent = branch_latents["b_gain_1_5"][offset]
        delta = grid_delta(b_latent, a_latent)
        comparisons.append(
            {
                "step_index": step_index,
                "control_active": step_index in CONTROL_STEPS,
                "global_mean_abs_delta": float(delta.mean()),
                "global_max_abs_delta": float(delta.max()),
                "mother_regions": {
                    region: region_metrics(delta, masks[region])
                    for region in sorted(MOTHER_CHANNELS)
                },
                "finite": bool(torch.isfinite(delta).all()),
            }
        )

    active_survives_scheduler = all(
        item["global_mean_abs_delta"] > 0.0
        for item in comparisons
        if item["control_active"]
    )
    passive_persistence = comparisons[-1]["global_mean_abs_delta"] > 0.0
    finite = all(item["finite"] for item in comparisons) and all(
        step["finite"] for branch in branches.values() for step in branch["steps"]
    )
    passed = active_survives_scheduler and passive_persistence and finite

    registration.unregister()
    del pipe, registration, adapter, prompt_embeds, pooled_embeds, identity_embedding
    gc.collect()
    torch.cuda.empty_cache()
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R6-R8",
        "status": "PASS_SCHEDULER_MICROTRAJECTORY_GAIN_AB" if passed else "FAIL",
        "configuration": {
            "probe_steps": PROBE_STEPS,
            "control_steps": sorted(CONTROL_STEPS),
            "passive_persistence_step": 4,
            "active_blocks": ACTIVE_BLOCKS,
            "scale": SCALE,
            "gains": GAINS,
            "seed": SEED,
        },
        "branches": branches,
        "comparisons": comparisons,
        "summary": {
            "gain_difference_survives_active_scheduler_steps": active_survives_scheduler,
            "gain_difference_survives_first_passive_step": passive_persistence,
            "first_scheduler_ab_mean_abs_delta": comparisons[0]["global_mean_abs_delta"],
            "final_passive_ab_mean_abs_delta": comparisons[-1]["global_mean_abs_delta"],
            "scheduler_immediate_erasure": not active_survives_scheduler,
            "remaining_suspect": (
                "later_denoise_tail_accumulation"
                if passed
                else "scheduler_update_or_immediate_post_control_transition"
            ),
        },
        "next_decode_authorized": False,
        "phase4l_closure": {
            "status": "OPEN_PENDING_TRAJECTORY_TAIL_LOCALIZATION",
            "all_requirements_satisfied": False,
        },
        "runtime": {
            "seconds": round(time.perf_counter() - started, 3),
            "gpu_before_mib": gpu_before,
            "gpu_after_mib": gpu_used_mib(),
        },
        "guards": {
            "transformer_forward_count": transformer_calls,
            "scheduler_step_count": scheduler_calls,
            "full_trajectory_run": False,
            "vae_called": False,
            "images_created": 0,
            "production_profile_changed": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
