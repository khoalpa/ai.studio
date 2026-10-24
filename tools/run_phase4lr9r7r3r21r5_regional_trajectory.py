from __future__ import annotations

import gc
import hashlib
import io
import json
import os
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import torch
from PIL import Image
from run_phase4lr9r7r3r5_late_step_decomposition import boundary_diagnostics

from ai_story.image_gate_profiles import (
    PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
    PHOTOREALISTIC_INTERACTION_PROMPT,
    identity_cast_hand_count_gates,
    photorealistic_hand_prop_gates,
)
from ai_story.image_qa import LocalImageQualityAssessor
from ai_story.latent_discontinuity import (
    LatentDiscontinuityConfig,
    PairedLatentDiscontinuityConfig,
    evaluate_latent_discontinuity,
    evaluate_paired_latent_discontinuity,
    observation_from_profile,
)
from ai_story.provider_config import configure_job
from ai_story.regional_ip_adapter import RegionalSD3IPAdapterProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R4_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r4-full-transformer-ab-v1/phase4lr9r7r3r21r4-result.json"
)
BASELINE_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r20r1-scale0-control-v1/phase4lr9r7r3r20r1-result.json"
)
LAYOUT_PATH = BASELINE_ROOT / (
    "phase4lr9r7r3r21r1-negative-spatial-conditioning-lock-v1/regional-spatial-conditioning.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r21r5-regional-trajectory-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r5-result.json"
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
SOURCE_WORK = BASELINE_ROOT / "phase4l-climax-canary-v1/youth-torn-paper-boat/work"
BO_REFERENCE = SOURCE_WORK / "characters/bo.png"
ME_REFERENCE = SOURCE_WORK / "characters/me.png"
IDENTITY_CROP = (384, 0, 1152, 768)
SEED = 420917
STEPS = 24
GUIDANCE = 5.0
DECODE_CANDIDATE = False
CANDIDATE_PATH = OUTPUT_ROOT / "candidates/climax/attempt-1.png"
ASSESSMENT_PATH = OUTPUT_ROOT / "candidates/climax/attempt-1-assessment.json"
AUTHORIZATION_RESULT: Path | None = None
PHASE = "4L-R9-R7-R3-R21-R5"
EXPLICIT_CONTROL_PROFILE: dict | None = None
PAIRED_BASELINE_CACHE: Path | None = None


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def token_mask(include: list[float], exclude: list[float]) -> torch.Tensor:
    rows = (torch.arange(32, dtype=torch.float32) + 0.5) / 32
    columns = (torch.arange(32, dtype=torch.float32) + 0.5) / 32
    y, x = torch.meshgrid(rows, columns, indexing="ij")
    selected = (x >= include[0]) & (y >= include[1]) & (x < include[2]) & (y < include[3])
    excluded = (x >= exclude[0]) & (y >= exclude[1]) & (x < exclude[2]) & (y < exclude[3])
    return (selected & ~excluded).reshape(1, -1, 1).to(torch.float32)


def set_scale(pipe, scale: float) -> None:
    for processor in pipe.transformer.attn_processors.values():
        if isinstance(processor, RegionalSD3IPAdapterProcessor):
            processor.scale = scale


def assess_candidate(path: Path) -> dict:
    data = path.read_bytes()
    settings = configure_job("local", None, "quality")["runtimes"]["diffusers"]["qa"]
    assessor = LocalImageQualityAssessor(settings)
    interaction_crop = [0.37, 0.52, 0.63, 0.74]
    gates = photorealistic_hand_prop_gates(
        crop_box_normalized=interaction_crop, include_prop_shape_scale=True
    ) + identity_cast_hand_count_gates(interaction_crop)
    try:
        fidelity = assessor.assess_fidelity_probes(data, fidelity_probes=gates)
        image = Image.open(io.BytesIO(data)).convert("RGB")
        width, height = image.size
        bo_region = image.crop((0, 0, width // 2, int(height * 0.68)))
        mother_region = image.crop((width // 2, 0, width, int(height * 0.68)))
        with Image.open(BO_REFERENCE) as source:
            bo_reference = source.convert("RGB").crop(IDENTITY_CROP)
        with Image.open(ME_REFERENCE) as source:
            mother_reference = source.convert("RGB").crop(IDENTITY_CROP)
        bo_score = assessor._clip_similarity(bo_region, reference=bo_reference)
        mother_score = assessor._clip_similarity(mother_region, reference=mother_reference)
        ocr = assessor._ocr(data)
    finally:
        assessor.unload()
    checks = {item["probe_id"]: item for item in fidelity["checks"]}
    identity_threshold = 0.45
    detected_text = "".join(character for character in ocr if character.isalnum())
    qa = {gate["probe_id"]: checks[gate["probe_id"]] for gate in gates}
    qa.update(
        {
            "bo_identity": {
                "status": "PASS"
                if bo_score is not None and bo_score >= identity_threshold
                else "FAIL",
                "score": None if bo_score is None else round(bo_score, 4),
                "threshold": identity_threshold,
            },
            "me_identity": {
                "status": "PASS"
                if mother_score is not None and mother_score >= identity_threshold
                else "FAIL",
                "score": None if mother_score is None else round(mother_score, 4),
                "threshold": identity_threshold,
            },
            "text_artifact": {
                "status": "PASS"
                if len(detected_text) <= int(settings.get("maximum_ocr_characters", 0))
                else "FAIL",
                "detected_text": ocr[:120],
                "detected_character_count": len(detected_text),
                "maximum": int(settings.get("maximum_ocr_characters", 0)),
            },
        }
    )
    failed = [name for name, gate in qa.items() if gate["status"] != "PASS"]
    return {
        "status": "ASSESSED_PASS" if not failed else "ASSESSED_FAIL",
        "gate_count": len(qa),
        "passed_gate_count": len(qa) - len(failed),
        "failed_gate_ids": failed,
        "gates": qa,
    }


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists():
        raise RuntimeError("R21-R5 already exists; refusing to rerun")
    prior = json.loads(R4_RESULT.read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_FULL_TRANSFORMER_SINGLE_STEP_AB":
        raise RuntimeError("R21-R4 must pass")
    if baseline.get("status") != "PASS_CLEAN_SCALE0_CONTROL":
        raise RuntimeError("Locked scale-0 baseline is not clean")
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
            SIGLIP_ROOT, local_files_only=True, dtype=torch.bfloat16, low_cpu_mem_usage=True
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
    control_registration = None
    token_controls = None
    if EXPLICIT_CONTROL_PROFILE is not None:
        from run_phase4lr9r7r3r21r7r4_full_transformer_control_ab import (
            HIDDEN_SIZE,
            load_control_tokens,
        )

        from ai_story.explicit_spatial_control import (
            ExplicitControlRegistration,
            ExplicitSpatialControlResidual,
        )

        vector_generator = torch.Generator(device="cpu").manual_seed(SEED)
        vectors = torch.randn((3, HIDDEN_SIZE), generator=vector_generator)
        control = ExplicitSpatialControlResidual(vectors).to(torch.bfloat16)
        control_registration = ExplicitControlRegistration(pipe.transformer, control)
        token_controls = load_control_tokens()

        def explicit_scales(step: int) -> list[float]:
            active = step in EXPLICIT_CONTROL_PROFILE["active_steps"]
            active_blocks = set(EXPLICIT_CONTROL_PROFILE["active_blocks"])
            return [
                EXPLICIT_CONTROL_PROFILE["scale"] if active and index in active_blocks else 0.0
                for index in range(38)
            ]

        control_registration.configure(token_controls, explicit_scales(0))
    pipe.enable_model_cpu_offload(device="cuda")
    pipe.vae.disable_tiling()
    pipe.vae.disable_slicing()

    with Image.open(BO_REFERENCE) as source:
        bo_crop = source.convert("RGB").crop(IDENTITY_CROP)
    with Image.open(ME_REFERENCE) as source:
        mother_crop = source.convert("RGB").crop(IDENTITY_CROP)
    with torch.inference_mode():
        bo_embedding = pipe.encode_image(bo_crop, pipe._execution_device)
        mother_embedding = pipe.encode_image(mother_crop, pipe._execution_device)
    cfg_bo = torch.cat([torch.zeros_like(bo_embedding), bo_embedding], dim=0)
    cfg_mother = torch.cat([torch.zeros_like(mother_embedding), mother_embedding], dim=0)
    layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    regions = layout["regions"]
    interaction = regions["interaction"]["box"]
    bo_mask = token_mask(regions["bo_identity"]["box"], interaction)
    mother_mask = token_mask(regions["mother_identity"]["box"], interaction)
    pipe._joint_attention_kwargs = {"regional_attention_mask": bo_mask}

    profiles = []
    events = [{"effective_step": 0, "scale": 0.0, "identity": "BO"}]

    def callback(_pipe, step_index, timestep, callback_kwargs):
        latent = callback_kwargs["latents"].detach().cpu()
        profiles.append(
            {
                "step": int(step_index),
                "timestep": float(timestep.item()),
                "boundaries": boundary_diagnostics(latent),
            }
        )
        next_step = step_index + 1
        if control_registration is not None and next_step < STEPS:
            control_registration.configure(token_controls, explicit_scales(next_step))
        if next_step == 8:
            set_scale(_pipe, 0.25)
            events.append({"effective_step": 8, "scale": 0.25, "identity": "BO"})
        elif next_step == 12:
            _pipe._joint_attention_kwargs["ip_adapter_image_embeds"] = cfg_mother
            _pipe._joint_attention_kwargs["regional_attention_mask"] = mother_mask.to(
                callback_kwargs["latents"].device
            )
            events.append({"effective_step": 12, "scale": 0.25, "identity": "ME"})
        elif next_step == 16:
            set_scale(_pipe, 0.0)
            events.append({"effective_step": 16, "scale": 0.0, "identity": "ME"})
        print(json.dumps({"progress": f"step_{next_step}_of_{STEPS}"}), flush=True)
        return callback_kwargs

    vae_calls = {"forward": 0, "decode": 0}
    forward_hook = pipe.vae.register_forward_pre_hook(
        lambda *_args, **_kwargs: vae_calls.__setitem__("forward", vae_calls["forward"] + 1)
    )
    decode_hook = pipe.vae.decoder.register_forward_pre_hook(
        lambda *_args, **_kwargs: vae_calls.__setitem__("decode", vae_calls["decode"] + 1)
    )
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    with torch.inference_mode():
        output = pipe(
            prompt=PHOTOREALISTIC_INTERACTION_PROMPT,
            negative_prompt=PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
            ip_adapter_image_embeds=cfg_bo,
            height=512,
            width=512,
            num_inference_steps=STEPS,
            guidance_scale=GUIDANCE,
            num_images_per_prompt=1,
            generator=generator,
            output_type="latent",
            callback_on_step_end=callback,
            callback_on_step_end_tensor_inputs=["latents"],
        )
    final_latent = output.images.detach().cpu()
    observations = [
        observation_from_profile(step=item["step"], axis=axis, profile=item["boundaries"][key])
        for item in profiles
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries"))
    ]
    critic = evaluate_latent_discontinuity(observations, LatentDiscontinuityConfig())
    paired_critic = None
    if PAIRED_BASELINE_CACHE is not None:
        cached = torch.load(PAIRED_BASELINE_CACHE, map_location="cpu", weights_only=False)
        baseline_profiles = cached["branch"]["profiles"]
        baseline_observations = [
            observation_from_profile(step=item["step"], axis=axis, profile=item["boundaries"][key])
            for item in baseline_profiles
            for axis, key in (
                ("row", "row_boundaries"),
                ("column", "column_boundaries"),
            )
        ]
        baseline_critic = evaluate_latent_discontinuity(
            baseline_observations, LatentDiscontinuityConfig()
        )
        paired_critic = evaluate_paired_latent_discontinuity(
            baseline_critic, critic, PairedLatentDiscontinuityConfig()
        )
    critic_allows_decode = (
        not paired_critic.blocked if paired_critic is not None else not critic.blocked
    )
    candidate_sha256 = None
    decode_seconds = None
    if DECODE_CANDIDATE and critic_allows_decode:
        decode_started = time.perf_counter()
        scaled_latent = (
            final_latent.to(pipe._execution_device) / pipe.vae.config.scaling_factor
        ) + pipe.vae.config.shift_factor
        with torch.inference_mode():
            decoded = pipe.vae.decode(scaled_latent, return_dict=False)[0]
        images = pipe.image_processor.postprocess(decoded, output_type="pil")
        if len(images) != 1:
            raise RuntimeError(f"Expected one decoded image, received {len(images)}")
        CANDIDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        images[0].save(CANDIDATE_PATH, format="PNG")
        candidate_sha256 = hashlib.sha256(CANDIDATE_PATH.read_bytes()).hexdigest()
        decode_seconds = round(time.perf_counter() - decode_started, 3)
        del scaled_latent, decoded, images
    forward_hook.remove()
    decode_hook.remove()
    if control_registration is not None:
        control_registration.unregister()
    expected_vae_calls = {"forward": 0, "decode": 1 if DECODE_CANDIDATE else 0}
    passed = critic_allows_decode and len(profiles) == STEPS and vae_calls == expected_vae_calls
    del pipe, output, final_latent, bo_embedding, mother_embedding
    gc.collect()
    torch.cuda.empty_cache()
    if DECODE_CANDIDATE:
        assessment = (
            assess_candidate(CANDIDATE_PATH)
            if candidate_sha256
            else {
                "status": "NOT_RUN_PRE_DECODE_BLOCK",
                "gate_count": 9,
                "passed_gate_count": 0,
                "failed_gate_ids": ["latent_discontinuity"],
                "gates": {},
            }
        )
        ASSESSMENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ASSESSMENT_PATH.write_text(
            json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        automatic_pass = assessment["status"] == "ASSESSED_PASS"
        authorization = (
            json.loads(AUTHORIZATION_RESULT.read_text(encoding="utf-8"))
            if AUTHORIZATION_RESULT is not None
            else {}
        )
        result = {
            "schema_version": "1.0",
            "phase": PHASE,
            "status": (
                "AUTO_PASS_AWAITING_MANUAL_REVIEW"
                if automatic_pass
                else "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
            ),
            "case_id": "youth-torn-paper-boat",
            "role": "CLIMAX",
            "attempt": 1,
            "attempt_count": 1,
            "authorization_consumed": True,
            "attempts_consumed": 1,
            "candidate_path": str(CANDIDATE_PATH.resolve()) if candidate_sha256 else None,
            "candidate_sha256": candidate_sha256,
            "assessment_path": str(ASSESSMENT_PATH.resolve()),
            "prompt": PHOTOREALISTIC_INTERACTION_PROMPT,
            "negative_prompt": PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
            "generation": {
                "seconds": round(time.perf_counter() - started, 3),
                "decode_seconds": decode_seconds,
                "seed": SEED,
                "dimensions": [512, 512],
                "steps": STEPS,
                "guidance_scale": GUIDANCE,
                "events": events,
                "profile_count": len(profiles),
                "latent_critic": asdict(critic),
                "paired_latent_critic": (
                    asdict(paired_critic) if paired_critic is not None else None
                ),
                "explicit_control": EXPLICIT_CONTROL_PROFILE,
                "vae_calls": vae_calls,
                "images_created": 1 if candidate_sha256 else 0,
            },
            "automatic_qa": assessment,
            "latent_qa": {
                "paired_latent_discontinuity_gate": {
                    "status": "PASS" if critic_allows_decode else "FAIL",
                    "decision": (asdict(paired_critic) if paired_critic is not None else None),
                },
                "vae_amplification_precursor_gate": {
                    "status": "PASS" if not critic.blocked else "FAIL",
                    "decision": asdict(critic),
                },
            },
            "candidate_promotable": automatic_pass,
            "manual_review_required": True,
            "next_attempt_started": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
            "source_package_modified": False,
            "guards": {
                "exactly_one_attempt": True,
                "locked_profile_sha256": authorization.get("locked_profile_sha256"),
                "profile_override_used": False,
                "spatial_contract_override_used": False,
                "critic_policy_override_used": False,
                "automatic_retry_started": False,
            },
        }
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not passed:
            raise SystemExit(1)
        return
    result = {
        "schema_version": "1.0",
        "phase": PHASE,
        "status": "PASS_CLEAN_REGIONAL_TIME_MULTIPLEXED_TRAJECTORY" if passed else "FAIL",
        "baseline_a": {
            "path": str(BASELINE_RESULT.resolve()),
            "status": baseline["status"],
            "latent_critic": baseline["generation"]["latent_critic"],
        },
        "regional_b": {
            "seed": SEED,
            "steps": STEPS,
            "guidance_scale": GUIDANCE,
            "events": events,
            "profile_count": len(profiles),
            "latent_critic": asdict(critic),
            "latent_profiles": profiles,
            "final_latent_finite": True,
        },
        "runtime": {
            "seconds": round(time.perf_counter() - started, 3),
            "gpu_before_mib": gpu_before,
            "gpu_after_mib": gpu_used_mib(),
        },
        "guards": {
            "baseline_reused_not_rerun": True,
            "regional_trajectory_count": 1,
            "scheduler_steps": STEPS,
            "vae_calls": vae_calls,
            "images_created": 0,
            "next_decode_authorized": False,
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
