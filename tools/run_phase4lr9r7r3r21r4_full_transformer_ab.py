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

from ai_story.image_gate_profiles import PHOTOREALISTIC_INTERACTION_PROMPT
from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R3_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r3-full-regional-registration-smoke-v1/"
    "phase4lr9r7r3r21r3-result.json"
)
LAYOUT_PATH = BASELINE_ROOT / (
    "phase4lr9r7r3r21r1-negative-spatial-conditioning-lock-v1/"
    "regional-spatial-conditioning.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r21r4-full-transformer-ab-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r4-result.json"
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
SOURCE_WORK = BASELINE_ROOT / "phase4l-climax-canary-v1/youth-torn-paper-boat/work"
BO_REFERENCE = SOURCE_WORK / "characters/bo.png"
ME_REFERENCE = SOURCE_WORK / "characters/me.png"
IDENTITY_CROP = (384, 0, 1152, 768)
SEED = 420917
STEPS = 24
SCALE = 0.25
GRID_SIDE = 32


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def token_mask(include: list[float], exclude: list[float]) -> torch.Tensor:
    rows = (torch.arange(GRID_SIDE, dtype=torch.float32) + 0.5) / GRID_SIDE
    columns = (torch.arange(GRID_SIDE, dtype=torch.float32) + 0.5) / GRID_SIDE
    y, x = torch.meshgrid(rows, columns, indexing="ij")
    selected = (
        (x >= include[0])
        & (y >= include[1])
        & (x < include[2])
        & (y < include[3])
    )
    excluded = (
        (x >= exclude[0])
        & (y >= exclude[1])
        & (x < exclude[2])
        & (y < exclude[3])
    )
    return (selected & ~excluded).reshape(1, -1, 1).to(torch.float32)


def metrics(
    current: torch.Tensor,
    baseline: torch.Tensor,
    region_mask: torch.Tensor,
    interaction_mask: torch.Tensor,
) -> dict[str, float]:
    delta = (current.float() - baseline.float()).abs().mean(dim=-1, keepdim=True)
    region = region_mask.bool()
    outside = ~region
    interaction = interaction_mask.bool()
    inside_mean = float(delta[region].mean().item())
    outside_mean = float(delta[outside].mean().item())
    interaction_mean = float(delta[interaction].mean().item())
    return {
        "inside_mean_abs_delta": inside_mean,
        "outside_mean_abs_delta": outside_mean,
        "interaction_mean_abs_delta": interaction_mean,
        "localization_ratio": inside_mean / max(outside_mean, 1e-12),
        "interaction_to_inside_ratio": interaction_mean / max(inside_mean, 1e-12),
    }


def set_scale(pipe, value: float) -> None:
    for processor in pipe.transformer.attn_processors.values():
        if isinstance(processor, RegionalSD3IPAdapterProcessor):
            processor.scale = value


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    prior = json.loads(R3_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_FULL_38_BLOCK_REGISTRATION":
        raise RuntimeError("R21-R3 must pass before the full-transformer A/B")
    if RESULT_PATH.exists():
        raise RuntimeError("R21-R4 result already exists; refusing to rerun")
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
            processor.scale = SCALE
            replacements[name] = RegionalSD3IPAdapterProcessor(processor)
    pipe.transformer.set_attn_processor(replacements)
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
        bo_embedding = pipe.encode_image(bo_crop, pipe._execution_device)
        mother_embedding = pipe.encode_image(mother_crop, pipe._execution_device)

    layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    regions = layout["regions"]
    interaction_box = regions["interaction"]["box"]
    bo_mask = token_mask(regions["bo_identity"]["box"], interaction_box)
    mother_mask = token_mask(regions["mother_identity"]["box"], interaction_box)
    interaction_mask = token_mask(interaction_box, [0.0, 0.0, 0.0, 0.0])
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    fixed_latent = torch.randn((1, 16, 64, 64), generator=generator, dtype=torch.bfloat16)

    branch_results: dict[str, Any] = {}
    for identity, step_index, embedding, region_mask in (
        ("BO", 10, bo_embedding, bo_mask),
        ("ME", 14, mother_embedding, mother_mask),
    ):
        timestep = pipe.scheduler.timesteps[step_index].reshape(1).to(
            pipe._execution_device
        )
        baseline_activations: dict[int, torch.Tensor] = {}
        regional_metrics: list[dict[str, Any]] = []
        mode = {"value": "baseline"}

        def hook(index: int):
            def capture(_module, _inputs, output):
                hidden = output[1].detach().cpu()
                if mode["value"] == "baseline":
                    baseline_activations[index] = hidden
                else:
                    item = metrics(
                        hidden,
                        baseline_activations[index],
                        region_mask,
                        interaction_mask,
                    )
                    regional_metrics.append({"block": index, **item})
                return None

            return capture

        handles = [
            block.register_forward_hook(hook(index))
            for index, block in enumerate(pipe.transformer.transformer_blocks)
        ]
        latent = fixed_latent.to(pipe._execution_device)
        kwargs = {
            "ip_adapter_image_embeds": embedding,
            "regional_attention_mask": region_mask.to(pipe._execution_device),
        }
        with torch.inference_mode():
            set_scale(pipe, 0.0)
            baseline_output = pipe.transformer(
                hidden_states=latent,
                timestep=timestep,
                encoder_hidden_states=prompt_embeds,
                pooled_projections=pooled_embeds,
                joint_attention_kwargs=dict(kwargs),
                return_dict=False,
            )[0].detach().cpu()
            mode["value"] = "regional"
            set_scale(pipe, SCALE)
            regional_output = pipe.transformer(
                hidden_states=latent,
                timestep=timestep,
                encoder_hidden_states=prompt_embeds,
                pooled_projections=pooled_embeds,
                joint_attention_kwargs=dict(kwargs),
                return_dict=False,
            )[0].detach().cpu()
        for handle in handles:
            handle.remove()
        if len(regional_metrics) != 38:
            raise RuntimeError(f"{identity} did not capture all 38 blocks")
        final_delta = float(
            (regional_output.float() - baseline_output.float()).abs().mean().item()
        )
        branch_results[identity] = {
            "step_index": step_index,
            "timestep": float(timestep.item()),
            "block_metrics": regional_metrics,
            "final_output_mean_abs_delta": final_delta,
            "inside_dominant_at_block_0": regional_metrics[0]["localization_ratio"] > 1.0,
            "interaction_below_inside_at_block_0": (
                regional_metrics[0]["interaction_to_inside_ratio"] < 1.0
            ),
            "all_blocks_finite": all(
                all(
                    torch.isfinite(torch.tensor(value)).item()
                    for key, value in item.items()
                    if key != "block"
                )
                for item in regional_metrics
            ),
        }
        baseline_activations.clear()
        del baseline_output, regional_output, latent
        gc.collect()
        torch.cuda.empty_cache()

    passed = all(
        result["inside_dominant_at_block_0"]
        and result["interaction_below_inside_at_block_0"]
        and result["all_blocks_finite"]
        and result["final_output_mean_abs_delta"] > 0
        for result in branch_results.values()
    )
    del pipe, prompt_embeds, pooled_embeds, bo_embedding, mother_embedding
    gc.collect()
    torch.cuda.empty_cache()
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R4",
        "status": "PASS_FULL_TRANSFORMER_SINGLE_STEP_AB" if passed else "FAIL",
        "seed": SEED,
        "prompt": PHOTOREALISTIC_INTERACTION_PROMPT,
        "fixed_latent_shape": [1, 16, 64, 64],
        "query_grid": [32, 32],
        "scale": SCALE,
        "branches": branch_results,
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
            "image_generation_performed": False,
            "next_full_scene_attempt_authorized": False,
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
