from __future__ import annotations

import gc
import hashlib
import io
import json
from pathlib import Path

import torch
import torch.nn.functional as functional
from PIL import Image

from ai_story.image_gate_profiles import neutral_identity_portrait_gates
from ai_story.image_qa import LocalImageQualityAssessor
from ai_story.provider_config import configure_job

PROJECT_ROOT = Path(__file__).resolve().parents[1]
R1_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r1-negative-conditioning-lock-v1/phase4lr9r7r1-result.json"
NEGATIVE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7-neutral-identity-canary-v1/candidates/neutral-identity/attempt-1.png"
REFERENCE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1/youth-torn-paper-boat/work/characters/bo.png"
POSITIVE_SOURCE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4a/review_assets/adult-memory-choice/linh.png"
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER_WEIGHT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter/ip-adapter.bin")
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r2-identity-conditioning-dry-run-v1"
REFERENCE_CROP_BOX = (384, 0, 1152, 768)
POSITIVE_CROP_BOX = (330, 0, 1200, 870)
NEGATIVE_SHA256 = "48a1135f69aa514d2a1251a1abcd007ca45279697c6aedab6633e1b06a66c90b"
REFERENCE_SHA256 = "5c253d4a48a1e72fa1632be78fdc2ab111a594b8714f4c39af911ab4b4fc3c29"
PLANNED_SCALE = 0.5


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


def assess_controls() -> dict:
    gates = neutral_identity_portrait_gates()
    with Image.open(POSITIVE_SOURCE) as source:
        positive = source.convert("RGB").crop(POSITIVE_CROP_BOX).resize(
            (512, 512), Image.Resampling.LANCZOS
        )
    assessor = LocalImageQualityAssessor(
        configure_job("local", None, "quality")["runtimes"]["diffusers"]["qa"]
    )
    try:
        negative = assessor.assess_fidelity_probes(
            NEGATIVE.read_bytes(), fidelity_probes=gates
        )
        positive_result = assessor.assess_fidelity_probes(
            png_bytes(positive), fidelity_probes=gates
        )
    finally:
        assessor.unload()
    return {
        "negative": negative,
        "positive": positive_result,
        "positive_source_path": str(POSITIVE_SOURCE.resolve()),
        "positive_source_sha256": digest(POSITIVE_SOURCE),
        "positive_crop_box_in_memory": list(POSITIVE_CROP_BOX),
        "positive_crop_persisted": False,
    }


