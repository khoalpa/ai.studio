from __future__ import annotations

import argparse
import gc
import json
import os
import time
from pathlib import Path
from typing import Any

import torch
from PIL import Image
from run_phase4lr9r7r3r21r5_regional_trajectory import IDENTITY_CROP, set_scale, token_mask
from run_phase4lr9r7r3r21r7r4_full_transformer_control_ab import (
    HIDDEN_SIZE,
    block_metrics,
    gpu_used_mib,
)
from run_phase4lr9r7r3r21r7r4r5r3r5_combined_contact_roi import split_controls
from run_phase4lr9r7r3r21r7r4r5r3r6_structural_trajectory import (
    ADAPTER_ROOT,
    BO_REFERENCE,
    LARGE_ROOT,
    LAYOUT_PATH,
    ME_REFERENCE,
    SEED,
    SIGLIP_ROOT,
    STEPS,
)

from ai_story.explicit_spatial_control import (
    ExplicitSpatialControlResidual,
    StagedExplicitControlRegistration,
)
from ai_story.image_gate_profiles import PHOTOREALISTIC_INTERACTION_PROMPT
from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R7_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r7-scale-terminal-isolation-v1")
R7_RESULT = R7_ROOT / "phase4lr9r7r3r21r7r4r5r3r7-result.json"
BASELINE_CACHE = R7_ROOT / "baseline-cache.pt"
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r8-precision-isolation-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r8-result.json"
R8_RESULT = RESULT_PATH
R9_OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r9-error-feedback-isolation-v1")
R9_RESULT = R9_OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r9-result.json"
R10_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10-error-feedback-trajectory-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10-result.json"
)
R10_R1_OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r10r1-step-bounded-feedback-v1")
R10_R1_RESULT = R10_R1_OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r1-result.json"
R10_R1_R1_OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r1r1-clean-scale-revalidation-v1"
)
R10_R1_R1_RESULT = R10_R1_R1_OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r1r1-result.json"
SCALES = [0.000625, 0.00125, 0.0025]
PROBES = {
    2: {"stage": "early", "blocks": list(range(10)), "identity": "bo", "identity_scale": 0.0},
    8: {"stage": "middle", "blocks": list(range(18, 23)), "identity": "bo", "identity_scale": 0.25},
    15: {
        "stage": "middle",
        "blocks": list(range(18, 23)),
        "identity": "mother",
        "identity_scale": 0.25,
    },
    22: {
        "stage": "middle",
        "blocks": list(range(28, 38)),
        "identity": "mother",
        "identity_scale": 0.0,
    },
}


