from __future__ import annotations

import gc
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch
from PIL import Image
from run_phase4lr9r7r3r21r5_regional_trajectory import (
    IDENTITY_CROP,
    boundary_diagnostics,
    set_scale,
    token_mask,
)
from run_phase4lr9r7r3r21r7r4r2_late_window_trajectory import (
    ADAPTER_ROOT,
    BO_REFERENCE,
    GUIDANCE,
    LARGE_ROOT,
    LAYOUT_PATH,
    MAX_RELATIVE_LATENT_DELTA,
    MAX_UPDATE_NORM_RATIO,
    ME_REFERENCE,
    MIN_FINAL_SPATIAL_RATIO,
    MIN_UPDATE_NORM_RATIO,
    SEED,
    SIGLIP_ROOT,
    STEPS,
    critic,
    gpu_used_mib,
    spatial_delta_metrics,
)
from run_phase4lr9r7r3r21r7r4r5r3r4_pose_contact_isolation import (
    HIDDEN_SIZE,
)
from run_phase4lr9r7r3r21r7r4r5r3r5_combined_contact_roi import (
    split_controls,
)

from ai_story.explicit_spatial_control import (
    ExplicitSpatialControlResidual,
    StagedExplicitControlRegistration,
)
from ai_story.image_gate_profiles import (
    PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
    PHOTOREALISTIC_INTERACTION_PROMPT,
)
from ai_story.latent_discontinuity import (
    LatentDiscontinuityDecision,
    PairedLatentDiscontinuityConfig,
    evaluate_paired_latent_discontinuity,
)
from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R5_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r5-combined-contact-roi-v1/phase4lr9r7r3r21r7r4r5r3r5-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r6-structural-trajectory-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r6-result.json"
PHASE = "4L-R9-R7-R3-R21-R7-R4-R5-R3-R6"
EXPECTED_PRIOR_STATUS = "PASS_COMBINED_SCHEDULE_AND_CONTACT_ROI_ISOLATION"
EXPECTED_PRIOR_CLOSURE = "OPEN_PENDING_LATENT_TRAJECTORY_AB"
BASELINE_CACHE_INPUT: Path | None = None
BASELINE_CACHE_OUTPUT: Path | None = None
ACTIVE_LATENT_OUTPUT: Path | None = None
EARLY_CONTROLS_OVERRIDE: torch.Tensor | None = None
SPATIAL_REGION_MASKS_OVERRIDE: dict[str, torch.Tensor] | None = None
EARLY_BLOCKS = list(range(10))
MIDDLE_BLOCKS = list(range(18, 23))
TERMINAL_BLOCKS: list[int] = []
EARLY_STEPS = list(range(2, 8))
MIDDLE_STEPS = list(range(8, 16))
TERMINAL_STEPS: list[int] = []
EARLY_SCALE = 0.00125
MIDDLE_SCALE = 0.0025
TERMINAL_SCALE = 0.0
ERROR_FEEDBACK = False
RESET_ERROR_FEEDBACK_PER_FORWARD = False