def embedding_projection_dry_run() -> dict:
    from diffusers.models.embeddings import IPAdapterTimeImageProjection
    from transformers import SiglipImageProcessor, SiglipVisionModel

    processor = SiglipImageProcessor.from_pretrained(SIGLIP_ROOT, local_files_only=True)
    encoder = SiglipVisionModel.from_pretrained(
        SIGLIP_ROOT,
        local_files_only=True,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    ).eval()
    with Image.open(REFERENCE) as source:
        source = source.convert("RGB")
        source_size = list(source.size)
        identity_crop = source.crop(REFERENCE_CROP_BOX)
    crop_size = list(identity_crop.size)
    aspect_preserved = crop_size[0] == crop_size[1]
    pixels = processor(images=[source, identity_crop], return_tensors="pt").pixel_values.to(
        dtype=torch.bfloat16
    )
    with torch.inference_mode():
        embeddings = encoder(pixels, output_hidden_states=True).hidden_states[-2]
    full_embedding, crop_embedding = embeddings[0:1], embeddings[1:2]
    pooled_cosine = float(
        functional.cosine_similarity(
            full_embedding.float().mean(dim=1), crop_embedding.float().mean(dim=1)
        ).item()
    )
    token_delta = float((full_embedding.float() - crop_embedding.float()).abs().mean().item())

    state = torch.load(ADAPTER_WEIGHT, map_location="cpu", weights_only=True)
    projection_state = convert_projection_state(state["image_proj"])
    embed_dim = projection_state["proj_in.weight"].shape[1]
    output_dim = projection_state["proj_out.weight"].shape[0]
    hidden_dim = projection_state["proj_in.weight"].shape[0]
    heads = projection_state["layers.0.attn.to_q.weight"].shape[0] // 64
    num_queries = projection_state["latents"].shape[1]
    timestep_in_dim = projection_state["time_embedding.linear_1.weight"].shape[1]
    projection = IPAdapterTimeImageProjection(
        embed_dim=embed_dim,
        output_dim=output_dim,
        hidden_dim=hidden_dim,
        heads=heads,
        num_queries=num_queries,
        timestep_in_dim=timestep_in_dim,
    ).to(dtype=torch.bfloat16).eval()
    projection.load_state_dict(projection_state, strict=True)
    timestep_checks = []
    with torch.inference_mode():
        for timestep in (0, 500, 999):
            projected, timestep_embedding = projection(
                crop_embedding, torch.tensor([timestep], dtype=torch.long)
            )
            timestep_checks.append({
                "timestep": timestep,
                "projected_shape": list(projected.shape),
                "projected_dtype": str(projected.dtype),
                "projected_finite": bool(torch.isfinite(projected).all().item()),
                "projected_nonzero": bool(torch.count_nonzero(projected).item() > 0),
                "projected_abs_mean": round(float(projected.float().abs().mean().item()), 6),
                "timestep_embedding_shape": list(timestep_embedding.shape),
                "timestep_embedding_finite": bool(torch.isfinite(timestep_embedding).all().item()),
            })
    result = {
        "reference_path": str(REFERENCE.resolve()),
        "reference_sha256": digest(REFERENCE),
        "reference_size": source_size,
        "identity_crop_box_in_memory": list(REFERENCE_CROP_BOX),
        "identity_crop_size": crop_size,
        "identity_crop_persisted": False,
        "aspect_ratio_preserved": aspect_preserved,
        "processor_output_shape": list(pixels.shape),
        "encoder_dtype": str(next(encoder.parameters()).dtype),
        "embedding_shape": list(crop_embedding.shape),
        "embedding_dtype": str(crop_embedding.dtype),
        "embedding_finite": bool(torch.isfinite(crop_embedding).all().item()),
        "embedding_nonzero": bool(torch.count_nonzero(crop_embedding).item() > 0),
        "full_vs_identity_crop_pooled_cosine": round(pooled_cosine, 6),
        "full_vs_identity_crop_token_mean_absolute_delta": round(token_delta, 6),
        "projection_class": projection.__class__.__name__,
        "projection_strict_load": True,
        "projection_num_queries": num_queries,
        "projection_output_dim": output_dim,
        "planned_ip_adapter_scale": PLANNED_SCALE,
        "timestep_checks": timestep_checks,
        "transformer_instantiated": False,
        "transformer_called": False,
        "vae_instantiated": False,
        "vae_called": False,
        "latents_created": False,
        "denoise_performed": False,
        "images_created": 0,
    }
    del projection, projection_state, state, embeddings, full_embedding, crop_embedding
    del pixels, encoder, processor, source, identity_crop
    gc.collect()
    return result


def main() -> None:
    prior = json.loads(R1_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_WITH_NEXT_GENERATION_BLOCKED":
        raise RuntimeError("Phase 4L-R9-R7-R1 must be locked before R2")
    if digest(NEGATIVE) != NEGATIVE_SHA256 or digest(REFERENCE) != REFERENCE_SHA256:
        raise RuntimeError("Locked R7 fixture or identity reference changed")

    controls = assess_controls()
    dry_run = embedding_projection_dry_run()
    controls_pass = (
        controls["negative"]["status"] == "ASSESSED_FAIL"
        and controls["negative"]["failed_probes"]
        == [gate["probe_id"] for gate in neutral_identity_portrait_gates()]
        and controls["positive"]["status"] == "ASSESSED_PASS"
    )
    projection_pass = (
        dry_run["aspect_ratio_preserved"]
        and dry_run["encoder_dtype"] == "torch.bfloat16"
        and dry_run["embedding_shape"] == [1, 729, 1152]
        and dry_run["embedding_dtype"] == "torch.bfloat16"
        and dry_run["embedding_finite"]
        and dry_run["embedding_nonzero"]
        and dry_run["projection_strict_load"]
        and dry_run["projection_num_queries"] == 64
        and all(
            check["projected_shape"] == [1, 64, 2432]
            and check["projected_dtype"] == "torch.bfloat16"
            and check["projected_finite"]
            and check["projected_nonzero"]
            and check["timestep_embedding_finite"]
            for check in dry_run["timestep_checks"]
        )
    )
    passed = controls_pass and projection_pass
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R2",
        "status": "PASS_READY_FOR_MANUAL_AUTHORIZATION" if passed else "FAIL",
        "critic_control_lock": {
            "status": "PASS" if controls_pass else "FAIL",
            **controls,
        },
        "identity_conditioning_dry_run": {
            "status": "PASS" if projection_pass else "FAIL",
            **dry_run,
        },
        "guards": {
            "all_crops_in_memory_only": True,
            "new_bitmap_written": False,
            "image_generation_performed": False,
            "transformer_called": False,
            "vae_called": False,
            "denoise_performed": False,
            "next_neutral_attempt_started": False,
            "next_neutral_attempt_requires_manual_authorization": True,
            "climax_generated": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / "phase4lr9r7r2-result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
