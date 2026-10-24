from __future__ import annotations

import gc
import hashlib
import io
import json
from pathlib import Path

import torch
import torch.nn.functional as functional
from PIL import Image
from safetensors import safe_open

from ai_story.image_gate_profiles import neutral_identity_portrait_gates
from ai_story.image_qa import LocalImageQualityAssessor
from ai_story.provider_config import configure_job

PROJECT_ROOT = Path(__file__).resolve().parents[1]
R3_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r3-isolated-identity-canary-v1/phase4lr9r7r3-result.json"
NEGATIVE_R7 = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7-neutral-identity-canary-v1/candidates/neutral-identity/attempt-1.png"
NEGATIVE_R3 = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r3-isolated-identity-canary-v1/candidates/neutral-identity/attempt-1.png"
POSITIVE_SOURCE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4a/review_assets/adult-memory-choice/linh.png"
ADAPTER_WEIGHT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter/ip-adapter.bin")
TRANSFORMER_SHARD = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large/transformer/diffusion_pytorch_model-00001-of-00002.safetensors")
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r3r1-ip-adapter-parity-lock-v1"
NEGATIVE_R7_SHA256 = "48a1135f69aa514d2a1251a1abcd007ca45279697c6aedab6633e1b06a66c90b"
NEGATIVE_R3_SHA256 = "f47b5ec9a41b2d4595431946a845bf838096d45a2eb2ea2d0a55fc56a58c4f83"
POSITIVE_CROP_BOX = (330, 0, 1200, 870)
SOURCE_REVISION = "1f5bb12aad717097f1d0ae884ec6c9394f775045"
SOURCE_URL = (
    "https://huggingface.co/InstantX/SD3.5-Large-IP-Adapter/blob/"
    f"{SOURCE_REVISION}/pipeline_stable_diffusion_3_ipa.py"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def convert_projection_state(state: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    converted = {}
    for key, value in state.items():
        if key.startswith("layers."):
            index = key.split(".")[1]
            key = key.replace(f"layers.{index}.0.norm1", f"layers.{index}.ln0")
            key = key.replace(f"layers.{index}.0.norm2", f"layers.{index}.ln1")
            key = key.replace(f"layers.{index}.0.to_q", f"layers.{index}.attn.to_q")
            key = key.replace(f"layers.{index}.0.to_kv", f"layers.{index}.attn.to_kv")
            key = key.replace(f"layers.{index}.0.to_out", f"layers.{index}.attn.to_out.0")
            key = key.replace(f"layers.{index}.1.0", f"layers.{index}.adaln_norm")
            key = key.replace(f"layers.{index}.1.1", f"layers.{index}.ff.net.0.proj")
            key = key.replace(f"layers.{index}.1.3", f"layers.{index}.ff.net.2")
            key = key.replace(f"layers.{index}.2.1", f"layers.{index}.adaln_proj")
        converted[key] = value
    return converted


def critic_regression() -> dict:
    gates = neutral_identity_portrait_gates()
    with Image.open(POSITIVE_SOURCE) as source:
        positive = source.convert("RGB").crop(POSITIVE_CROP_BOX).resize(
            (512, 512), Image.Resampling.LANCZOS
        )
    assessor = LocalImageQualityAssessor(
        configure_job("local", None, "quality")["runtimes"]["diffusers"]["qa"]
    )
    try:
        r7 = assessor.assess_fidelity_probes(NEGATIVE_R7.read_bytes(), fidelity_probes=gates)
        r3 = assessor.assess_fidelity_probes(NEGATIVE_R3.read_bytes(), fidelity_probes=gates)
        positive_result = assessor.assess_fidelity_probes(
            png_bytes(positive), fidelity_probes=gates
        )
    finally:
        assessor.unload()
    expected = [gate["probe_id"] for gate in gates]
    return {
        "status": "PASS" if (
            r7["failed_probes"] == expected
            and r3["failed_probes"] == expected
            and positive_result["status"] == "ASSESSED_PASS"
        ) else "FAIL",
        "negative_r7": r7,
        "negative_r3": r3,
        "positive": positive_result,
        "positive_source_path": str(POSITIVE_SOURCE.resolve()),
        "positive_source_sha256": digest(POSITIVE_SOURCE),
        "positive_crop_box_in_memory": list(POSITIVE_CROP_BOX),
        "positive_crop_persisted": False,
    }


def manual_projection_forward(projection, image_embedding, timestep):
    timestep_embedding = projection.time_proj(timestep).to(dtype=image_embedding.dtype)
    timestep_embedding = projection.time_embedding(timestep_embedding)
    latents = projection.latents.repeat(image_embedding.size(0), 1, 1)
    encoded = projection.proj_in(image_embedding) + timestep_embedding[:, None]
    for block in projection.layers:
        latents = block(encoded, latents, timestep_embedding)
    latents = projection.proj_out(latents)
    latents = projection.norm_out(latents)
    return latents, timestep_embedding


def native_attention_forward(processor, attn, hidden_states, encoder_hidden_states, ip_hidden_states, temb, scale):
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
    context_query = attn.add_q_proj(encoder_hidden_states).view(
        batch_size, -1, attn.heads, head_dim
    ).transpose(1, 2)
    context_key = attn.add_k_proj(encoder_hidden_states).view(
        batch_size, -1, attn.heads, head_dim
    ).transpose(1, 2)
    context_value = attn.add_v_proj(encoder_hidden_states).view(
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
    output = output.transpose(1, 2).reshape(batch_size, -1, inner_dim).to(joint_query.dtype)
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
    combined_key = torch.cat([image_key, ip_key], dim=2)
    combined_value = torch.cat([
        raw_value.view(batch_size, -1, attn.heads, head_dim).transpose(1, 2),
        ip_value,
    ], dim=2)
    ip_output = functional.scaled_dot_product_attention(
        ip_query, combined_key, combined_value, dropout_p=0.0, is_causal=False
    )
    ip_output = ip_output.transpose(1, 2).reshape(batch_size, -1, inner_dim).to(ip_query.dtype)
    output = output + ip_output * scale
    output = attn.to_out[0](output)
    output = attn.to_out[1](output)
    return output, context_output


def numerical_parity() -> dict:
    from diffusers.models.attention_processor import Attention, SD3IPAdapterJointAttnProcessor2_0
    from diffusers.models.embeddings import IPAdapterTimeImageProjection

    state = torch.load(ADAPTER_WEIGHT, map_location="cpu", weights_only=True)
    projection_state = convert_projection_state(state["image_proj"])
    projection = IPAdapterTimeImageProjection(
        embed_dim=1152,
        output_dim=2432,
        hidden_dim=1280,
        heads=20,
        num_queries=64,
        timestep_in_dim=320,
    ).to(dtype=torch.float32).eval()
    projection.load_state_dict(projection_state, strict=True)
    processor = SD3IPAdapterJointAttnProcessor2_0(
        hidden_size=2432,
        ip_hidden_states_dim=2432,
        head_dim=64,
        timesteps_emb_dim=1280,
        scale=0.5,
    ).to(dtype=torch.float32).eval()
    block_zero = {
        key.split(".", 1)[1]: value.float()
        for key, value in state["ip_adapter"].items()
        if key.startswith("0.")
    }
    processor.load_state_dict(block_zero, strict=True)
    del state, projection_state, block_zero
    gc.collect()

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
    ).to(dtype=torch.float32).eval()
    prefix = "transformer_blocks.0.attn."
    with safe_open(TRANSFORMER_SHARD, framework="pt", device="cpu") as handle:
        attention_state = {
            key[len(prefix):]: handle.get_tensor(key).float()
            for key in handle.keys()
            if key.startswith(prefix)
        }
    attention.load_state_dict(attention_state, strict=False)

    generator = torch.Generator(device="cpu").manual_seed(420917)
    image_embedding = torch.randn((2, 729, 1152), generator=generator, dtype=torch.float32)
    timestep = torch.tensor([500.0, 500.0], dtype=torch.float32)
    with torch.inference_mode():
        projected, timestep_embedding = projection(image_embedding, timestep)
        manual_projected, manual_timestep_embedding = manual_projection_forward(
            projection, image_embedding, timestep
        )
        hidden = torch.randn((2, 4, 2432), generator=generator, dtype=torch.float32)
        context = torch.randn((2, 3, 2432), generator=generator, dtype=torch.float32)
        diffusers_output = processor(
            attention,
            hidden,
            encoder_hidden_states=context,
            ip_hidden_states=projected,
            temb=timestep_embedding,
        )
        native_output = native_attention_forward(
            processor,
            attention,
            hidden,
            context,
            manual_projected,
            manual_timestep_embedding,
            0.5,
        )
    projection_error = float((projected - manual_projected).abs().max().item())
    timestep_error = float((timestep_embedding - manual_timestep_embedding).abs().max().item())
    image_error = float((diffusers_output[0] - native_output[0]).abs().max().item())
    context_error = float((diffusers_output[1] - native_output[1]).abs().max().item())
    image_cosine = float(functional.cosine_similarity(
        diffusers_output[0].flatten(), native_output[0].flatten(), dim=0
    ).item())
    passed = max(projection_error, timestep_error, image_error, context_error) <= 1e-6
    return {
        "status": "PASS" if passed else "FAIL",
        "source_revision": SOURCE_REVISION,
        "source_url": SOURCE_URL,
        "block_index": 0,
        "test_seed": 420917,
        "test_dtype": "torch.float32",
        "scale": 0.5,
        "timestep": 500.0,
        "projection_shape": list(projected.shape),
        "timestep_embedding_shape": list(timestep_embedding.shape),
        "attention_image_output_shape": list(diffusers_output[0].shape),
        "attention_context_output_shape": list(diffusers_output[1].shape),
        "projection_max_abs_error": projection_error,
        "timestep_embedding_max_abs_error": timestep_error,
        "attention_image_max_abs_error": image_error,
        "attention_context_max_abs_error": context_error,
        "attention_image_cosine": image_cosine,
        "tolerance": 1e-6,
        "transformer_block_weights_loaded": True,
        "full_transformer_instantiated": False,
        "vae_instantiated": False,
        "denoise_performed": False,
        "images_created": 0,
    }


def main() -> None:
    prior = json.loads(R3_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "AUTO_REJECT_AWAITING_MANUAL_REVIEW":
        raise RuntimeError("R3 rejected checkpoint is required")
    if digest(NEGATIVE_R7) != NEGATIVE_R7_SHA256 or digest(NEGATIVE_R3) != NEGATIVE_R3_SHA256:
        raise RuntimeError("Locked negative fixture changed")
    critic = critic_regression()
    parity = numerical_parity()
    passed = critic["status"] == "PASS" and parity["status"] == "PASS"
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R1",
        "status": "PASS_WITH_GENERATION_BLOCKED" if passed else "FAIL",
        "critic_regression_lock": critic,
        "ip_adapter_numerical_parity": parity,
        "conclusion": (
            "Diffusers projection, timestep conditioning, scale application, and block-0 attention math "
            "match the InstantX source-equivalent equations. The R3 fragmentation is therefore not "
            "explained by a numerical mismatch in these integration components."
            if passed else
            "Parity or critic regression failed; generation remains blocked."
        ),
        "guards": {
            "negative_r3_mandatory": True,
            "image_generation_performed": False,
            "full_transformer_instantiated": False,
            "vae_instantiated": False,
            "denoise_performed": False,
            "next_neutral_attempt_authorized": False,
            "climax_generated": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / "phase4lr9r7r3r1-result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
