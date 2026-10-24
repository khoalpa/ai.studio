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

from ai_story.explicit_spatial_control import (
    ExplicitControlRegistration,
    ExplicitSpatialControlResidual,
    raster_controls_to_tokens,
)
from ai_story.image_gate_profiles import PHOTOREALISTIC_INTERACTION_PROMPT
from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R3_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r3-full-control-registration-v1/"
    "phase4lr9r7r3r21r7r3-result.json"
)
CONTROL_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r1-negative-pose-contract-v1"
)
CONTROL_PATHS = [
    CONTROL_ROOT / "composition-control.png",
    CONTROL_ROOT / "pose-control.png",
    CONTROL_ROOT / "prop-silhouette-control.png",
]
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4-full-transformer-control-ab-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4-result.json"
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
BO_REFERENCE = BASELINE_ROOT / (
    "phase4l-climax-canary-v1/youth-torn-paper-boat/work/characters/bo.png"
)
IDENTITY_CROP = (384, 0, 1152, 768)
SEED = 420917
STEPS = 24
STEP_INDEX = 12
GRID = (32, 32)
HIDDEN_SIZE = 2432
CONTROL_SCALE = 0.01
MAX_BLOCK_AMPLIFICATION = 100.0
MAX_RELATIVE_BLOCK_DELTA = 0.05


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def load_control_tokens() -> torch.Tensor:
    channels = []
    for path in CONTROL_PATHS:
        with Image.open(path) as image:
            grayscale = image.convert("L")
            values = torch.frombuffer(
                bytearray(grayscale.tobytes()), dtype=torch.uint8
            )
            channels.append(
                values.reshape(grayscale.height, grayscale.width).float() / 255.0
            )
    rasters = torch.stack(channels).unsqueeze(0)
    return raster_controls_to_tokens(rasters, GRID, threshold=0.25)


def block_metrics(
    current: torch.Tensor,
    baseline: torch.Tensor,
    union_mask: torch.Tensor,
) -> dict[str, float | bool]:
    current_float = current.float()
    baseline_float = baseline.float()
    delta = (current_float - baseline_float).abs().mean(dim=-1).reshape(-1)
    inside = delta[union_mask]
    outside = delta[~union_mask]
    global_mean = float(delta.mean().item())
    baseline_mean = float(baseline_float.abs().mean().item())
    inside_mean = float(inside.mean().item())
    outside_mean = float(outside.mean().item())
    return {
        "inside_mean_abs_delta": inside_mean,
        "outside_mean_abs_delta": outside_mean,
        "global_mean_abs_delta": global_mean,
        "relative_global_delta": global_mean / max(baseline_mean, 1e-12),
        "localization_ratio": inside_mean / max(outside_mean, 1e-12),
        "finite": bool(torch.isfinite(delta).all().item()),
    }


