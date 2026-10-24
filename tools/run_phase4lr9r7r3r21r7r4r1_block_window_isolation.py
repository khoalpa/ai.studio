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
    ExplicitControlRegistration,
    ExplicitSpatialControlResidual,
)
from ai_story.image_gate_profiles import PHOTOREALISTIC_INTERACTION_PROMPT
from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R4_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4-full-transformer-control-ab-v1/"
    "phase4lr9r7r3r21r7r4-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r1-block-window-isolation-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r1-result.json"
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
BO_REFERENCE = BASELINE_ROOT / (
    "phase4l-climax-canary-v1/youth-torn-paper-boat/work/characters/bo.png"
)
EXPECTED_R4_SHA256 = (
    "1d53672609763748712a449a27dc8578d50310e15c38879f52f46a0cc3e8b0a0"
)
SEED = 420917
STEP_INDEX = 12
CONTROL_SCALE = 0.01
WINDOWS = {
    "early": list(range(0, 8)),
    "middle": list(range(12, 20)),
    "late": list(range(28, 38)),
}
MAX_RELATIVE_DELTA = 0.01
MIN_TERMINAL_LOCALIZATION = 1.0
MIN_ONSET_LOCALIZATION = 100.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists():
        raise RuntimeError("R21-R7-R4-R1 already exists; refusing to overwrite")
    r4 = json.loads(R4_RESULT.read_text(encoding="utf-8"))
    r4_digest = sha256(R4_RESULT)
    if r4_digest != EXPECTED_R4_SHA256 or r4.get("status") != "FAIL":
        raise RuntimeError("R4 all-block negative fixture changed or no longer fails")
    if r4["summary"]["max_amplification_vs_block0"] <= r4["summary"][
        "amplification_limit"
    ]:
        raise RuntimeError("R4 no longer demonstrates all-block amplification")
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
    vectors = torch.randn((3, HIDDEN_SIZE), generator=generator)
    control = ExplicitSpatialControlResidual(vectors).to(torch.bfloat16)
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
        crop = source.convert("RGB").crop(IDENTITY_CROP)
    with torch.inference_mode():
        identity_embedding = pipe.encode_image(crop, pipe._execution_device)

    latent = torch.randn(
        (1, 16, 64, 64), generator=generator, dtype=torch.bfloat16
    ).to(pipe._execution_device)
    timestep = pipe.scheduler.timesteps[STEP_INDEX].reshape(1).to(
        pipe._execution_device
    )
    kwargs = {
        "ip_adapter_image_embeds": identity_embedding,
        "regional_attention_mask": torch.zeros(
            (1, GRID[0] * GRID[1], 1), device=pipe._execution_device
        ),
    }
    set_identity_scale(pipe, 0.0)

    baseline_activations: dict[int, torch.Tensor] = {}
    current_metrics: list[dict[str, Any]] = []
    mode = {"value": "baseline"}

    def capture(index: int):
        def hook(_module, _inputs, output):
            hidden = output[1].detach().cpu()
            if mode["value"] == "baseline":
                baseline_activations[index] = hidden
            else:
                current_metrics.append(
                    {
                        "block": index,
                        **block_metrics(
                            hidden, baseline_activations[index], union_mask
                        ),
                    }
                )
            return None

        return hook

    handles = [
        block.register_forward_hook(capture(index))
        for index, block in enumerate(pipe.transformer.transformer_blocks)
    ]
    with torch.inference_mode():
        registration.configure(token_controls, [0.0] * 38)
        baseline_output = pipe.transformer(
            hidden_states=latent,
            timestep=timestep,
            encoder_hidden_states=prompt_embeds,
            pooled_projections=pooled_embeds,
            joint_attention_kwargs=dict(kwargs),
            return_dict=False,
        )[0].detach().cpu()

    profiles: dict[str, Any] = {}
    for name, active_blocks in WINDOWS.items():
        current_metrics.clear()
        mode["value"] = name
        scales = [CONTROL_SCALE if index in active_blocks else 0.0 for index in range(38)]
        registration.configure(token_controls, scales)
        with torch.inference_mode():
            output = pipe.transformer(
                hidden_states=latent,
                timestep=timestep,
                encoder_hidden_states=prompt_embeds,
                pooled_projections=pooled_embeds,
                joint_attention_kwargs=dict(kwargs),
                return_dict=False,
            )[0].detach().cpu()
        metrics = list(current_metrics)
        onset = active_blocks[0]
        pre_onset_clean = all(
            item["global_mean_abs_delta"] == 0.0 for item in metrics[:onset]
        )
        max_relative = max(item["relative_global_delta"] for item in metrics)
        onset_localization = metrics[onset]["localization_ratio"]
        terminal_localization = metrics[-1]["localization_ratio"]
        final_delta = float((output.float() - baseline_output.float()).abs().mean().item())
        all_finite = all(item["finite"] for item in metrics)
        eligible = (
            pre_onset_clean
            and onset_localization >= MIN_ONSET_LOCALIZATION
            and terminal_localization > MIN_TERMINAL_LOCALIZATION
            and max_relative < MAX_RELATIVE_DELTA
            and final_delta > 0.0
            and all_finite
        )
        profiles[name] = {
            "active_blocks": active_blocks,
            "active_block_count": len(active_blocks),
            "pre_onset_clean": pre_onset_clean,
            "onset_localization_ratio": onset_localization,
            "terminal_localization_ratio": terminal_localization,
            "max_relative_global_delta": max_relative,
            "final_output_mean_abs_delta": final_delta,
            "all_blocks_finite": all_finite,
            "eligible": eligible,
            "block_metrics": metrics,
        }
        del output
        gc.collect()

    for handle in handles:
        handle.remove()
    identity_ids_after = {
        name: id(processor)
        for name, processor in pipe.transformer.attn_processors.items()
        if isinstance(processor, RegionalSD3IPAdapterProcessor)
    }
    identity_preserved = identity_ids_after == identity_processor_ids
    eligible_names = [name for name, profile in profiles.items() if profile["eligible"]]
    selected = (
        max(
            eligible_names,
            key=lambda name: (
                profiles[name]["terminal_localization_ratio"],
                -profiles[name]["active_block_count"],
            ),
        )
        if eligible_names
        else None
    )
    passed = selected is not None and identity_preserved
    registration.unregister()
    del pipe, control, registration, prompt_embeds, pooled_embeds
    del identity_embedding, latent, baseline_output
    gc.collect()
    torch.cuda.empty_cache()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R1",
        "status": "PASS_BLOCK_WINDOW_ISOLATION" if passed else "FAIL",
        "negative_fixture": {
            "path": str(R4_RESULT.resolve()),
            "sha256": r4_digest,
            "status": r4["status"],
            "all_block_profile_forbidden": True,
        },
        "seed": SEED,
        "step_index": STEP_INDEX,
        "timestep": float(timestep.item()),
        "control_scale": CONTROL_SCALE,
        "windows": WINDOWS,
        "thresholds": {
            "maximum_relative_global_delta": MAX_RELATIVE_DELTA,
            "minimum_onset_localization": MIN_ONSET_LOCALIZATION,
            "minimum_terminal_localization_exclusive": MIN_TERMINAL_LOCALIZATION,
        },
        "profiles": profiles,
        "eligible_profiles": eligible_names,
        "selected_profile": selected,
        "identity_processors_preserved": identity_preserved,
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
