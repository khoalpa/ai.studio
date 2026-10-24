from __future__ import annotations

import gc
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as functional
from PIL import Image
from run_phase4lr9r7r3r21r7r4_full_transformer_control_ab import (
    BO_REFERENCE,
    GRID,
    HIDDEN_SIZE,
    IDENTITY_CROP,
    LARGE_ROOT,
    SIGLIP_ROOT,
    STEPS,
    block_metrics,
    gpu_used_mib,
    load_control_tokens,
    set_identity_scale,
)
from run_phase4lr9r7r3r21r7r4r5r3r3_full_transformer_structural_ab import (
    ADAPTER_ROOT,
    CONTRACT_PATH,
    EXPECTED_CONTRACT_SHA256,
    SEED,
    STEP_INDEX,
)

from ai_story.explicit_spatial_control import (
    ExplicitSpatialControlResidual,
    StagedExplicitControlRegistration,
)
from ai_story.image_gate_profiles import PHOTOREALISTIC_INTERACTION_PROMPT
from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R3_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r3-full-transformer-structural-ab-v1/"
    "phase4lr9r7r3r21r7r4r5r3r3-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r4-pose-contact-isolation-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r4-result.json"
PHASE = "4L-R9-R7-R3-R21-R7-R4-R5-R3-R4"
PASS_STATUS = "PASS_POSE_CONTACT_CHANNEL_WINDOW_ISOLATION"
EXPECTED_PRIOR_CLOSURE = "OPEN_PENDING_SINGLE_STEP_STRUCTURAL_CALIBRATION"
PASS_CLOSURE = "OPEN_PENDING_LATENT_TRAJECTORY_AB"
FAIL_CLOSURE = "OPEN_PENDING_STRUCTURAL_CHANNEL_REDESIGN"
COMBINED_PROFILE = "combined_structural_full"
REQUIRE_NON_EARLY_PROFILE = True
MIDDLE_SCALE = 0.0025
EARLY_SCALE = 0.00125
CHANNEL_ORDER = ("pose", "contact", "prop")
WINDOWS = {
    "full_middle": list(range(18, 28)),
    "early_middle": list(range(18, 23)),
    "late_middle": list(range(23, 28)),
}
PROFILES = {
    "pose_full": {"channels": ["pose"], "window": "full_middle"},
    "contact_full": {"channels": ["contact"], "window": "full_middle"},
    "prop_full": {"channels": ["prop"], "window": "full_middle"},
    "contact_prop_full": {
        "channels": ["contact", "prop"],
        "window": "full_middle",
    },
    "all_full": {
        "channels": ["pose", "contact", "prop"],
        "window": "full_middle",
    },
    "all_early_middle": {
        "channels": ["pose", "contact", "prop"],
        "window": "early_middle",
    },
    "all_late_middle": {
        "channels": ["pose", "contact", "prop"],
        "window": "late_middle",
    },
    "combined_structural_full": {
        "channels": ["pose", "contact", "prop"],
        "window": "full_middle",
        "early_framing": True,
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_controls() -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    raw = load_control_tokens()
    framing = raw[..., :1]
    pose = raw[..., 1].reshape(1, 1, *GRID).float()
    prop = raw[..., 2].reshape(1, 1, *GRID).float()
    near_prop = functional.max_pool2d(prop, kernel_size=3, stride=1, padding=1).bool()
    contact = pose.bool() & near_prop
    pose_without_contact = pose.bool() & ~contact
    channels = {
        "pose": pose_without_contact.reshape(1, -1, 1),
        "contact": contact.reshape(1, -1, 1),
        "prop": prop.bool().reshape(1, -1, 1),
    }
    return framing, channels


def negative_middle_dominance(prior: dict[str, Any]) -> float:
    return prior["profiles"]["middle_pose_contact_only"]["minimum_spatial_dominance_ratio"]


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R4 checkpoint already exists; refusing to overwrite")
    prior = json.loads(R3_RESULT.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if (
        prior["status"] != "FAIL"
        or prior["phase4l_closure"]["status"] != EXPECTED_PRIOR_CLOSURE
        or sha256(CONTRACT_PATH) != EXPECTED_CONTRACT_SHA256
    ):
        raise RuntimeError("R3-R3 failure checkpoint or contract changed")
    gpu_before = gpu_used_mib()
    if gpu_before > 512:
        raise RuntimeError(f"GPU is not exclusive: {gpu_before} MiB already used")

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
    identity_ids = {
        name: id(processor)
        for name, processor in pipe.transformer.attn_processors.items()
        if isinstance(processor, RegionalSD3IPAdapterProcessor)
    }

    generator = torch.Generator(device="cpu").manual_seed(SEED)
    framing_adapter = ExplicitSpatialControlResidual(
        torch.randn((1, HIDDEN_SIZE), generator=generator)
    ).to(torch.bfloat16)
    middle_adapter = ExplicitSpatialControlResidual(
        torch.randn((len(CHANNEL_ORDER), HIDDEN_SIZE), generator=generator)
    ).to(torch.bfloat16)
    registration = StagedExplicitControlRegistration(
        pipe.transformer,
        {"early_framing_cast": framing_adapter, "middle_channels": middle_adapter},
    )
    framing, split = split_controls()
    middle_tokens = torch.cat([split[name] for name in CHANNEL_ORDER], -1)
    channel_index = {name: index for index, name in enumerate(CHANNEL_ORDER)}

    pipe.enable_model_cpu_offload(device="cuda")
    pipe.scheduler.set_timesteps(STEPS, device="cpu")
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
    latent = torch.randn((1, 16, 64, 64), generator=generator, dtype=torch.bfloat16).to(
        pipe._execution_device
    )
    timestep = pipe.scheduler.timesteps[STEP_INDEX].reshape(1).to(pipe._execution_device)
    attention_kwargs = {
        "ip_adapter_image_embeds": identity_embedding,
        "regional_attention_mask": torch.zeros(
            (1, GRID[0] * GRID[1], 1), device=pipe._execution_device
        ),
    }
    set_identity_scale(pipe, 0.0)

    baseline_activations: dict[int, torch.Tensor] = {}
    current_activations: list[torch.Tensor] = []
    mode = {"baseline": True}

    def capture(index: int):
        def hook(_module, _inputs, output):
            hidden = output[1].detach().cpu()
            if mode["baseline"]:
                baseline_activations[index] = hidden
            else:
                current_activations.append(hidden)
            return None

        return hook

    handles = [
        block.register_forward_hook(capture(index))
        for index, block in enumerate(pipe.transformer.transformer_blocks)
    ]
    with torch.inference_mode():
        registration.configure_stage("early_framing_cast", framing, [0.0] * 38)
        registration.configure_stage("middle_channels", middle_tokens, [0.0] * 38)
        baseline_output = (
            pipe.transformer(
                hidden_states=latent,
                timestep=timestep,
                encoder_hidden_states=prompt_embeds,
                pooled_projections=pooled_embeds,
                joint_attention_kwargs=dict(attention_kwargs),
                return_dict=False,
            )[0]
            .detach()
            .cpu()
        )

    acceptance = contract["acceptance"]
    results: dict[str, Any] = {}
    for name, spec in PROFILES.items():
        mode["baseline"] = False
        current_activations.clear()
        selected = torch.zeros_like(middle_tokens)
        for channel in spec["channels"]:
            selected[..., channel_index[channel]] = middle_tokens[..., channel_index[channel]]
        blocks = WINDOWS[spec["window"]]
        registration.configure_stage(
            "middle_channels",
            selected,
            [MIDDLE_SCALE if index in blocks else 0.0 for index in range(38)],
        )
        early_enabled = bool(spec.get("early_framing", False))
        registration.configure_stage(
            "early_framing_cast",
            framing,
            [EARLY_SCALE if early_enabled and index < 10 else 0.0 for index in range(38)],
        )
        with torch.inference_mode():
            output = (
                pipe.transformer(
                    hidden_states=latent,
                    timestep=timestep,
                    encoder_hidden_states=prompt_embeds,
                    pooled_projections=pooled_embeds,
                    joint_attention_kwargs=dict(attention_kwargs),
                    return_dict=False,
                )[0]
                .detach()
                .cpu()
            )
        mask = selected.any(dim=-1).reshape(-1)
        if early_enabled:
            mask |= framing.any(dim=-1).reshape(-1)
        metrics = [
            {"block": index, **block_metrics(value, baseline_activations[index], mask)}
            for index, value in enumerate(current_activations)
        ]
        injection_blocks = ([*range(10)] if early_enabled else []) + blocks
        active_metrics = [item for item in metrics if item["block"] in injection_blocks]
        min_locality = min(item["localization_ratio"] for item in active_metrics)
        max_relative = max(item["relative_global_delta"] for item in active_metrics)
        norm_ratio = float(
            output.float().norm().item() / max(baseline_output.float().norm().item(), 1e-12)
        )
        checks = {
            "pre_onset_clean": all(
                item["global_mean_abs_delta"] == 0.0 for item in metrics[: min(injection_blocks)]
            ),
            "all_finite": all(item["finite"] for item in metrics),
            "spatial_dominance": min_locality >= acceptance["minimum_spatial_dominance_ratio"],
            "global_delta_bounded": max_relative < acceptance["maximum_relative_global_delta"],
            "norm_bounded": acceptance["update_norm_ratio_range"][0]
            <= norm_ratio
            <= acceptance["update_norm_ratio_range"][1],
        }
        results[name] = {
            "channels": spec["channels"],
            "window": spec["window"],
            "active_blocks": injection_blocks,
            "active_token_count": int(mask.sum()),
            "minimum_spatial_dominance_ratio": min_locality,
            "maximum_relative_global_delta": max_relative,
            "output_norm_ratio": norm_ratio,
            "final_output_mean_abs_delta": float(
                (output.float() - baseline_output.float()).abs().mean()
            ),
            "checks": checks,
            "eligible": all(checks.values()),
            "block_metrics": metrics,
        }
        del output

    eligible_middle = [
        name
        for name, value in results.items()
        if value["eligible"] and not PROFILES[name].get("early_framing", False)
    ]
    selected = (
        max(
            eligible_middle,
            key=lambda name: results[name]["minimum_spatial_dominance_ratio"],
        )
        if eligible_middle
        else None
    )
    combined_pass = results[COMBINED_PROFILE]["eligible"]
    identity_preserved = identity_ids == {
        name: id(processor)
        for name, processor in pipe.transformer.attn_processors.items()
        if isinstance(processor, RegionalSD3IPAdapterProcessor)
    }
    passed = (
        (selected is not None or not REQUIRE_NON_EARLY_PROFILE)
        and combined_pass
        and identity_preserved
    )
    for handle in handles:
        handle.remove()
    registration.unregister()
    del pipe, registration, framing_adapter, middle_adapter, identity_embedding
    del latent, prompt_embeds, pooled_embeds, baseline_output
    gc.collect()
    torch.cuda.empty_cache()

    result = {
        "schema_version": "1.0",
        "phase": PHASE,
        "status": PASS_STATUS if passed else "FAIL",
        "negative_fixture": {
            "phase": prior["phase"],
            "status": prior["status"],
            "middle_spatial_dominance": negative_middle_dominance(prior),
        },
        "channel_counts": {name: int(value.sum()) for name, value in split.items()},
        "profiles": results,
        "eligible_middle_profiles": eligible_middle,
        "selected_middle_profile": selected,
        "combined_structural_pass": combined_pass,
        "identity_processors_preserved": identity_preserved,
        "phase4l_closure": {
            "status": (PASS_CLOSURE if passed else FAIL_CLOSURE),
            "all_requirements_satisfied": False,
        },
        "runtime": {
            "seconds": round(time.perf_counter() - started, 3),
            "gpu_before_mib": gpu_before,
            "gpu_after_mib": gpu_used_mib(),
        },
        "guards": {
            "full_transformer_forward_count": 1 + len(PROFILES),
            "scheduler_step_called": False,
            "trajectory_run": False,
            "vae_called": False,
            "images_created": 0,
            "critic_threshold_relaxed": False,
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
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
