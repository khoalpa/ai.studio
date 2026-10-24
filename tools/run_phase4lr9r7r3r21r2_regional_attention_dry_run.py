from __future__ import annotations

import gc
import hashlib
import json
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as functional
from safetensors import safe_open

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R21_R1_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r1-negative-spatial-conditioning-lock-v1"
)
R21_R1_RESULT = R21_R1_ROOT / "phase4lr9r7r3r21r1-result.json"
LAYOUT_PATH = R21_R1_ROOT / "regional-spatial-conditioning.json"
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r21r2-regional-attention-dry-run-v1"
ADAPTER_WEIGHT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter/ip-adapter.bin")
TRANSFORMER_SHARD = Path(
    "D:/project/ai.studio/models/stable-diffusion-3.5-large/transformer/"
    "diffusion_pytorch_model-00001-of-00002.safetensors"
)
TRANSFORMER_CONFIG = Path(
    "D:/project/ai.studio/models/stable-diffusion-3.5-large/transformer/config.json"
)
EXPECTED_LAYOUT_SHA256 = (
    "d0f5d0f2cb1ebad81a7140e1289dcff0d9e60a8ef900d446453afb6c8c708350"
)
SEED = 420917
BLOCK_INDEX = 0
TOLERANCE = 1e-6


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def token_mask(
    grid: tuple[int, int], include: list[float], exclude: list[float]
) -> torch.Tensor:
    height, width = grid
    rows = (torch.arange(height, dtype=torch.float32) + 0.5) / height
    columns = (torch.arange(width, dtype=torch.float32) + 0.5) / width
    y, x = torch.meshgrid(rows, columns, indexing="ij")
    included = (
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
    return (included & ~excluded).reshape(1, -1, 1).to(torch.float32)


def regional_forward(
    processor,
    attn,
    hidden_states: torch.Tensor,
    context: torch.Tensor,
    ip_hidden_states: torch.Tensor,
    temb: torch.Tensor,
    mask: torch.Tensor,
    scale: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    residual = hidden_states
    batch_size = hidden_states.shape[0]
    raw_query = attn.to_q(hidden_states)
    raw_key = attn.to_k(hidden_states)
    raw_value = attn.to_v(hidden_states)
    inner_dim = raw_key.shape[-1]
    head_dim = inner_dim // attn.heads
    query = raw_query.view(batch_size, -1, attn.heads, head_dim).transpose(1, 2)
    key = raw_key.view(batch_size, -1, attn.heads, head_dim).transpose(1, 2)
    value = raw_value.view(batch_size, -1, attn.heads, head_dim).transpose(1, 2)
    if attn.norm_q is not None:
        query = attn.norm_q(query)
    if attn.norm_k is not None:
        key = attn.norm_k(key)

    context_query = attn.add_q_proj(context).view(
        batch_size, -1, attn.heads, head_dim
    ).transpose(1, 2)
    context_key = attn.add_k_proj(context).view(
        batch_size, -1, attn.heads, head_dim
    ).transpose(1, 2)
    context_value = attn.add_v_proj(context).view(
        batch_size, -1, attn.heads, head_dim
    ).transpose(1, 2)
    if attn.norm_added_q is not None:
        context_query = attn.norm_added_q(context_query)
    if attn.norm_added_k is not None:
        context_key = attn.norm_added_k(context_key)
    joint_query = torch.cat([query, context_query], dim=2)
    joint_key = torch.cat([key, context_key], dim=2)
    joint_value = torch.cat([value, context_value], dim=2)
    output = functional.scaled_dot_product_attention(
        joint_query, joint_key, joint_value, dropout_p=0.0, is_causal=False
    )
    output = output.transpose(1, 2).reshape(batch_size, -1, inner_dim)
    output, context_output = output[:, : residual.shape[1]], output[:, residual.shape[1] :]
    if not attn.context_pre_only:
        context_output = attn.to_add_out(context_output)

    normalized_ip = processor.norm_ip(ip_hidden_states, temb=temb)
    ip_key = processor.to_k_ip(normalized_ip).view(
        batch_size, -1, attn.heads, head_dim
    ).transpose(1, 2)
    ip_value = processor.to_v_ip(normalized_ip).view(
        batch_size, -1, attn.heads, head_dim
    ).transpose(1, 2)
    ip_query = processor.norm_q(
        raw_query.view(batch_size, -1, attn.heads, head_dim).transpose(1, 2)
    )
    image_key = processor.norm_k(
        raw_key.view(batch_size, -1, attn.heads, head_dim).transpose(1, 2)
    )
    ip_key = processor.norm_ip_k(ip_key)
    ip_output = functional.scaled_dot_product_attention(
        ip_query,
        torch.cat([image_key, ip_key], dim=2),
        torch.cat(
            [
                raw_value.view(batch_size, -1, attn.heads, head_dim).transpose(1, 2),
                ip_value,
            ],
            dim=2,
        ),
        dropout_p=0.0,
        is_causal=False,
    )
    ip_output = ip_output.transpose(1, 2).reshape(batch_size, -1, inner_dim)
    output = output + ip_output * mask.to(output) * scale
    output = attn.to_out[1](attn.to_out[0](output))
    return output, context_output


def load_block():
    from diffusers.models.attention_processor import (
        Attention,
        SD3IPAdapterJointAttnProcessor2_0,
    )

    state = torch.load(ADAPTER_WEIGHT, map_location="cpu", weights_only=True)
    processor = SD3IPAdapterJointAttnProcessor2_0(
        hidden_size=2432,
        ip_hidden_states_dim=2432,
        head_dim=64,
        timesteps_emb_dim=1280,
        scale=0.25,
    ).float().eval()
    block_state = {
        key.split(".", 1)[1]: value.float()
        for key, value in state["ip_adapter"].items()
        if key.startswith(f"{BLOCK_INDEX}.")
    }
    processor.load_state_dict(block_state, strict=True)
    attention = Attention(
        query_dim=2432,
        cross_attention_dim=None,
        added_kv_proj_dim=2432,
        dim_head=64,
        heads=38,
        out_dim=2432,
        context_pre_only=False,
        bias=True,
        processor=processor,
        qk_norm="rms_norm",
        eps=1e-6,
    ).float().eval()
    prefix = f"transformer_blocks.{BLOCK_INDEX}.attn."
    with safe_open(TRANSFORMER_SHARD, framework="pt", device="cpu") as handle:
        attention_state = {
            key[len(prefix) :]: handle.get_tensor(key).float()
            for key in handle.keys()
            if key.startswith(prefix)
        }
    attention.load_state_dict(attention_state, strict=False)
    del state, block_state, attention_state
    gc.collect()
    return processor, attention


def branch_metrics(
    active: torch.Tensor,
    baseline: torch.Tensor,
    mask: torch.Tensor,
    interaction_mask: torch.Tensor,
) -> dict[str, float | int | bool]:
    delta = (active - baseline).abs().mean(dim=-1, keepdim=True)
    inside = delta[mask.bool()]
    outside = delta[(1.0 - mask).bool()]
    interaction = delta[interaction_mask.bool()]
    outside_max = float(outside.max().item())
    interaction_max = float(interaction.max().item())
    inside_mean = float(inside.mean().item())
    return {
        "active_token_count": int(mask.sum().item()),
        "inside_mean_abs_delta": inside_mean,
        "outside_max_abs_delta": outside_max,
        "interaction_max_abs_delta": interaction_max,
        "inside_effect_nonzero": inside_mean > 1e-6,
        "outside_leakage_below_tolerance": outside_max <= TOLERANCE,
        "interaction_leakage_below_tolerance": interaction_max <= TOLERANCE,
    }


def main() -> None:
    prior = json.loads(R21_R1_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_NEGATIVE_LOCK_AND_SPATIAL_DESIGN":
        raise RuntimeError("R21-R1 spatial contract is not locked")
    layout_digest = sha256(LAYOUT_PATH)
    if layout_digest != EXPECTED_LAYOUT_SHA256:
        raise RuntimeError(f"Spatial contract changed: {layout_digest}")
    layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    config = json.loads(TRANSFORMER_CONFIG.read_text(encoding="utf-8"))
    latent_size = layout["canvas"]["width"] // 8
    grid_side = latent_size // int(config["patch_size"])
    grid = (grid_side, grid_side)
    regions = layout["regions"]
    interaction_box = regions["interaction"]["box"]
    bo_mask = token_mask(grid, regions["bo_identity"]["box"], interaction_box)
    mother_mask = token_mask(
        grid, regions["mother_identity"]["box"], interaction_box
    )
    interaction_mask = token_mask(grid, interaction_box, [0.0, 0.0, 0.0, 0.0])
    overlap = int((bo_mask.bool() & mother_mask.bool()).sum().item())

    processor, attention = load_block()
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    hidden = torch.randn((1, grid_side * grid_side, 2432), generator=generator)
    context = torch.randn((1, 3, 2432), generator=generator)
    ip_hidden = torch.randn((1, 64, 2432), generator=generator)
    temb = torch.randn((1, 1280), generator=generator)
    zero_mask = torch.zeros_like(bo_mask)
    full_mask = torch.ones_like(bo_mask)
    with torch.inference_mode():
        baseline, baseline_context = regional_forward(
            processor, attention, hidden, context, ip_hidden, temb, zero_mask, 0.25
        )
        full, full_context = regional_forward(
            processor, attention, hidden, context, ip_hidden, temb, full_mask, 0.25
        )
        native, native_context = processor(
            attention,
            hidden,
            encoder_hidden_states=context,
            ip_hidden_states=ip_hidden,
            temb=temb,
        )
        bo, bo_context = regional_forward(
            processor, attention, hidden, context, ip_hidden, temb, bo_mask, 0.25
        )
        mother, mother_context = regional_forward(
            processor,
            attention,
            hidden,
            context,
            ip_hidden,
            temb,
            mother_mask,
            0.25,
        )
    parity_error = float((full - native).abs().max().item())
    context_errors = {
        "baseline": float((baseline_context - native_context).abs().max().item()),
        "full": float((full_context - native_context).abs().max().item()),
        "bo": float((bo_context - native_context).abs().max().item()),
        "mother": float((mother_context - native_context).abs().max().item()),
    }
    bo_metrics = branch_metrics(bo, baseline, bo_mask, interaction_mask)
    mother_metrics = branch_metrics(mother, baseline, mother_mask, interaction_mask)
    passed = (
        parity_error <= TOLERANCE
        and overlap == 0
        and all(value <= TOLERANCE for value in context_errors.values())
        and all(
            bool(metrics[key])
            for metrics in (bo_metrics, mother_metrics)
            for key in (
                "inside_effect_nonzero",
                "outside_leakage_below_tolerance",
                "interaction_leakage_below_tolerance",
            )
        )
    )
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R2",
        "status": "PASS_REGIONAL_ATTENTION_DRY_RUN" if passed else "FAIL",
        "spatial_contract_sha256": layout_digest,
        "transformer_mapping": {
            "image_size": 512,
            "vae_scale_factor": 8,
            "latent_size": [latent_size, latent_size],
            "patch_size": config["patch_size"],
            "query_grid": list(grid),
            "query_token_count": grid_side * grid_side,
            "block_index": BLOCK_INDEX,
            "block_count": config["num_layers"],
        },
        "regional_masks": {
            "sampling": "TOKEN_CENTER_HALF_OPEN_BOX",
            "bo_active_tokens": int(bo_mask.sum().item()),
            "mother_active_tokens": int(mother_mask.sum().item()),
            "interaction_tokens": int(interaction_mask.sum().item()),
            "identity_overlap_tokens": overlap,
            "interaction_subtracted_from_identity_masks": True,
        },
        "attention_dry_run": {
            "seed": SEED,
            "dtype": "torch.float32",
            "scale": 0.25,
            "full_mask_native_max_abs_error": parity_error,
            "context_max_abs_errors": context_errors,
            "bo_step_10": bo_metrics,
            "mother_step_14": mother_metrics,
            "tolerance": TOLERANCE,
            "actual_block_weights_loaded": True,
            "actual_adapter_block_weights_loaded": True,
        },
        "conclusion": (
            "The regional IP-Adapter branch is numerically identical to the native "
            "processor under a full mask and confines each time-multiplexed identity "
            "effect to its assigned spatial query tokens without interaction-ROI leakage."
            if passed
            else "Regional attention parity or leakage isolation failed."
        ),
        "guards": {
            "single_transformer_attention_block_only": True,
            "full_transformer_instantiated": False,
            "denoise_performed": False,
            "latents_created": False,
            "vae_instantiated": False,
            "image_generation_performed": False,
            "next_full_scene_attempt_authorized": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    write_json(OUTPUT_ROOT / "phase4lr9r7r3r21r2-result.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