def set_identity_scale(pipe, value: float) -> None:
    for processor in pipe.transformer.attn_processors.values():
        if isinstance(processor, RegionalSD3IPAdapterProcessor):
            processor.scale = value


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists():
        raise RuntimeError("R21-R7-R4 already exists; refusing to overwrite checkpoint")
    prior = json.loads(R3_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_FULL_38_BLOCK_EXPLICIT_CONTROL_REGISTRATION":
        raise RuntimeError("R21-R7-R3 full registration must pass")
    gpu_before = gpu_used_mib()
    if gpu_before > 512:
        raise RuntimeError(f"GPU is not exclusive: {gpu_before} MiB already used")

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
    identity_processor_ids = {
        name: id(processor)
        for name, processor in pipe.transformer.attn_processors.items()
        if isinstance(processor, RegionalSD3IPAdapterProcessor)
    }

    generator = torch.Generator(device="cpu").manual_seed(SEED)
    channel_vectors = torch.randn((3, HIDDEN_SIZE), generator=generator)
    control = ExplicitSpatialControlResidual(channel_vectors).to(torch.bfloat16)
    registration = ExplicitControlRegistration(pipe.transformer, control)
    token_controls = load_control_tokens()
    union_mask = token_controls.any(dim=-1).reshape(-1)
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

    fixed_latent = torch.randn(
        (1, 16, 64, 64), generator=generator, dtype=torch.bfloat16
    )
    timestep = pipe.scheduler.timesteps[STEP_INDEX].reshape(1).to(
        pipe._execution_device
    )
    regional_mask = torch.zeros((1, GRID[0] * GRID[1], 1))
    attention_kwargs = {
        "ip_adapter_image_embeds": identity_embedding,
        "regional_attention_mask": regional_mask.to(pipe._execution_device),
    }

    baseline_activations: dict[int, torch.Tensor] = {}
    active_metrics: list[dict[str, Any]] = []
    mode = {"value": "baseline"}

    def capture(index: int):
        def hook(_module, _inputs, output):
            hidden = output[1].detach().cpu()
            if mode["value"] == "baseline":
                baseline_activations[index] = hidden
            else:
                active_metrics.append(
                    {
                        "block": index,
                        **block_metrics(
                            hidden,
                            baseline_activations[index],
                            union_mask,
                        ),
                    }
                )
            return None

        return hook

    capture_handles = [
        block.register_forward_hook(capture(index))
        for index, block in enumerate(pipe.transformer.transformer_blocks)
    ]
    latent = fixed_latent.to(pipe._execution_device)
    set_identity_scale(pipe, 0.0)
    with torch.inference_mode():
        registration.configure(token_controls, [0.0] * 38)
        baseline_output = pipe.transformer(
            hidden_states=latent,
            timestep=timestep,
            encoder_hidden_states=prompt_embeds,
            pooled_projections=pooled_embeds,
            joint_attention_kwargs=dict(attention_kwargs),
            return_dict=False,
        )[0].detach().cpu()
        mode["value"] = "active"
        registration.configure(token_controls, [CONTROL_SCALE] * 38)
        active_output = pipe.transformer(
            hidden_states=latent,
            timestep=timestep,
            encoder_hidden_states=prompt_embeds,
            pooled_projections=pooled_embeds,
            joint_attention_kwargs=dict(attention_kwargs),
            return_dict=False,
        )[0].detach().cpu()

    for handle in capture_handles:
        handle.remove()
    if len(active_metrics) != 38:
        raise RuntimeError(f"Expected 38 block metrics, got {len(active_metrics)}")
    block0_global = active_metrics[0]["global_mean_abs_delta"]
    for item in active_metrics:
        item["amplification_vs_block0"] = item["global_mean_abs_delta"] / max(
            block0_global, 1e-12
        )
    final_delta = float(
        (active_output.float() - baseline_output.float()).abs().mean().item()
    )
    max_amplification = max(item["amplification_vs_block0"] for item in active_metrics)
    max_relative_delta = max(item["relative_global_delta"] for item in active_metrics)
    block0_localized = active_metrics[0]["localization_ratio"] > 100.0
    all_finite = all(item["finite"] for item in active_metrics)
    identity_ids_after = {
        name: id(processor)
        for name, processor in pipe.transformer.attn_processors.items()
        if isinstance(processor, RegionalSD3IPAdapterProcessor)
    }
    identity_processors_preserved = identity_ids_after == identity_processor_ids
    passed = (
        block0_global > 0.0
        and block0_localized
        and all_finite
        and final_delta > 0.0
        and max_amplification < MAX_BLOCK_AMPLIFICATION
        and max_relative_delta < MAX_RELATIVE_BLOCK_DELTA
        and identity_processors_preserved
    )

    registration.unregister()
    del pipe, control, registration, prompt_embeds, pooled_embeds
    del identity_embedding, latent, baseline_output, active_output
    gc.collect()
    torch.cuda.empty_cache()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4",
        "status": "PASS_FULL_TRANSFORMER_SINGLE_STEP_EXPLICIT_CONTROL_AB"
        if passed
        else "FAIL",
        "seed": SEED,
        "fixed_latent_shape": [1, 16, 64, 64],
        "query_grid": list(GRID),
        "step_index": STEP_INDEX,
        "timestep": float(timestep.item()),
        "control_scale": CONTROL_SCALE,
        "union_active_token_count": int(union_mask.sum().item()),
        "identity_scale": 0.0,
        "identity_processors_preserved": identity_processors_preserved,
        "block_metrics": active_metrics,
        "summary": {
            "block0_localized": block0_localized,
            "max_amplification_vs_block0": max_amplification,
            "amplification_limit": MAX_BLOCK_AMPLIFICATION,
            "max_relative_global_delta": max_relative_delta,
            "relative_delta_limit": MAX_RELATIVE_BLOCK_DELTA,
            "final_output_mean_abs_delta": final_delta,
            "all_blocks_finite": all_finite,
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
            "image_generation_performed": False,
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
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
