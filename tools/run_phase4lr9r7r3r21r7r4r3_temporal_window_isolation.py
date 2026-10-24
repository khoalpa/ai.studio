from __future__ import annotations

import gc
import hashlib
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
R4_R2_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r2-late-window-trajectory-v1/"
    "phase4lr9r7r3r21r7r4r2-result.json"
)
LAYOUT_PATH = BASELINE_ROOT / (
    "phase4lr9r7r3r21r1-negative-spatial-conditioning-lock-v1/"
    "regional-spatial-conditioning.json"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r3-temporal-window-isolation-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r3-result.json"
CACHE_ROOT = OUTPUT_ROOT / "branch-cache"
BASELINE_CACHE_FALLBACK: Path | None = None
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
SOURCE_WORK = BASELINE_ROOT / "phase4l-climax-canary-v1/youth-torn-paper-boat/work"
BO_REFERENCE = SOURCE_WORK / "characters/bo.png"
ME_REFERENCE = SOURCE_WORK / "characters/me.png"
EXPECTED_R4_R2_SHA256 = (
    "4c167c3fe8ad280fe027867ae28cd862669c25e46a6404d122018174f297d5e1"
)
PHASE = "4L-R9-R7-R3-R21-R7-R4-R3"
NEGATIVE_FIXTURE_FLAG = "full_time_profile_forbidden"
SEED = 420917
STEPS = 24
GUIDANCE = 5.0
CONTROL_SCALE = 0.01
ACTIVE_BLOCKS = list(range(28, 38))
WINDOWS: dict[str, list[int]] = {
    "early": list(range(0, 8)),
    "middle": list(range(8, 16)),
    "late": list(range(16, 24)),
}
MAX_RELATIVE_LATENT_DELTA = 0.05
MAX_UPDATE_NORM_RATIO = 1.5
MIN_UPDATE_NORM_RATIO = 0.5
MIN_FINAL_SPATIAL_RATIO = 0.95


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_prior(prior: dict[str, Any], prior_digest: str) -> None:
    if prior_digest != EXPECTED_R4_R2_SHA256 or prior.get("status") != "FAIL":
        raise RuntimeError("R4-R2 full-time negative fixture changed or no longer fails")
    if prior["comparison"]["max_relative_latent_delta"] <= prior["comparison"][
        "thresholds"
    ]["maximum_relative_latent_delta"]:
        raise RuntimeError("R4-R2 no longer demonstrates temporal accumulation")


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def latent_critic(profiles: list[dict[str, Any]]) -> dict[str, Any]:
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


def spatial_metrics(
    baseline: torch.Tensor, active: torch.Tensor, union_mask: torch.Tensor
) -> dict[str, float | bool]:
    delta = (active.float() - baseline.float()).abs().mean(dim=1, keepdim=True)
    grid = functional.avg_pool2d(delta, kernel_size=2, stride=2).reshape(-1)
    mask = union_mask.reshape(-1).bool()
    inside = float(grid[mask].mean().item())
    outside = float(grid[~mask].mean().item())
    global_mean = float(grid.mean().item())
    baseline_mean = float(baseline.float().abs().mean().item())
    return {
        "inside_mean_abs_delta": inside,
        "outside_mean_abs_delta": outside,
        "global_mean_abs_delta": global_mean,
        "relative_latent_delta": global_mean / max(baseline_mean, 1e-12),
        "spatial_ratio": inside / max(outside, 1e-12),
        "finite": bool(torch.isfinite(grid).all().item()),
    }


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists():
        raise RuntimeError("R21-R7-R4-R3 already exists; refusing to overwrite")
    prior = json.loads(R4_R2_RESULT.read_text(encoding="utf-8"))
    prior_digest = sha256(R4_R2_RESULT)
    validate_prior(prior, prior_digest)
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
    baseline_cache_reused = False

    def scales_for(step: int, active_steps: list[int]) -> list[float]:
        enabled = step in active_steps
        return [
            CONTROL_SCALE if enabled and index in ACTIVE_BLOCKS else 0.0
            for index in range(38)
        ]

    def run_branch(
        pipeline,
        control_registration,
        name: str,
        active_steps: list[int],
    ) -> dict[str, Any]:
        nonlocal baseline_cache_reused
        cache_path = CACHE_ROOT / f"{name}.pt"
        source_cache = cache_path
        if (
            not source_cache.exists()
            and name == "baseline"
            and BASELINE_CACHE_FALLBACK is not None
            and BASELINE_CACHE_FALLBACK.exists()
        ):
            source_cache = BASELINE_CACHE_FALLBACK
            baseline_cache_reused = True
        if source_cache.exists():
            cached = torch.load(source_cache, map_location="cpu", weights_only=False)
            if (
                cached.get("seed") == SEED
                and cached.get("active_steps") == active_steps
                and cached.get("active_blocks") == ACTIVE_BLOCKS
            ):
                print(json.dumps({"branch": name, "progress": "checkpoint_loaded"}), flush=True)
                return cached["branch"]
        profiles: list[dict[str, Any]] = []
        latents: list[torch.Tensor] = []
        updates: list[float] = []
        previous: torch.Tensor | None = None
        events = [{"effective_step": 0, "scale": 0.0, "identity": "BO"}]
        set_scale(pipeline, 0.0)
        control_registration.configure(
            token_controls, scales_for(0, active_steps)
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
            if next_step < STEPS:
                control_registration.configure(
                    token_controls, scales_for(next_step, active_steps)
                )
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
        branch = {
            "name": name,
            "active_steps": active_steps,
            "events": events,
            "profiles": profiles,
            "latents": latents,
            "updates": updates,
            "final_latent": output.images.detach().cpu(),
            "latent_critic": latent_critic(profiles),
        }
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "seed": SEED,
                "active_steps": active_steps,
                "active_blocks": ACTIVE_BLOCKS,
                "branch": branch,
            },
            cache_path,
        )
        return branch

    baseline = run_branch(pipe, registration, "baseline", [])
    branches = {
        name: run_branch(pipe, registration, name, steps)
        for name, steps in WINDOWS.items()
    }
    profiles: dict[str, Any] = {}
    for name, branch in branches.items():
        comparisons = []
        for step in range(STEPS):
            spatial = spatial_metrics(
                baseline["latents"][step], branch["latents"][step], union_mask
            )
            base_update = baseline["updates"][step]
            active_update = branch["updates"][step]
            ratio = 1.0 if step == 0 else active_update / max(base_update, 1e-12)
            comparisons.append({"step": step, "update_norm_ratio": ratio, **spatial})
        ratios = [item["update_norm_ratio"] for item in comparisons[1:]]
        max_delta = max(item["relative_latent_delta"] for item in comparisons)
        final_ratio = comparisons[-1]["spatial_ratio"]
        critic = branch["latent_critic"]
        events_match = branch["events"] == baseline["events"]
        all_finite = all(item["finite"] for item in comparisons)
        eligible = (
            not critic["blocked"]
            and max_delta < MAX_RELATIVE_LATENT_DELTA
            and min(ratios) >= MIN_UPDATE_NORM_RATIO
            and max(ratios) <= MAX_UPDATE_NORM_RATIO
            and final_ratio >= MIN_FINAL_SPATIAL_RATIO
            and all_finite
            and events_match
        )
        profiles[name] = {
            "active_steps": branch["active_steps"],
            "latent_critic": critic,
            "max_relative_latent_delta": max_delta,
            "minimum_update_norm_ratio": min(ratios),
            "maximum_update_norm_ratio": max(ratios),
            "final_spatial_ratio": final_ratio,
            "all_steps_finite": all_finite,
            "identity_events_match": events_match,
            "eligible": eligible,
            "steps": comparisons,
        }
    eligible_names = [name for name, profile in profiles.items() if profile["eligible"]]
    selected = (
        max(
            eligible_names,
            key=lambda name: (
                profiles[name]["final_spatial_ratio"],
                -profiles[name]["max_relative_latent_delta"],
            ),
        )
        if eligible_names
        else None
    )
    passed = (
        not baseline["latent_critic"]["blocked"]
        and selected is not None
        and vae_calls == {"forward": 0, "decode": 0}
    )
    forward_hook.remove()
    decode_hook.remove()
    registration.unregister()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "phase": PHASE,
        "status": "PASS_DENOISE_TIME_WINDOW_ISOLATION" if passed else "FAIL",
        "negative_fixture": {
            "path": str(R4_R2_RESULT.resolve()),
            "sha256": prior_digest,
            "status": prior["status"],
            NEGATIVE_FIXTURE_FLAG: True,
        },
        "seed": SEED,
        "steps": STEPS,
        "guidance_scale": GUIDANCE,
        "spatial_profile": {
            "active_blocks": ACTIVE_BLOCKS,
            "scale": CONTROL_SCALE,
        },
        "windows": WINDOWS,
        "thresholds": {
            "maximum_relative_latent_delta": MAX_RELATIVE_LATENT_DELTA,
            "minimum_update_norm_ratio": MIN_UPDATE_NORM_RATIO,
            "maximum_update_norm_ratio": MAX_UPDATE_NORM_RATIO,
            "minimum_final_spatial_ratio": MIN_FINAL_SPATIAL_RATIO,
        },
        "baseline": {
            "events": baseline["events"],
            "profile_count": len(baseline["profiles"]),
            "latent_critic": baseline["latent_critic"],
        },
        "profiles": profiles,
        "eligible_profiles": eligible_names,
        "selected_profile": selected,
        "runtime": {
            "seconds": round(time.perf_counter() - started, 3),
            "gpu_before_mib": gpu_before,
            "gpu_after_mib": gpu_used_mib(),
        },
        "guards": {
            "evaluated_trajectory_count": len(WINDOWS) + 1,
            "executed_trajectory_count": len(WINDOWS)
            if baseline_cache_reused
            else len(WINDOWS) + 1,
            "transformer_forward_count": STEPS
            * (len(WINDOWS) if baseline_cache_reused else len(WINDOWS) + 1),
            "scheduler_step_count": STEPS
            * (len(WINDOWS) if baseline_cache_reused else len(WINDOWS) + 1),
            "vae_calls": vae_calls,
            "images_created": 0,
            "branch_checkpoints_used": True,
            "baseline_cache_reused": baseline_cache_reused,
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
    del pipe, control, registration, baseline, branches
    gc.collect()
    torch.cuda.empty_cache()
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
