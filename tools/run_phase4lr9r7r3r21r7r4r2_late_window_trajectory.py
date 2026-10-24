from __future__ import annotations

import gc
import json
import os
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as functional
from PIL import Image
from run_phase4lr9r7r3r21r5_regional_trajectory import (
    IDENTITY_CROP,
    boundary_diagnostics,
    set_scale,
    token_mask,
)
from run_phase4lr9r7r3r21r7r4_full_transformer_control_ab import (
    HIDDEN_SIZE,
    load_control_tokens,
)

from ai_story.explicit_spatial_control import (
    ExplicitControlRegistration,
    ExplicitSpatialControlResidual,
)
from ai_story.image_gate_profiles import (
    PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
    PHOTOREALISTIC_INTERACTION_PROMPT,
)
from ai_story.latent_discontinuity import (
    LatentDiscontinuityConfig,
    evaluate_latent_discontinuity,
    observation_from_profile,
)
from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R4_R1_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r1-block-window-isolation-v1/"
    "phase4lr9r7r3r21r7r4r1-result.json"
)
LAYOUT_PATH = BASELINE_ROOT / (
    "phase4lr9r7r3r21r1-negative-spatial-conditioning-lock-v1/"
    "regional-spatial-conditioning.json"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r2-late-window-trajectory-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r2-result.json"
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
SOURCE_WORK = BASELINE_ROOT / "phase4l-climax-canary-v1/youth-torn-paper-boat/work"
BO_REFERENCE = SOURCE_WORK / "characters/bo.png"
ME_REFERENCE = SOURCE_WORK / "characters/me.png"
SEED = 420917
STEPS = 24
GUIDANCE = 5.0
CONTROL_SCALE = 0.01
ACTIVE_BLOCKS = list(range(28, 38))
MAX_RELATIVE_LATENT_DELTA = 0.05
MAX_UPDATE_NORM_RATIO = 1.5
MIN_UPDATE_NORM_RATIO = 0.5
MIN_FINAL_SPATIAL_RATIO = 0.95


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def critic(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [
        observation_from_profile(
            step=item["step"], axis=axis, profile=item["boundaries"][key]
        )
        for item in profiles
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries"))
    ]
    return asdict(
        evaluate_latent_discontinuity(observations, LatentDiscontinuityConfig())
    )


def spatial_delta_metrics(
    baseline: torch.Tensor,
    active: torch.Tensor,
    union_mask: torch.Tensor,
) -> dict[str, float | bool]:
    delta = (active.float() - baseline.float()).abs().mean(dim=1, keepdim=True)
    grid_delta = functional.avg_pool2d(delta, kernel_size=2, stride=2).reshape(-1)
    mask = union_mask.reshape(-1).bool()
    inside = float(grid_delta[mask].mean().item())
    outside = float(grid_delta[~mask].mean().item())
    global_mean = float(grid_delta.mean().item())
    baseline_mean = float(baseline.float().abs().mean().item())
    return {
        "inside_mean_abs_delta": inside,
        "outside_mean_abs_delta": outside,
        "global_mean_abs_delta": global_mean,
        "relative_latent_delta": global_mean / max(baseline_mean, 1e-12),
        "spatial_ratio": inside / max(outside, 1e-12),
        "finite": bool(torch.isfinite(grid_delta).all().item()),
    }


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists():
        raise RuntimeError("R21-R7-R4-R2 already exists; refusing to overwrite")
    prior = json.loads(R4_R1_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_BLOCK_WINDOW_ISOLATION":
        raise RuntimeError("R4-R1 block-window isolation must pass")
    if prior.get("selected_profile") != "late":
        raise RuntimeError("R4-R1 did not lock the late control window")
    if prior["windows"]["late"] != ACTIVE_BLOCKS:
        raise RuntimeError("R4-R1 late block profile changed")
    gpu_before = gpu_used_mib()
    if gpu_before > 512:
        raise RuntimeError(f"GPU is not exclusive: {gpu_before} MiB")

    from diffusers import StableDiffusion3Pipeline
    from diffusers.models.attention_processor import (
        SD3IPAdapterJointAttnProcessor2_0,
    )
    from transformers import SiglipImageProcessor, SiglipVisionModel

    started = time.perf_counter()
    pipe = StableDiffusion3Pipeline.from_pretrained(
        LARGE_ROOT,
        local_files_only=True,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    pipe.register_modules(
        feature_extractor=SiglipImageProcessor.from_pretrained(
            SIGLIP_ROOT, local_files_only=True
        ),
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

    generator = torch.Generator(device="cpu").manual_seed(SEED)
    vectors = torch.randn((3, HIDDEN_SIZE), generator=generator)
    control = ExplicitSpatialControlResidual(vectors).to(torch.bfloat16)
    registration = ExplicitControlRegistration(pipe.transformer, control)
    token_controls = load_control_tokens()
    union_mask = token_controls.any(dim=-1)
    pipe.enable_model_cpu_offload(device="cuda")
    pipe.vae.disable_tiling()
    pipe.vae.disable_slicing()

    with Image.open(BO_REFERENCE) as source:
        bo_crop = source.convert("RGB").crop(IDENTITY_CROP)
    with Image.open(ME_REFERENCE) as source:
        mother_crop = source.convert("RGB").crop(IDENTITY_CROP)
    with torch.inference_mode():
        bo_embedding = pipe.encode_image(bo_crop, pipe._execution_device)
        mother_embedding = pipe.encode_image(mother_crop, pipe._execution_device)
    cfg_bo = torch.cat([torch.zeros_like(bo_embedding), bo_embedding], dim=0)
    cfg_mother = torch.cat([torch.zeros_like(mother_embedding), mother_embedding], dim=0)

    layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    regions = layout["regions"]
    interaction = regions["interaction"]["box"]
    bo_mask = token_mask(regions["bo_identity"]["box"], interaction)
    mother_mask = token_mask(regions["mother_identity"]["box"], interaction)

    vae_calls = {"forward": 0, "decode": 0}
    forward_hook = pipe.vae.register_forward_pre_hook(
        lambda *_args, **_kwargs: vae_calls.__setitem__(
            "forward", vae_calls["forward"] + 1
        )
    )
    decode_hook = pipe.vae.decoder.register_forward_pre_hook(
        lambda *_args, **_kwargs: vae_calls.__setitem__(
            "decode", vae_calls["decode"] + 1
        )
    )

    def run_branch(
        pipeline, control_registration, name: str, explicit_enabled: bool
    ) -> dict[str, Any]:
        profiles: list[dict[str, Any]] = []
        latents: list[torch.Tensor] = []
        updates: list[float] = []
        previous: torch.Tensor | None = None
        events = [{"effective_step": 0, "scale": 0.0, "identity": "BO"}]
        set_scale(pipeline, 0.0)
        control_registration.configure(
            token_controls,
            [
                CONTROL_SCALE if explicit_enabled and index in ACTIVE_BLOCKS else 0.0
                for index in range(38)
            ],
        )
        pipeline._joint_attention_kwargs = {"regional_attention_mask": bo_mask}

        def callback(_pipe, step_index, timestep, callback_kwargs):
            nonlocal previous
            latent = callback_kwargs["latents"].detach().cpu()
            latents.append(latent)
            update_norm = (
                0.0
                if previous is None
                else float((latent.float() - previous.float()).norm().item())
            )
            updates.append(update_norm)
            previous = latent
            profiles.append(
                {
                    "step": int(step_index),
                    "timestep": float(timestep.item()),
                    "update_norm": update_norm,
                    "boundaries": boundary_diagnostics(latent),
                }
            )
            next_step = step_index + 1
            if next_step == 8:
                set_scale(_pipe, 0.25)
                events.append(
                    {"effective_step": 8, "scale": 0.25, "identity": "BO"}
                )
            elif next_step == 12:
                _pipe._joint_attention_kwargs["ip_adapter_image_embeds"] = cfg_mother
                _pipe._joint_attention_kwargs["regional_attention_mask"] = mother_mask.to(
                    callback_kwargs["latents"].device
                )
                events.append(
                    {"effective_step": 12, "scale": 0.25, "identity": "ME"}
                )
            elif next_step == 16:
                set_scale(_pipe, 0.0)
                events.append(
                    {"effective_step": 16, "scale": 0.0, "identity": "ME"}
                )
            print(
                json.dumps({"branch": name, "progress": f"step_{next_step}_of_{STEPS}"}),
                flush=True,
            )
            return callback_kwargs

        branch_generator = torch.Generator(device="cpu").manual_seed(SEED)
        with torch.inference_mode():
            output = pipeline(
                prompt=PHOTOREALISTIC_INTERACTION_PROMPT,
                negative_prompt=PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
                ip_adapter_image_embeds=cfg_bo,
                height=512,
                width=512,
                num_inference_steps=STEPS,
                guidance_scale=GUIDANCE,
                num_images_per_prompt=1,
                generator=branch_generator,
                output_type="latent",
                callback_on_step_end=callback,
                callback_on_step_end_tensor_inputs=["latents"],
            )
        final_latent = output.images.detach().cpu()
        return {
            "name": name,
            "explicit_enabled": explicit_enabled,
            "events": events,
            "profiles": profiles,
            "latents": latents,
            "updates": updates,
            "final_latent": final_latent,
            "latent_critic": critic(profiles),
        }

    baseline = run_branch(pipe, registration, "regional_identity_only", False)
    active = run_branch(
        pipe, registration, "regional_identity_plus_late_control", True
    )
    comparisons = []
    for step in range(STEPS):
        spatial = spatial_delta_metrics(
            baseline["latents"][step], active["latents"][step], union_mask
        )
        base_update = baseline["updates"][step]
        active_update = active["updates"][step]
        update_ratio = (
            1.0 if step == 0 else active_update / max(base_update, 1e-12)
        )
        comparisons.append(
            {"step": step, "update_norm_ratio": update_ratio, **spatial}
        )

    max_relative_delta = max(item["relative_latent_delta"] for item in comparisons)
    update_ratios = [item["update_norm_ratio"] for item in comparisons[1:]]
    final_spatial_ratio = comparisons[-1]["spatial_ratio"]
    all_finite = all(item["finite"] for item in comparisons)
    events_match = baseline["events"] == active["events"]
    passed = (
        not baseline["latent_critic"]["blocked"]
        and not active["latent_critic"]["blocked"]
        and len(baseline["profiles"]) == len(active["profiles"]) == STEPS
        and max_relative_delta < MAX_RELATIVE_LATENT_DELTA
        and min(update_ratios) >= MIN_UPDATE_NORM_RATIO
        and max(update_ratios) <= MAX_UPDATE_NORM_RATIO
        and final_spatial_ratio >= MIN_FINAL_SPATIAL_RATIO
        and all_finite
        and events_match
        and vae_calls == {"forward": 0, "decode": 0}
    )

    forward_hook.remove()
    decode_hook.remove()
    registration.unregister()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R2",
        "status": "PASS_CLEAN_LATE_WINDOW_EXPLICIT_CONTROL_TRAJECTORY"
        if passed
        else "FAIL",
        "seed": SEED,
        "steps": STEPS,
        "guidance_scale": GUIDANCE,
        "explicit_profile": {
            "active_blocks": ACTIVE_BLOCKS,
            "scale": CONTROL_SCALE,
        },
        "baseline": {
            "events": baseline["events"],
            "profile_count": len(baseline["profiles"]),
            "latent_critic": baseline["latent_critic"],
        },
        "active": {
            "events": active["events"],
            "profile_count": len(active["profiles"]),
            "latent_critic": active["latent_critic"],
        },
        "comparison": {
            "steps": comparisons,
            "max_relative_latent_delta": max_relative_delta,
            "minimum_update_norm_ratio": min(update_ratios),
            "maximum_update_norm_ratio": max(update_ratios),
            "final_spatial_ratio": final_spatial_ratio,
            "all_steps_finite": all_finite,
            "identity_events_match": events_match,
            "thresholds": {
                "maximum_relative_latent_delta": MAX_RELATIVE_LATENT_DELTA,
                "minimum_update_norm_ratio": MIN_UPDATE_NORM_RATIO,
                "maximum_update_norm_ratio": MAX_UPDATE_NORM_RATIO,
                "minimum_final_spatial_ratio": MIN_FINAL_SPATIAL_RATIO,
            },
        },
        "runtime": {
            "seconds": round(time.perf_counter() - started, 3),
            "gpu_before_mib": gpu_before,
            "gpu_after_mib": gpu_used_mib(),
        },
        "guards": {
            "transformer_forward_count": STEPS * 2,
            "scheduler_step_count": STEPS * 2,
            "trajectory_count": 2,
            "vae_calls": vae_calls,
            "images_created": 0,
            "decode_authorized": False,
            "next_full_scene_attempt_authorized": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    del pipe, control, registration, baseline, active
    gc.collect()
    torch.cuda.empty_cache()
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