def decision(payload: dict[str, Any]) -> LatentDiscontinuityDecision:
    return LatentDiscontinuityDecision(**payload)


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R6 checkpoint already exists; refusing to overwrite")
    prior = json.loads(R5_RESULT.read_text(encoding="utf-8"))
    if (
        prior["status"] != EXPECTED_PRIOR_STATUS
        or prior["phase4l_closure"]["status"] != EXPECTED_PRIOR_CLOSURE
    ):
        raise RuntimeError("R3-R5 combined profile is not locked")
    gpu_before = gpu_used_mib()
    if gpu_before > 512:
        raise RuntimeError(f"GPU is not exclusive: {gpu_before} MiB")

    from diffusers import StableDiffusion3Pipeline
    from diffusers.models.attention_processor import SD3IPAdapterJointAttnProcessor2_0
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

    vector_generator = torch.Generator(device="cpu").manual_seed(SEED)
    early_channel_count = (
        EARLY_CONTROLS_OVERRIDE.shape[-1]
        if EARLY_CONTROLS_OVERRIDE is not None
        else 1
    )
    framing_vector = torch.randn((early_channel_count, HIDDEN_SIZE), generator=vector_generator)
    all_middle_vectors = torch.randn((5, HIDDEN_SIZE), generator=vector_generator)
    selected_middle_vectors = all_middle_vectors[[0, 3, 4]]
    registration = StagedExplicitControlRegistration(
        pipe.transformer,
        {
            "early_framing_cast": ExplicitSpatialControlResidual(framing_vector).to(torch.bfloat16),
            "middle_pose_contact10_prop": ExplicitSpatialControlResidual(
                selected_middle_vectors, error_feedback=ERROR_FEEDBACK
            ).to(torch.bfloat16),
        },
    )
    error_feedback_resets = {"count": 0}

    def reset_error_feedback_before_forward(_module, _inputs) -> None:
        if RESET_ERROR_FEEDBACK_PER_FORWARD:
            for adapter in registration.adapters.values():
                adapter.reset_error_feedback()
            error_feedback_resets["count"] += 1

    reset_handle = pipe.transformer.register_forward_pre_hook(reset_error_feedback_before_forward)
    framing, controls = split_controls()
    if EARLY_CONTROLS_OVERRIDE is not None:
        framing = EARLY_CONTROLS_OVERRIDE
    middle = torch.cat([controls[name] for name in ("pose", "contact_10", "prop")], dim=-1)
    union_mask = framing.any(dim=-1) | middle.any(dim=-1)

    pipe.enable_model_cpu_offload(device="cuda")
    with Image.open(BO_REFERENCE) as source:
        bo_crop = source.convert("RGB").crop(IDENTITY_CROP)
    with Image.open(ME_REFERENCE) as source:
        mother_crop = source.convert("RGB").crop(IDENTITY_CROP)
    with torch.inference_mode():
        bo_embedding = pipe.encode_image(bo_crop, pipe._execution_device)
        mother_embedding = pipe.encode_image(mother_crop, pipe._execution_device)
    cfg_bo = torch.cat([torch.zeros_like(bo_embedding), bo_embedding], dim=0)
    cfg_mother = torch.cat([torch.zeros_like(mother_embedding), mother_embedding], dim=0)
    regions = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))["regions"]
    interaction = regions["interaction"]["box"]
    bo_mask = token_mask(regions["bo_identity"]["box"], interaction)
    mother_mask = token_mask(regions["mother_identity"]["box"], interaction)

    vae_calls = {"forward": 0, "decode": 0}
    vae_hook = pipe.vae.register_forward_pre_hook(
        lambda *_args, **_kwargs: vae_calls.__setitem__("forward", vae_calls["forward"] + 1)
    )
    decode_hook = pipe.vae.decoder.register_forward_pre_hook(
        lambda *_args, **_kwargs: vae_calls.__setitem__("decode", vae_calls["decode"] + 1)
    )

    def configure_structural(step: int, enabled: bool) -> None:
        early_active = enabled and step in EARLY_STEPS
        middle_active = enabled and step in MIDDLE_STEPS
        terminal_active = enabled and step in TERMINAL_STEPS
        registration.configure_stage(
            "early_framing_cast",
            framing,
            [EARLY_SCALE if early_active and index in EARLY_BLOCKS else 0.0 for index in range(38)],
        )
        registration.configure_stage(
            "middle_pose_contact10_prop",
            middle,
            [
                (
                    MIDDLE_SCALE
                    if middle_active and index in MIDDLE_BLOCKS
                    else TERMINAL_SCALE
                    if terminal_active and index in TERMINAL_BLOCKS
                    else 0.0
                )
                for index in range(38)
            ],
        )

    def run_branch(name: str, enabled: bool) -> dict[str, Any]:
        for adapter in registration.adapters.values():
            adapter.error_feedback = ERROR_FEEDBACK
            adapter.reset_error_feedback()
        profiles: list[dict[str, Any]] = []
        latents: list[torch.Tensor] = []
        updates: list[float] = []
        previous: torch.Tensor | None = None
        identity_events = [{"effective_step": 0, "scale": 0.0, "identity": "BO"}]
        structural_events = [{"effective_step": 0, "early": False, "middle": False}]
        set_scale(pipe, 0.0)
        configure_structural(0, enabled)
        pipe._joint_attention_kwargs = {"regional_attention_mask": bo_mask}

        def callback(_pipe, step_index, timestep, callback_kwargs):
            nonlocal previous
            latent = callback_kwargs["latents"].detach().cpu()
            latents.append(latent)
            update = (
                0.0
                if previous is None
                else float((latent.float() - previous.float()).norm().item())
            )
            updates.append(update)
            previous = latent
            profiles.append(
                {
                    "step": int(step_index),
                    "timestep": float(timestep.item()),
                    "update_norm": update,
                    "boundaries": boundary_diagnostics(latent),
                    "error_feedback_mean_abs": {
                        adapter_name: (
                            float(adapter.pending_error.float().abs().mean())
                            if adapter.pending_error is not None
                            else 0.0
                        )
                        for adapter_name, adapter in registration.adapters.items()
                    },
                    "error_feedback_reset_count": error_feedback_resets["count"],
                }
            )
            next_step = step_index + 1
            configure_structural(next_step, enabled)
            if next_step in sorted({2, 8, 16, *TERMINAL_STEPS}):
                structural_events.append(
                    {
                        "effective_step": next_step,
                        "early": enabled and next_step in EARLY_STEPS,
                        "middle": enabled and next_step in MIDDLE_STEPS,
                        "terminal": enabled and next_step in TERMINAL_STEPS,
                    }
                )
            if next_step == 8:
                set_scale(_pipe, 0.25)
                identity_events.append({"effective_step": 8, "scale": 0.25, "identity": "BO"})
            elif next_step == 12:
                _pipe._joint_attention_kwargs["ip_adapter_image_embeds"] = cfg_mother
                _pipe._joint_attention_kwargs["regional_attention_mask"] = mother_mask.to(
                    callback_kwargs["latents"].device
                )
                identity_events.append({"effective_step": 12, "scale": 0.25, "identity": "ME"})
            elif next_step == 16:
                set_scale(_pipe, 0.0)
                identity_events.append({"effective_step": 16, "scale": 0.0, "identity": "ME"})
            print(json.dumps({"branch": name, "step": next_step}), flush=True)
            return callback_kwargs

        branch_generator = torch.Generator(device="cpu").manual_seed(SEED)
        with torch.inference_mode():
            output = pipe(
                prompt=PHOTOREALISTIC_INTERACTION_PROMPT,
                negative_prompt=PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
                ip_adapter_image_embeds=cfg_bo,
                height=512,
                width=512,
                num_inference_steps=STEPS,
                guidance_scale=GUIDANCE,
                generator=branch_generator,
                output_type="latent",
                callback_on_step_end=callback,
                callback_on_step_end_tensor_inputs=["latents"],
            )
        return {
            "name": name,
            "profiles": profiles,
            "latents": latents,
            "updates": updates,
            "identity_events": identity_events,
            "structural_events": structural_events,
            "final_latent": output.images.detach().cpu(),
            "latent_critic": critic(profiles),
        }

    baseline_loaded = BASELINE_CACHE_INPUT is not None
    if BASELINE_CACHE_INPUT is not None:
        baseline = torch.load(BASELINE_CACHE_INPUT, map_location="cpu", weights_only=False)[
            "branch"
        ]
    else:
        baseline = run_branch("regional_identity_only", False)
        if BASELINE_CACHE_OUTPUT is not None:
            BASELINE_CACHE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"seed": SEED, "steps": STEPS, "branch": baseline}, BASELINE_CACHE_OUTPUT)
    active = run_branch("combined_structural_profile", True)
    if ACTIVE_LATENT_OUTPUT is not None:
        ACTIVE_LATENT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "seed": SEED,
                "steps": STEPS,
                "profile": {
                    "early_blocks": EARLY_BLOCKS,
                    "early_steps": EARLY_STEPS,
                    "early_scale": EARLY_SCALE,
                    "middle_blocks": MIDDLE_BLOCKS,
                    "middle_steps": MIDDLE_STEPS,
                    "middle_scale": MIDDLE_SCALE,
                    "terminal_blocks": TERMINAL_BLOCKS,
                    "terminal_steps": TERMINAL_STEPS,
                    "terminal_scale": TERMINAL_SCALE,
                },
                "final_latent": active["final_latent"],
            },
            ACTIVE_LATENT_OUTPUT,
        )
    comparisons = []
    region_comparisons: dict[str, list[dict[str, Any]]] = {
        name: [] for name in (SPATIAL_REGION_MASKS_OVERRIDE or {})
    }
    for step in range(STEPS):
        spatial = spatial_delta_metrics(
            baseline["latents"][step], active["latents"][step], union_mask
        )
        ratio = (
            1.0 if step == 0 else active["updates"][step] / max(baseline["updates"][step], 1e-12)
        )
        comparisons.append({"step": step, "update_norm_ratio": ratio, **spatial})
        for name, mask in (SPATIAL_REGION_MASKS_OVERRIDE or {}).items():
            region_comparisons[name].append(
                {
                    "step": step,
                    **spatial_delta_metrics(
                        baseline["latents"][step], active["latents"][step], mask
                    ),
                }
            )

    paired = asdict(
        evaluate_paired_latent_discontinuity(
            decision(baseline["latent_critic"]),
            decision(active["latent_critic"]),
            PairedLatentDiscontinuityConfig(),
        )
    )
    update_ratios = [item["update_norm_ratio"] for item in comparisons[1:]]
    gates = {
        "baseline_absolute_critic_clean": not baseline["latent_critic"]["blocked"],
        "active_absolute_critic_clean": not active["latent_critic"]["blocked"],
        "paired_critic_clean": not paired["blocked"],
        "pre_onset_clean": all(item["global_mean_abs_delta"] == 0.0 for item in comparisons[:2]),
        "relative_latent_delta_bounded": max(item["relative_latent_delta"] for item in comparisons)
        < MAX_RELATIVE_LATENT_DELTA,
        "update_norm_bounded": min(update_ratios) >= MIN_UPDATE_NORM_RATIO
        and max(update_ratios) <= MAX_UPDATE_NORM_RATIO,
        "final_spatial_ratio_sufficient": comparisons[-1]["spatial_ratio"]
        >= MIN_FINAL_SPATIAL_RATIO,
        "all_steps_finite": all(item["finite"] for item in comparisons),
        "identity_events_match": baseline["identity_events"] == active["identity_events"],
        "vae_untouched": vae_calls == {"forward": 0, "decode": 0},
    }
    passed = all(gates.values())
    vae_hook.remove()
    decode_hook.remove()
    reset_handle.remove()
    registration.unregister()
    result = {
        "schema_version": "1.0",
        "phase": PHASE,
        "status": "PASS_FULL_LATENT_TRAJECTORY_STRUCTURAL_AB" if passed else "FAIL",
        "profile": {
            "early_blocks": EARLY_BLOCKS,
            "early_steps": EARLY_STEPS,
            "early_scale": EARLY_SCALE,
            "middle_blocks": MIDDLE_BLOCKS,
            "middle_steps": MIDDLE_STEPS,
            "middle_scale": MIDDLE_SCALE,
            "middle_channels": ["pose", "contact_10", "prop"],
            "terminal_blocks": TERMINAL_BLOCKS,
            "terminal_steps": TERMINAL_STEPS,
            "terminal_scale": TERMINAL_SCALE,
            "error_feedback": ERROR_FEEDBACK,
            "reset_error_feedback_per_forward": RESET_ERROR_FEEDBACK_PER_FORWARD,
        },
        "baseline": {
            "profile_count": len(baseline["profiles"]),
            "identity_events": baseline["identity_events"],
            "latent_critic": baseline["latent_critic"],
        },
        "active": {
            "profile_count": len(active["profiles"]),
            "identity_events": active["identity_events"],
            "structural_events": active["structural_events"],
            "latent_critic": active["latent_critic"],
        },
        "paired_critic": paired,
        "comparison": {
            "steps": comparisons,
            "maximum_relative_latent_delta": max(
                item["relative_latent_delta"] for item in comparisons
            ),
            "minimum_update_norm_ratio": min(update_ratios),
            "maximum_update_norm_ratio": max(update_ratios),
            "final_spatial_ratio": comparisons[-1]["spatial_ratio"],
            "regions": {
                name: {
                    "steps": values,
                    "final_inside_mean_abs_delta": values[-1]["inside_mean_abs_delta"],
                    "final_outside_mean_abs_delta": values[-1]["outside_mean_abs_delta"],
                    "final_spatial_ratio": values[-1]["spatial_ratio"],
                }
                for name, values in region_comparisons.items()
            },
        },
        "gates": gates,
        "phase4l_closure": {
            "status": (
                "OPEN_PENDING_DECODE_AUTHORIZATION_REVIEW"
                if passed
                else "OPEN_PENDING_TRAJECTORY_REPAIR"
            ),
            "all_requirements_satisfied": False,
        },
        "runtime": {
            "seconds": round(time.perf_counter() - started, 3),
            "gpu_before_mib": gpu_before,
            "gpu_after_mib": gpu_used_mib(),
        },
        "guards": {
            "transformer_forward_count": STEPS * (1 if baseline_loaded else 2),
            "scheduler_step_count": STEPS * (1 if baseline_loaded else 2),
            "trajectory_count": 1 if baseline_loaded else 2,
            "baseline_loaded_from_cache": baseline_loaded,
            "active_latent_persisted": ACTIVE_LATENT_OUTPUT is not None,
            "error_feedback_reset_count": error_feedback_resets["count"],
            "vae_calls": vae_calls,
            "images_created": 0,
            "decode_authorized": False,
            "new_generation_authorized": False,
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
    gc.collect()
    torch.cuda.empty_cache()
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