def quantization_metrics(
    hidden_states: torch.Tensor,
    controls: torch.Tensor,
    vectors: torch.Tensor,
    scale: float,
    *,
    accumulate_in_fp32: bool,
) -> dict[str, float | int]:
    """Measure what survives the final BF16 write at an injection boundary."""
    hidden = hidden_states.to(torch.bfloat16)
    controls = controls.cpu()
    vectors = vectors.cpu()
    if accumulate_in_fp32:
        intended = torch.matmul(controls.float(), vectors.float()) * float(scale)
        written = (hidden.float() + intended).to(torch.bfloat16)
    else:
        intended = torch.matmul(controls.to(torch.bfloat16), vectors.to(torch.bfloat16)) * float(
            scale
        )
        written = hidden + intended
    observed = written.float() - hidden.float()
    intended = intended.float()
    nonzero = intended != 0
    observed_nonzero = observed != 0
    surviving = nonzero & observed_nonzero
    intended_count = int(nonzero.sum())
    observed_count = int((nonzero & observed_nonzero).sum())
    sign_matches = int((torch.sign(observed[surviving]) == torch.sign(intended[surviving])).sum())
    error = (observed - intended).abs().mean().item()
    signal = intended.abs().mean().item()
    return {
        "intended_nonzero_count": intended_count,
        "observed_nonzero_count": observed_count,
        "quantized_to_zero_fraction": (
            1.0 - observed_count / intended_count if intended_count else 0.0
        ),
        "sign_preservation_fraction": (
            sign_matches / int(surviving.sum()) if surviving.any() else 1.0
        ),
        "mean_absolute_signal": signal,
        "mean_absolute_quantization_error": error,
        "signal_to_quantization_error_ratio": signal / max(error, 1e-30),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--error-feedback", action="store_true", help="run the R9 causal branch")
    parser.add_argument(
        "--step-bounded-feedback",
        action="store_true",
        help="run the R10-R1 lifecycle branch",
    )
    parser.add_argument(
        "--clean-scale-revalidation",
        action="store_true",
        help="run the R10-R1-R1 clean scale branch",
    )
    args = parser.parse_args()
    if sum((args.error_feedback, args.step_bounded_feedback, args.clean_scale_revalidation)) > 1:
        parser.error("choose only one causal branch")
    error_feedback_stage = args.error_feedback
    lifecycle_stage = args.step_bounded_feedback
    clean_scale_stage = args.clean_scale_revalidation
    output_root = (
        R10_R1_R1_OUTPUT_ROOT
        if clean_scale_stage
        else R10_R1_OUTPUT_ROOT
        if lifecycle_stage
        else R9_OUTPUT_ROOT
        if error_feedback_stage
        else OUTPUT_ROOT
    )
    result_path = (
        R10_R1_R1_RESULT
        if clean_scale_stage
        else R10_R1_RESULT
        if lifecycle_stage
        else R9_RESULT
        if error_feedback_stage
        else RESULT_PATH
    )
    os.environ["HF_HUB_OFFLINE"] = "1"
    if result_path.exists():
        raise RuntimeError("stage checkpoint already exists; refusing to overwrite")
    prior_path = (
        R10_R1_RESULT
        if clean_scale_stage
        else R10_RESULT
        if lifecycle_stage
        else R8_RESULT
        if error_feedback_stage
        else R7_RESULT
    )
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    cached = torch.load(BASELINE_CACHE, map_location="cpu", weights_only=False)
    expected_status = (
        "PASS_STEP_BOUNDED_ERROR_FEEDBACK_ISOLATION"
        if clean_scale_stage
        else "FAIL"
        if lifecycle_stage
        else "PASS_NUMERICAL_PRECISION_CAUSAL_ISOLATION"
        if error_feedback_stage
        else "FAIL"
    )
    if prior["status"] != expected_status or cached["seed"] != SEED or cached["steps"] != STEPS:
        raise RuntimeError("prior checkpoint or baseline cache changed")
    gpu_before = gpu_used_mib()
    if gpu_before > 512:
        raise RuntimeError(f"GPU is not exclusive: {gpu_before} MiB")

    from diffusers import StableDiffusion3Pipeline
    from diffusers.models.attention_processor import SD3IPAdapterJointAttnProcessor2_0
    from transformers import SiglipImageProcessor, SiglipVisionModel

    started = time.perf_counter()
    pipe = StableDiffusion3Pipeline.from_pretrained(
        LARGE_ROOT, local_files_only=True, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True
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
            replacements[name] = RegionalSD3IPAdapterProcessor(processor)
    pipe.transformer.set_attn_processor(replacements)

    vector_generator = torch.Generator(device="cpu").manual_seed(SEED)
    framing_vector = torch.randn((1, HIDDEN_SIZE), generator=vector_generator)
    all_middle_vectors = torch.randn((5, HIDDEN_SIZE), generator=vector_generator)
    middle_vectors = all_middle_vectors[[0, 3, 4]]
    adapters = {
        "early": ExplicitSpatialControlResidual(framing_vector).to(torch.bfloat16),
        "middle": ExplicitSpatialControlResidual(middle_vectors).to(torch.bfloat16),
    }
    registration = StagedExplicitControlRegistration(pipe.transformer, adapters)
    framing, controls = split_controls()
    middle = torch.cat([controls[name] for name in ("pose", "contact_10", "prop")], dim=-1)
    stage_controls = {"early": framing, "middle": middle}
    stage_masks = {name: value.any(dim=-1).reshape(-1) for name, value in stage_controls.items()}

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
        bo_crop = source.convert("RGB").crop(IDENTITY_CROP)
    with Image.open(ME_REFERENCE) as source:
        mother_crop = source.convert("RGB").crop(IDENTITY_CROP)
    with torch.inference_mode():
        embeddings = {
            "bo": pipe.encode_image(bo_crop, pipe._execution_device),
            "mother": pipe.encode_image(mother_crop, pipe._execution_device),
        }
    regions = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))["regions"]
    interaction = regions["interaction"]["box"]
    masks = {
        "bo": token_mask(regions["bo_identity"]["box"], interaction),
        "mother": token_mask(regions["mother_identity"]["box"], interaction),
    }

    results: dict[str, Any] = {}
    carry_errors: dict[str, torch.Tensor | None] = {name: None for name in adapters}
    active_scales = [0.0025] if lifecycle_stage else SCALES
    baseline_branch = cached["branch"]
    for step, spec in PROBES.items():
        latent = baseline_branch["latents"][step - 1].to(pipe._execution_device)
        timestep = pipe.scheduler.timesteps[step].reshape(1).to(pipe._execution_device)
        attention_kwargs = {
            "ip_adapter_image_embeds": embeddings[spec["identity"]],
            "regional_attention_mask": masks[spec["identity"]].to(pipe._execution_device),
        }
        set_scale(pipe, spec["identity_scale"])
        baseline_activations: dict[int, torch.Tensor] = {}
        active_activations: list[torch.Tensor] = []
        mode = {"baseline": True}

        def capture(index: int):
            def hook(_module, _inputs, output):
                hidden = output[1].detach().cpu()
                if mode["baseline"]:
                    baseline_activations[index] = hidden
                else:
                    active_activations.append(hidden)
                return None

            return hook

        handles = [
            block.register_forward_hook(capture(index))
            for index, block in enumerate(pipe.transformer.transformer_blocks)
        ]
        for adapter in adapters.values():
            adapter.accumulate_in_fp32 = False
            adapter.error_feedback = False
            adapter.reset_error_feedback()
        for name, value in stage_controls.items():
            registration.configure_stage(name, value, [0.0] * 38)
        with torch.inference_mode():
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

        variants: dict[str, Any] = {}
        precision_paths = (
            ("cross_step_carry", "per_step_reset")
            if lifecycle_stage
            else ("bf16_direct", "error_feedback")
            if error_feedback_stage or clean_scale_stage
            else ("bf16_direct", "fp32_accumulate")
        )
        for precision in precision_paths:
            for adapter in adapters.values():
                adapter.accumulate_in_fp32 = precision == "fp32_accumulate"
                adapter.error_feedback = precision in {
                    "error_feedback",
                    "cross_step_carry",
                    "per_step_reset",
                }
                adapter.reset_error_feedback()
            if precision == "cross_step_carry":
                for name, adapter in adapters.items():
                    adapter._quantization_error = carry_errors[name]
            for scale in active_scales:
                if clean_scale_stage:
                    for adapter in adapters.values():
                        adapter.reset_error_feedback()
                active_activations.clear()
                mode["baseline"] = False
                for name, value in stage_controls.items():
                    registration.configure_stage(
                        name,
                        value,
                        [
                            scale if name == spec["stage"] and index in spec["blocks"] else 0.0
                            for index in range(38)
                        ],
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
                metrics = [
                    {
                        "block": index,
                        **block_metrics(
                            value,
                            baseline_activations[index],
                            stage_masks[spec["stage"]],
                        ),
                    }
                    for index, value in enumerate(active_activations)
                ]
                active_metrics = [item for item in metrics if item["block"] in spec["blocks"]]
                injection_block = spec["blocks"][0]
                quantization = quantization_metrics(
                    baseline_activations[injection_block],
                    stage_controls[spec["stage"]],
                    adapters[spec["stage"]].channel_vectors,
                    scale,
                    accumulate_in_fp32=precision == "fp32_accumulate",
                )
                key = f"{precision}_scale_{scale}"
                variants[key] = {
                    "precision": precision,
                    "scale": scale,
                    "minimum_localization_ratio": min(
                        item["localization_ratio"] for item in active_metrics
                    ),
                    "maximum_relative_global_delta": max(
                        item["relative_global_delta"] for item in active_metrics
                    ),
                    "final_output_mean_abs_delta": float(
                        (output.float() - baseline_output.float()).abs().mean()
                    ),
                    "all_finite": all(item["finite"] for item in metrics),
                    "injection_boundary_quantization": quantization,
                    "pending_error_mean_abs": (
                        float(adapters[spec["stage"]].pending_error.float().abs().mean())
                        if adapters[spec["stage"]].pending_error is not None
                        else 0.0
                    ),
                }
                if precision == "cross_step_carry":
                    carry_errors = {
                        name: (
                            adapter.pending_error.detach().clone()
                            if adapter.pending_error is not None
                            else None
                        )
                        for name, adapter in adapters.items()
                    }
                del output
        for handle in handles:
            handle.remove()
        results[str(step)] = {"spec": spec, "variants": variants}
        del latent, baseline_output

    parity = {}
    comparison_path = (
        "per_step_reset"
        if lifecycle_stage
        else "error_feedback"
        if error_feedback_stage or clean_scale_stage
        else "fp32_accumulate"
    )
    for step, payload in results.items():
        for scale in active_scales:
            baseline_path = "cross_step_carry" if lifecycle_stage else "bf16_direct"
            direct = payload["variants"][f"{baseline_path}_scale_{scale}"]
            candidate = payload["variants"][f"{comparison_path}_scale_{scale}"]
            parity[f"step_{step}_scale_{scale}"] = {
                "direct_locality": direct["minimum_localization_ratio"],
                "candidate_locality": candidate["minimum_localization_ratio"],
                "locality_delta": candidate["minimum_localization_ratio"]
                - direct["minimum_localization_ratio"],
                "direct_output_delta": direct["final_output_mean_abs_delta"],
                "candidate_output_delta": candidate["final_output_mean_abs_delta"],
            }
    all_finite = all(
        variant["all_finite"]
        for payload in results.values()
        for variant in payload["variants"].values()
    )
    error_feedback_decision = None
    if error_feedback_stage or clean_scale_stage:
        monotonic_global_response = all(
            all(
                payload["variants"][f"error_feedback_scale_{right}"][
                    "maximum_relative_global_delta"
                ]
                >= payload["variants"][f"error_feedback_scale_{left}"][
                    "maximum_relative_global_delta"
                ]
                for left, right in zip(SCALES, SCALES[1:])
            )
            for payload in results.values()
        )
        eligible_scales = [
            scale
            for scale in SCALES
            if all(
                payload["variants"][f"error_feedback_scale_{scale}"]["minimum_localization_ratio"]
                >= payload["variants"][f"bf16_direct_scale_{scale}"]["minimum_localization_ratio"]
                for payload in results.values()
            )
        ]
        error_feedback_decision = {
            "monotonic_global_response": monotonic_global_response,
            "eligible_scales_with_non_degrading_locality_at_all_probes": eligible_scales,
            "selected_scale": max(eligible_scales) if eligible_scales else None,
            "trajectory_authorized": bool(
                all_finite and monotonic_global_response and eligible_scales
            ),
        }
    lifecycle_decision = None
    if lifecycle_stage:
        r9 = json.loads(R9_RESULT.read_text(encoding="utf-8"))
        reproduction_deltas = []
        carry_deltas = []
        for step, payload in results.items():
            reset = payload["variants"]["per_step_reset_scale_0.0025"]
            carry = payload["variants"]["cross_step_carry_scale_0.0025"]
            reference = r9["results"][step]["variants"]["error_feedback_scale_0.0025"]
            reproduction_deltas.extend(
                [
                    abs(
                        reset["minimum_localization_ratio"]
                        - reference["minimum_localization_ratio"]
                    ),
                    abs(
                        reset["final_output_mean_abs_delta"]
                        - reference["final_output_mean_abs_delta"]
                    ),
                ]
            )
            carry_deltas.append(
                abs(reset["final_output_mean_abs_delta"] - carry["final_output_mean_abs_delta"])
            )
        exact_r9_reproduction = max(reproduction_deltas) == 0.0
        cross_step_state_is_causal = max(carry_deltas) > 0.0
        lifecycle_decision = {
            "exact_r9_reproduction": exact_r9_reproduction,
            "maximum_r9_metric_delta": max(reproduction_deltas),
            "cross_step_state_is_causal": cross_step_state_is_causal,
            "maximum_reset_vs_carry_output_delta": max(carry_deltas),
            "r9_scale_selection_invalidated": not exact_r9_reproduction,
            "trajectory_authorized": exact_r9_reproduction and cross_step_state_is_causal,
        }
    registration.unregister()
    result = {
        "schema_version": "1.0",
        "phase": (
            "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R1-R1"
            if clean_scale_stage
            else "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R1"
            if lifecycle_stage
            else "4L-R9-R7-R3-R21-R7-R4-R5-R3-R9"
            if error_feedback_stage
            else "4L-R9-R7-R3-R21-R7-R4-R5-R3-R8"
        ),
        "status": (
            "PASS_CLEAN_SCALE_ERROR_FEEDBACK_REVALIDATION"
            if clean_scale_stage and all_finite
            else "PASS_STEP_BOUNDED_ERROR_FEEDBACK_ISOLATION"
            if lifecycle_stage and all_finite
            else "PASS_ERROR_FEEDBACK_CAUSAL_ISOLATION"
            if error_feedback_stage and all_finite
            else "PASS_NUMERICAL_PRECISION_CAUSAL_ISOLATION"
            if all_finite
            else "FAIL"
        ),
        "probe_steps": list(PROBES),
        "scales": active_scales,
        "results": results,
        "causal_comparison": parity,
        "all_finite": all_finite,
        "error_feedback_decision": error_feedback_decision,
        "lifecycle_decision": lifecycle_decision,
        "phase4l_closure": {
            "status": (
                (
                    "OPEN_PENDING_STEP_BOUNDED_TRAJECTORY"
                    if error_feedback_decision and error_feedback_decision["trajectory_authorized"]
                    else "OPEN_PENDING_RESIDUAL_PROFILE_REDESIGN"
                )
                if clean_scale_stage
                else (
                    "OPEN_PENDING_STEP_BOUNDED_TRAJECTORY"
                    if lifecycle_decision and lifecycle_decision["trajectory_authorized"]
                    else "OPEN_PENDING_CLEAN_SCALE_REVALIDATION"
                )
                if lifecycle_stage
                else "OPEN_PENDING_ERROR_FEEDBACK_TRAJECTORY"
                if error_feedback_stage
                else "OPEN_PENDING_PRECISION_PATH_DECISION"
            ),
            "all_requirements_satisfied": False,
        },
        "runtime": {
            "seconds": round(time.perf_counter() - started, 3),
            "gpu_before_mib": gpu_before,
            "gpu_after_mib": gpu_used_mib(),
        },
        "guards": {
            "transformer_forward_count": len(PROBES)
            * (1 + len(precision_paths) * len(active_scales)),
            "scheduler_step_count": 0,
            "trajectory_count": 0,
            "vae_calls": {"forward": 0, "decode": 0},
            "images_created": 0,
            "decode_authorized": False,
            "new_generation_authorized": False,
            "production_profile_changed": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
        },
    }
    output_root.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    gc.collect()
    torch.cuda.empty_cache()
    if not all_finite:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
