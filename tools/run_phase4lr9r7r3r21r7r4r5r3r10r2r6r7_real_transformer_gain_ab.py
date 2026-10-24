from __future__ import annotations

import gc
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import torch
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
R6_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r6-bf16-gain-probe-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r6-result.json"
)
BASELINE_CACHE = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r7-scale-terminal-isolation-v1/baseline-cache.pt"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r7-real-transformer-gain-ab-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r6r7-result.json"
MOTHER_CHANNELS = {"me_face", "me_hand", "me_contact"}
GAINS = {"a_gain_1": 1.0, "b_gain_1_5": 1.5}
ACTIVE_BLOCKS = [0, 1, 2, 3, 4]
SCALE = 0.00125
STEP_INDEX = 2


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def region_delta(
    current: torch.Tensor, baseline: torch.Tensor, mask: torch.Tensor
) -> dict[str, float]:
    delta = (current.float() - baseline.float()).abs().mean(dim=-1).reshape(-1)
    flat_mask = mask.reshape(-1)
    inside = delta[flat_mask]
    outside = delta[~flat_mask]
    inside_mean = float(inside.mean())
    outside_mean = float(outside.mean())
    return {
        "inside_mean_abs_delta": inside_mean,
        "outside_mean_abs_delta": outside_mean,
        "localization_ratio": inside_mean / max(outside_mean, 1e-12),
    }


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists():
        raise RuntimeError("R10-R2-R6-R7 checkpoint already exists; refusing overwrite")
    prior = json.loads(R6_RESULT.read_text(encoding="utf-8"))
    if prior["status"] != "PASS_BF16_CHANNEL_GAIN_OBSERVABILITY_FORENSIC":
        raise RuntimeError("R6 BF16 gain forensic is not locked PASS")
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

    raw_outputs: dict[str, dict[int, torch.Tensor]] = {}
    post_outputs: dict[str, dict[int, torch.Tensor]] = {}
    mode = {"name": ""}

    def capture_raw(index: int):
        def hook(_module, _inputs, output):
            raw_outputs[mode["name"]][index] = output[1].detach().cpu().clone()
            return None

        return hook

    raw_handles = [
        block.register_forward_hook(capture_raw(index))
        for index, block in enumerate(pipe.transformer.transformer_blocks)
    ]
    registration = StagedExplicitControlRegistration(pipe.transformer, {"geometry": adapter})

    def capture_post(index: int):
        def hook(_module, _inputs, output):
            post_outputs[mode["name"]][index] = output[1].detach().cpu().clone()
            return None

        return hook

    post_handles = [
        block.register_forward_hook(capture_post(index))
        for index, block in enumerate(pipe.transformer.transformer_blocks)
    ]

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
    baseline_cache = torch.load(BASELINE_CACHE, map_location="cpu", weights_only=False)
    fixed_latent = baseline_cache["branch"]["latents"][STEP_INDEX - 1]
    timestep = pipe.scheduler.timesteps[STEP_INDEX].reshape(1).to(pipe._execution_device)
    attention_kwargs = {
        "ip_adapter_image_embeds": identity_embedding,
        "regional_attention_mask": torch.zeros((1, GRID[0] * GRID[1], 1)).to(
            pipe._execution_device
        ),
    }
    final_outputs: dict[str, torch.Tensor] = {}
    weighted_controls: dict[str, torch.Tensor] = {}
    with torch.inference_mode():
        for name, gain in GAINS.items():
            weighted = base_controls.float().clone()
            for index, channel in enumerate(CHANNELS):
                if channel in MOTHER_CHANNELS:
                    weighted[..., index] *= gain
            weighted_controls[name] = weighted
            raw_outputs[name] = {}
            post_outputs[name] = {}
            mode["name"] = name
            adapter.reset_error_feedback()
            registration.configure_stage(
                "geometry",
                weighted,
                [SCALE if index in ACTIVE_BLOCKS else 0.0 for index in range(38)],
            )
            final_outputs[name] = pipe.transformer(
                hidden_states=fixed_latent.to(pipe._execution_device),
                timestep=timestep,
                encoder_hidden_states=prompt_embeds,
                pooled_projections=pooled_embeds,
                joint_attention_kwargs=dict(attention_kwargs),
                return_dict=False,
            )[0].detach().cpu()

    block_records = []
    for index in ACTIVE_BLOCKS:
        a_raw = raw_outputs["a_gain_1"][index]
        b_raw = raw_outputs["b_gain_1_5"][index]
        a_post = post_outputs["a_gain_1"][index]
        b_post = post_outputs["b_gain_1_5"][index]
        a_write = a_post.float() - a_raw.float()
        b_write = b_post.float() - b_raw.float()
        record: dict[str, Any] = {
            "block": index,
            "gain_1_write_norm": float(a_write.norm()),
            "gain_1_5_write_norm": float(b_write.norm()),
            "write_norm_ratio": float(b_write.norm()) / max(float(a_write.norm()), 1e-12),
            "pre_residual_ab_mean_abs_delta": float(
                (b_raw.float() - a_raw.float()).abs().mean()
            ),
            "post_residual_ab_mean_abs_delta": float(
                (b_post.float() - a_post.float()).abs().mean()
            ),
            "mother_regions": {
                region: region_delta(b_post, a_post, masks[region])
                for region in sorted(MOTHER_CHANNELS)
            },
        }
        block_records.append(record)
    final_ab_delta = float(
        (final_outputs["b_gain_1_5"].float() - final_outputs["a_gain_1"].float())
        .abs()
        .mean()
    )
    first_observable_block = next(
        (
            record["block"]
            for record in block_records
            if record["post_residual_ab_mean_abs_delta"] > 0.0
        ),
        None,
    )
    write_observable = any(record["write_norm_ratio"] > 1.0 for record in block_records)
    propagated_to_final = final_ab_delta > 0.0
    passed = (
        write_observable
        and first_observable_block is not None
        and all(
            torch.isfinite(torch.tensor(list(record.values())[:5])).all().item()
            for record in block_records
        )
    )

    for handle in post_handles + raw_handles:
        handle.remove()
    registration.unregister()
    del pipe, registration, adapter, prompt_embeds, pooled_embeds, identity_embedding
    gc.collect()
    torch.cuda.empty_cache()
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R6-R7",
        "status": "PASS_REAL_TRANSFORMER_GAIN_OBSERVABILITY_AB" if passed else "FAIL",
        "configuration": {
            "step_index": STEP_INDEX,
            "timestep": float(timestep.item()),
            "active_blocks": ACTIVE_BLOCKS,
            "scale": SCALE,
            "gains": GAINS,
            "seed": SEED,
        },
        "block_records": block_records,
        "summary": {
            "write_observable": write_observable,
            "first_observable_block": first_observable_block,
            "final_transformer_output_ab_mean_abs_delta": final_ab_delta,
            "gain_difference_propagated_to_final_output": propagated_to_final,
        },
        "next_decode_authorized": False,
        "phase4l_closure": {
            "status": "OPEN_PENDING_MOTHER_GAIN_INTEGRATION_DECISION",
            "all_requirements_satisfied": False,
        },
        "runtime": {
            "seconds": round(time.perf_counter() - started, 3),
            "gpu_before_mib": gpu_before,
            "gpu_after_mib": gpu_used_mib(),
        },
        "guards": {
            "full_transformer_forward_count": 2,
            "scheduler_step_called": False,
            "trajectory_run": False,
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
