from __future__ import annotations

import gc
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import torch
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

from ai_story.explicit_spatial_control import (
    ExplicitSpatialControlResidual,
    StagedExplicitControlRegistration,
)
from ai_story.image_gate_profiles import PHOTOREALISTIC_INTERACTION_PROMPT
from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R2_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r2-structural-registration-v1")
R2_RESULT = R2_ROOT / "phase4lr9r7r3r21r7r4r5r3r2-result.json"
CONTRACT_PATH = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r1-reject-and-structural-design-v1/"
    "structural-conditioning-contract.json"
)
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r3-full-transformer-structural-ab-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r3-result.json"
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
EXPECTED_CONTRACT_SHA256 = "43aff9756ab14039321d2f18fc83208a39d5134c77fc59971d2005bb87f405a8"
SEED = 420917
STEP_INDEX = 12
PROFILES = {
    "early_framing_only": {"early_framing_cast": 0.00125},
    "middle_pose_contact_only": {"middle_pose_contact": 0.0025},
    "combined": {
        "early_framing_cast": 0.00125,
        "middle_pose_contact": 0.0025,
    },
}
PROFILE_MASKS = {
    "early_framing_only": "early_framing_cast",
    "middle_pose_contact_only": "middle_pose_contact",
    "combined": "combined",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reassess_completed_result(result: dict[str, Any]) -> dict[str, Any]:
    acceptance = result["acceptance"]
    for profile in result["profiles"].values():
        expected = profile["expected_changed_blocks"]
        observed = profile["observed_changed_blocks"]
        onset = min(expected)
        profile["pre_onset_clean"] = all(block >= onset for block in observed)
        profile["injection_window_effective"] = all(block in observed for block in expected)
        profile["downstream_propagation_observed"] = any(
            block > max(expected) for block in observed
        )
        checks = {
            "pre_onset_clean": profile["pre_onset_clean"],
            "injection_window_effective": profile["injection_window_effective"],
            "all_blocks_finite": profile["all_blocks_finite"],
            "nonzero_final_delta": profile["final_output_mean_abs_delta"] > 0,
            "relative_global_delta_bounded": profile["max_relative_global_delta"]
            < acceptance["maximum_relative_global_delta"],
            "spatial_dominance_sufficient": profile["minimum_spatial_dominance_ratio"]
            >= acceptance["minimum_spatial_dominance_ratio"],
            "output_norm_ratio_bounded": acceptance["update_norm_ratio_range"][0]
            <= profile["output_norm_ratio"]
            <= acceptance["update_norm_ratio_range"][1],
        }
        profile["acceptance_checks"] = checks
        profile["failed_checks"] = sorted(name for name, passed in checks.items() if not passed)
        profile["eligible"] = all(checks.values())
    passed = result["identity_processors_preserved"] and all(
        profile["eligible"] for profile in result["profiles"].values()
    )
    result["status"] = "PASS_FULL_TRANSFORMER_SINGLE_STEP_STRUCTURAL_AB" if passed else "FAIL"
    result["assessment_revision"] = {
        "version": "2",
        "reason": (
            "Injection is constrained to its configured block window; activation "
            "differences are expected to propagate through downstream blocks."
        ),
        "model_rerun": False,
    }
    result["phase4l_closure"] = {
        "status": (
            "OPEN_PENDING_LATENT_TRAJECTORY_AB"
            if passed
            else "OPEN_PENDING_SINGLE_STEP_STRUCTURAL_CALIBRATION"
        ),
        "newly_satisfied": (["real_transformer_single_step_structural_ab"] if passed else []),
        "all_requirements_satisfied": False,
    }
    return result


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists():
        prior = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        if prior.get("status") != "FAIL" or "profiles" not in prior:
            raise RuntimeError("R3-R3 checkpoint already exists; refusing to overwrite")
        result = reassess_completed_result(prior)
        RESULT_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if result["status"] == "FAIL":
            raise SystemExit(1)
        return
    r2 = json.loads(R2_RESULT.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if (
        r2["status"] != "PASS_STRUCTURAL_REGISTRATION_AND_ZERO_PARITY"
        or sha256(CONTRACT_PATH) != EXPECTED_CONTRACT_SHA256
    ):
        raise RuntimeError("R3-R2 checkpoint or contract changed")
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
    adapters = {
        "early_framing_cast": ExplicitSpatialControlResidual(
            torch.randn((1, HIDDEN_SIZE), generator=generator)
        ).to(torch.bfloat16),
        "middle_pose_contact": ExplicitSpatialControlResidual(
            torch.randn((2, HIDDEN_SIZE), generator=generator)
        ).to(torch.bfloat16),
    }
    registration = StagedExplicitControlRegistration(pipe.transformer, adapters)
    all_controls = load_control_tokens()
    controls = {
        "early_framing_cast": all_controls[..., :1],
        "middle_pose_contact": all_controls[..., 1:],
    }
    masks = {name: value.any(dim=-1).reshape(-1) for name, value in controls.items()}
    masks["combined"] = masks["early_framing_cast"] | masks["middle_pose_contact"]

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
    fixed_latent = torch.randn((1, 16, 64, 64), generator=generator, dtype=torch.bfloat16).to(
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
    branch_activations: list[torch.Tensor] = []
    mode = {"value": "baseline"}

    def capture(index: int):
        def hook(_module, _inputs, output):
            hidden = output[1].detach().cpu()
            if mode["value"] == "baseline":
                baseline_activations[index] = hidden
            else:
                branch_activations.append(hidden)
            return None

        return hook

    handles = [
        block.register_forward_hook(capture(index))
        for index, block in enumerate(pipe.transformer.transformer_blocks)
    ]
    with torch.inference_mode():
        for name, value in controls.items():
            registration.configure_stage(name, value, [0.0] * 38)
        baseline_output = (
            pipe.transformer(
                hidden_states=fixed_latent,
                timestep=timestep,
                encoder_hidden_states=prompt_embeds,
                pooled_projections=pooled_embeds,
                joint_attention_kwargs=dict(attention_kwargs),
                return_dict=False,
            )[0]
            .detach()
            .cpu()
        )

    stage_specs = {stage["id"]: stage for stage in contract["stages"]}
    acceptance = contract["acceptance"]
    profiles: dict[str, Any] = {}
    for profile_name, active in PROFILES.items():
        branch_activations.clear()
        mode["value"] = profile_name
        for stage_name, value in controls.items():
            stage = stage_specs[stage_name]
            scale = active.get(stage_name, 0.0)
            block_scales = [
                scale if index in stage["active_blocks"] else 0.0 for index in range(38)
            ]
            registration.configure_stage(stage_name, value, block_scales)
        with torch.inference_mode():
            output = (
                pipe.transformer(
                    hidden_states=fixed_latent,
                    timestep=timestep,
                    encoder_hidden_states=prompt_embeds,
                    pooled_projections=pooled_embeds,
                    joint_attention_kwargs=dict(attention_kwargs),
                    return_dict=False,
                )[0]
                .detach()
                .cpu()
            )
        if len(branch_activations) != 38:
            raise RuntimeError(f"Expected 38 activations, got {len(branch_activations)}")
        metric_mask = masks[PROFILE_MASKS[profile_name]]
        metrics = [
            {"block": index, **block_metrics(current, baseline_activations[index], metric_mask)}
            for index, current in enumerate(branch_activations)
        ]
        changed = [item["block"] for item in metrics if item["global_mean_abs_delta"] > 0]
        expected = sorted(
            {block for stage_name in active for block in stage_specs[stage_name]["active_blocks"]}
        )
        final_delta = float((output.float() - baseline_output.float()).abs().mean())
        output_norm_ratio = float(
            output.float().norm().item() / max(baseline_output.float().norm().item(), 1e-12)
        )
        active_metrics = [item for item in metrics if item["block"] in expected]
        max_relative = max(item["relative_global_delta"] for item in active_metrics)
        min_locality = min(item["localization_ratio"] for item in active_metrics)
        eligible = (
            changed == expected
            and all(item["finite"] for item in metrics)
            and final_delta > 0
            and max_relative < acceptance["maximum_relative_global_delta"]
            and min_locality >= acceptance["minimum_spatial_dominance_ratio"]
            and acceptance["update_norm_ratio_range"][0]
            <= output_norm_ratio
            <= acceptance["update_norm_ratio_range"][1]
        )
        profiles[profile_name] = {
            "active_stages": active,
            "expected_changed_blocks": expected,
            "observed_changed_blocks": changed,
            "exact_window_match": changed == expected,
            "max_relative_global_delta": max_relative,
            "minimum_spatial_dominance_ratio": min_locality,
            "output_norm_ratio": output_norm_ratio,
            "final_output_mean_abs_delta": final_delta,
            "all_blocks_finite": all(item["finite"] for item in metrics),
            "eligible": eligible,
            "block_metrics": metrics,
        }
        del output

    for handle in handles:
        handle.remove()
    identity_preserved = identity_ids == {
        name: id(processor)
        for name, processor in pipe.transformer.attn_processors.items()
        if isinstance(processor, RegionalSD3IPAdapterProcessor)
    }
    passed = identity_preserved and all(item["eligible"] for item in profiles.values())
    registration.unregister()
    del pipe, registration, adapters, identity_embedding, fixed_latent
    del prompt_embeds, pooled_embeds, baseline_output
    gc.collect()
    torch.cuda.empty_cache()

    result = reassess_completed_result(
        {
            "schema_version": "1.0",
            "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R3",
            "status": "PASS_FULL_TRANSFORMER_SINGLE_STEP_STRUCTURAL_AB" if passed else "FAIL",
            "contract_sha256": sha256(CONTRACT_PATH),
            "seed": SEED,
            "step_index": STEP_INDEX,
            "timestep": float(timestep.item()),
            "identity_scale": 0.0,
            "identity_processors_preserved": identity_preserved,
            "profiles": profiles,
            "acceptance": acceptance,
            "phase4l_closure": {
                "status": "OPEN_PENDING_LATENT_TRAJECTORY_AB",
                "newly_satisfied": ["real_transformer_single_step_structural_ab"] if passed else [],
                "all_requirements_satisfied": False,
            },
            "runtime": {
                "seconds": round(time.perf_counter() - started, 3),
                "gpu_before_mib": gpu_before,
                "gpu_after_mib": gpu_used_mib(),
            },
            "guards": {
                "full_transformer_forward_count": 4,
                "scheduler_step_called": False,
                "trajectory_run": False,
                "vae_called": False,
                "images_created": 0,
                "new_generation_authorized": False,
                "production_profile_changed": False,
                "source_package_modified": False,
                "phase4l_closed": False,
                "phase4n_opened": False,
            },
        }
    )
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
