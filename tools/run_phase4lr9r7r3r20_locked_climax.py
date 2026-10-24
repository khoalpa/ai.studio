from __future__ import annotations

import gc
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import psutil
import torch
from PIL import Image
from run_phase4lr9r7r3r3_latent_trajectory_ab import (
    ADAPTER_ROOT,
    LARGE_ROOT,
    SIGLIP_ROOT,
)
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
    evaluate_latent_discontinuity,
    observation_from_profile,
)
from ai_story.provider_config import configure_job

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
AUTH_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r19r3-manual-approval-v1/phase4lr9r7r3r19r3-result.json"
)
SOURCE_WORK = BASELINE_ROOT / "phase4l-climax-canary-v1/youth-torn-paper-boat/work"
BO_REFERENCE = SOURCE_WORK / "characters/bo.png"
ME_REFERENCE = SOURCE_WORK / "characters/me.png"
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r20-locked-climax-v1"
CANDIDATE = OUTPUT_ROOT / "candidates/climax/attempt-1.png"
ASSESSMENT_PATH = OUTPUT_ROOT / "candidates/climax/attempt-1-assessment.json"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r20-result.json"
WORKER_LOG = OUTPUT_ROOT / "worker.log"
ENTRYPOINT = Path(__file__).resolve()
PHASE = "4L-R9-R7-R3-R20"
PRIOR_RESULT = AUTH_RESULT
PRIOR_STATUS = "MANUAL_APPROVE_ONE_CLIMAX_ATTEMPT_AUTHORIZED"
REQUIRE_AUTHORIZATION = True
LATENT_ONLY = False
IDENTITY_MODE = "MEAN_TWO_REFERENCES"
CLEAN_CONTROL_STATUS = "PASS_CLEAN_SCALE0_CONTROL"
BLOCKED_CONTROL_STATUS = "PASS_BLOCKED_SCALE0_CONTROL"
SCHEDULE = [
    {"effective_step": 0, "scale": 0.0},
    {"effective_step": 8, "scale": 0.25},
    {"effective_step": 16, "scale": 0.0},
]
SEED = 420917
STEPS = 24
GUIDANCE_SCALE = 5.0
TAIL_START = 16
INTERACTION_CROP = [0.32, 0.42, 0.68, 0.76]
BO_CROP = (384, 0, 1152, 768)
ME_CROP = (384, 0, 1152, 768)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def worker() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from diffusers import StableDiffusion3Pipeline
    from transformers import SiglipImageProcessor, SiglipVisionModel

    if CANDIDATE.exists():
        raise RuntimeError("R20 attempt 1 already exists; refusing a second generation")
    pipe = StableDiffusion3Pipeline.from_pretrained(
        LARGE_ROOT,
        local_files_only=True,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    feature_extractor = SiglipImageProcessor.from_pretrained(
        SIGLIP_ROOT, local_files_only=True
    )
    image_encoder = SiglipVisionModel.from_pretrained(
        SIGLIP_ROOT,
        local_files_only=True,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    pipe.register_modules(
        feature_extractor=feature_extractor, image_encoder=image_encoder
    )
    pipe.load_ip_adapter(
        ADAPTER_ROOT,
        weight_name="ip-adapter.bin",
        image_encoder_folder=None,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    pipe.set_ip_adapter_scale(0.0)
    pipe.enable_model_cpu_offload(device="cuda")
    pipe.vae.disable_tiling()
    pipe.vae.disable_slicing()

    with Image.open(BO_REFERENCE) as source:
        bo_crop = source.convert("RGB").crop(BO_CROP)
    with Image.open(ME_REFERENCE) as source:
        me_crop = source.convert("RGB").crop(ME_CROP)
    with torch.inference_mode():
        bo_embedding = pipe.encode_image(bo_crop, pipe._execution_device)
        me_embedding = pipe.encode_image(me_crop, pipe._execution_device)
        cfg_me_embedding = torch.cat(
            [torch.zeros_like(me_embedding), me_embedding], dim=0
        )
        if IDENTITY_MODE == "MEAN_TWO_REFERENCES":
            identity_embedding = (bo_embedding + me_embedding) / 2
        elif IDENTITY_MODE == "BO_ONLY":
            identity_embedding = bo_embedding
        elif IDENTITY_MODE == "ME_ONLY":
            identity_embedding = me_embedding
        elif IDENTITY_MODE == "TIME_MULTIPLEXED_BO_ME":
            identity_embedding = bo_embedding
        else:
            raise RuntimeError(f"Unsupported identity mode: {IDENTITY_MODE}")
        cfg_identity_embedding = torch.cat(
            [torch.zeros_like(identity_embedding), identity_embedding], dim=0
        )

    vae_calls = {"forward": 0, "decode": 0}

    def count_vae_forward(*_args, **_kwargs):
        vae_calls["forward"] += 1

    def count_vae_decode(*_args, **_kwargs):
        vae_calls["decode"] += 1

    forward_hook = pipe.vae.register_forward_pre_hook(count_vae_forward)
    decode_hook = pipe.vae.decoder.register_forward_pre_hook(count_vae_decode)
    tail_profiles = []
    scale_events = [dict(SCHEDULE[0])]
    identity_events = [{"effective_step": 0, "identity": "BO"}]

    def capture_latents(
        _pipe,
        step_index,
        timestep,
        callback_kwargs,
        mother_cfg_embedding=cfg_me_embedding,
    ):
        if step_index >= TAIL_START:
            latent = callback_kwargs["latents"].detach().cpu()
            tail_profiles.append(
                {
                    "step": int(step_index),
                    "timestep": float(timestep.item()),
                    "boundaries": boundary_diagnostics(latent),
                }
            )
        next_step = step_index + 1
        for event in SCHEDULE[1:]:
            if event["effective_step"] == next_step:
                _pipe.set_ip_adapter_scale(float(event["scale"]))
                scale_events.append(dict(event))
        if IDENTITY_MODE == "TIME_MULTIPLEXED_BO_ME" and next_step == 12:
            _pipe._joint_attention_kwargs["ip_adapter_image_embeds"] = (
                mother_cfg_embedding
            )
            identity_events.append({"effective_step": 12, "identity": "ME"})
        print(json.dumps({"progress": f"step_{step_index + 1}_of_{STEPS}"}), flush=True)
        return callback_kwargs

    generator = torch.Generator(device="cpu").manual_seed(SEED)
    started = time.perf_counter()
    with torch.inference_mode():
        output = pipe(
            prompt=PHOTOREALISTIC_INTERACTION_PROMPT,
            negative_prompt=PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
            ip_adapter_image_embeds=cfg_identity_embedding,
            height=512,
            width=512,
            num_inference_steps=STEPS,
            guidance_scale=GUIDANCE_SCALE,
            num_images_per_prompt=1,
            generator=generator,
            output_type="latent",
            callback_on_step_end=capture_latents,
            callback_on_step_end_tensor_inputs=["latents"],
        )
    final_latent = output.images.detach()
    observations = []
    for item in tail_profiles:
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries")):
            observations.append(
                observation_from_profile(
                    step=item["step"], axis=axis, profile=item["boundaries"][key]
                )
            )
    critic = evaluate_latent_discontinuity(
        observations, LatentDiscontinuityConfig()
    )
    if LATENT_ONLY:
        metrics = {
            "seed": SEED,
            "dimensions": [512, 512],
            "pipeline_dtype": "torch.bfloat16",
            "steps": STEPS,
            "guidance_scale": GUIDANCE_SCALE,
            "ip_adapter_scale_schedule": scale_events,
            "identity_conditioning": IDENTITY_MODE,
            "identity_schedule": identity_events,
            "latent_critic": asdict(critic),
            "latent_tail_profiles": tail_profiles,
            "vae_calls": vae_calls,
            "images_created": 0,
            "trajectory_seconds": round(time.perf_counter() - started, 3),
            "cuda_max_allocated_mib": round(
                torch.cuda.max_memory_allocated() / 1024**2, 2
            ),
        }
        forward_hook.remove()
        decode_hook.remove()
        pipe.maybe_free_model_hooks()
        del output, final_latent, bo_embedding, me_embedding
        del identity_embedding, cfg_identity_embedding
        del cfg_me_embedding
        del bo_crop, me_crop, generator, feature_extractor, image_encoder, pipe
        gc.collect()
        torch.cuda.empty_cache()
        metrics["cuda_allocated_mib_after_cleanup"] = round(
            torch.cuda.memory_allocated() / 1024**2, 2
        )
        print(json.dumps(metrics), flush=True)
        return
    if critic.blocked:
        raise RuntimeError("Latent critic blocked R20 decode: " + json.dumps(asdict(critic)))

    decode_started = time.perf_counter()
    scaled_latent = (
        final_latent / pipe.vae.config.scaling_factor
    ) + pipe.vae.config.shift_factor
    with torch.inference_mode():
        decoded = pipe.vae.decode(
            scaled_latent.to(pipe._execution_device), return_dict=False
        )[0]
    images = pipe.image_processor.postprocess(decoded, output_type="pil")
    if len(images) != 1:
        raise RuntimeError(f"Expected one decoded image, received {len(images)}")
    CANDIDATE.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(CANDIDATE, format="PNG")
    metrics = {
        "generation_seconds": round(time.perf_counter() - started, 3),
        "decode_seconds": round(time.perf_counter() - decode_started, 3),
        "seed": SEED,
        "dimensions": list(images[0].size),
        "images_created": 1,
        "candidate_sha256": file_sha256(CANDIDATE),
        "pipeline_dtype": "torch.bfloat16",
        "steps": STEPS,
        "guidance_scale": GUIDANCE_SCALE,
        "ip_adapter_scale_schedule": scale_events,
        "identity_conditioning": IDENTITY_MODE,
        "identity_schedule": identity_events,
        "identity_crop_boxes_in_memory": {"bo": list(BO_CROP), "me": list(ME_CROP)},
        "identity_crops_persisted": False,
        "latent_critic": asdict(critic),
        "latent_tail_profiles": tail_profiles,
        "vae_calls": vae_calls,
        "vae_tiling_enabled": bool(pipe.vae.use_tiling),
        "vae_slicing_enabled": bool(pipe.vae.use_slicing),
        "cuda_max_allocated_mib": round(torch.cuda.max_memory_allocated() / 1024**2, 2),
    }
    forward_hook.remove()
    decode_hook.remove()
    pipe.maybe_free_model_hooks()
    del output, final_latent, scaled_latent, decoded, images
    del bo_embedding, me_embedding, identity_embedding, cfg_identity_embedding
    del cfg_me_embedding
    del bo_crop, me_crop, generator, feature_extractor, image_encoder, pipe
    gc.collect()
    torch.cuda.empty_cache()
    metrics["cuda_allocated_mib_after_cleanup"] = round(
        torch.cuda.memory_allocated() / 1024**2, 2
    )
    print(json.dumps(metrics), flush=True)


def assess_candidate() -> dict:
    data = CANDIDATE.read_bytes()
    settings = configure_job("local", None, "quality")["runtimes"]["diffusers"]["qa"]
    assessor = LocalImageQualityAssessor(settings)
    fidelity_gates = photorealistic_hand_prop_gates(
        crop_box_normalized=INTERACTION_CROP, include_prop_shape_scale=True
    ) + identity_cast_hand_count_gates(INTERACTION_CROP)
    try:
        fidelity = assessor.assess_fidelity_probes(data, fidelity_probes=fidelity_gates)
        image = Image.open(io.BytesIO(data)).convert("RGB")
        width, height = image.size
        bo_region = image.crop((0, 0, width // 2, int(height * 0.68)))
        me_region = image.crop((width // 2, 0, width, int(height * 0.68)))
        with Image.open(BO_REFERENCE) as source:
            bo_reference = source.convert("RGB").crop(BO_CROP)
        with Image.open(ME_REFERENCE) as source:
            me_reference = source.convert("RGB").crop(ME_CROP)
        bo_score = assessor._clip_similarity(bo_region, reference=bo_reference)
        me_score = assessor._clip_similarity(me_region, reference=me_reference)
        ocr = assessor._ocr(data)
    finally:
        assessor.unload()
    fidelity_by_id = {item["probe_id"]: item for item in fidelity["checks"]}
    identity_threshold = 0.45
    max_ocr = int(settings.get("maximum_ocr_characters", 0))
    detected_text = "".join(character for character in ocr if character.isalnum())
    gates = {item["probe_id"]: fidelity_by_id[item["probe_id"]] for item in fidelity_gates}
    gates.update(
        {
            "bo_identity": {
                "status": "PASS" if bo_score is not None and bo_score >= identity_threshold else "FAIL",
                "score": None if bo_score is None else round(bo_score, 4),
                "threshold": identity_threshold,
            },
            "me_identity": {
                "status": "PASS" if me_score is not None and me_score >= identity_threshold else "FAIL",
                "score": None if me_score is None else round(me_score, 4),
                "threshold": identity_threshold,
            },
            "text_artifact": {
                "status": "PASS" if len(detected_text) <= max_ocr else "FAIL",
                "detected_text": ocr[:120],
                "detected_character_count": len(detected_text),
                "maximum": max_ocr,
            },
        }
    )
    failed = [name for name, gate in gates.items() if gate["status"] != "PASS"]
    return {
        "status": "ASSESSED_PASS" if not failed else "ASSESSED_FAIL",
        "gate_count": len(gates),
        "passed_gate_count": len(gates) - len(failed),
        "failed_gate_ids": failed,
        "gates": gates,
    }


def finalize_blocked_log() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R20 result already exists; refusing to overwrite checkpoint")
    if CANDIDATE.exists():
        raise RuntimeError("Cannot finalize pre-decode blocker after a candidate was written")
    log = WORKER_LOG.read_text(encoding="utf-8")
    matches = re.findall(r"Latent critic blocked R20 decode: (\{[^\r\n]+\})", log)
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one latent-critic blocker in worker log")
    critic = json.loads(matches[0])
    authorization = json.loads(AUTH_RESULT.read_text(encoding="utf-8"))
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R20",
        "status": "AUTO_BLOCKED_PRE_DECODE",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "attempt": 1,
        "attempt_count": 1,
        "authorization_consumed": True,
        "attempts_consumed": 1,
        "candidate_path": None,
        "candidate_sha256": None,
        "prompt": PHOTOREALISTIC_INTERACTION_PROMPT,
        "negative_prompt": PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
        "generation": {
            "seed": SEED,
            "dimensions": [512, 512],
            "pipeline_dtype": "torch.bfloat16",
            "steps": STEPS,
            "guidance_scale": GUIDANCE_SCALE,
            "ip_adapter_scale_schedule": SCHEDULE,
            "identity_conditioning": "MEAN_OF_TWO_SEPARATELY_ENCODED_FACE_CROPS",
            "latent_critic": critic,
            "vae_decode_calls": 0,
            "images_created": 0,
        },
        "automatic_qa": {
            "status": "NOT_RUN_PRE_DECODE_BLOCK",
            "failed_gate_ids": ["latent_discontinuity"],
        },
        "candidate_promotable": False,
        "manual_review_required": False,
        "next_attempt_started": False,
        "phase4n_opened": False,
        "source_package_modified": False,
        "production_profile_changed": False,
        "guards": {
            "exactly_one_attempt": True,
            "locked_profile_sha256": authorization["locked_profile_sha256"],
            "composition_canvas_used": False,
            "vae_boundary_instrumented": True,
            "profile_override_used": False,
            "decode_blocked_before_image_write": True,
        },
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    if "--finalize-blocked-log" in sys.argv:
        finalize_blocked_log()
        return
    if "--worker" in sys.argv:
        worker()
        return
    authorization = json.loads(PRIOR_RESULT.read_text(encoding="utf-8"))
    auth = authorization.get("authorization", {})
    if authorization.get("status") != PRIOR_STATUS:
        raise RuntimeError("Required prior checkpoint is not satisfied")
    if REQUIRE_AUTHORIZATION and (
        not auth.get("authorized")
        or auth.get("maximum_attempts") != 1
        or auth.get("attempts_consumed") != 0
    ):
        raise RuntimeError("R19-R3 one-attempt authorization is not intact")
    if CANDIDATE.exists() or RESULT_PATH.exists():
        raise RuntimeError("R20 already started; refusing a second attempt")
    if REQUIRE_AUTHORIZATION and (
        authorization["locked_profile"]["ip_adapter_scale_schedule"] != SCHEDULE
    ):
        raise RuntimeError("Locked delayed conditioning schedule changed")
    baseline_gpu = gpu_used_mib()
    if baseline_gpu > 4096:
        raise RuntimeError(f"Exclusive GPU unavailable: {baseline_gpu} MiB already used")

    env = os.environ.copy()
    env.update(
        {
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TRANSFORMERS_VERBOSITY": "error",
            "DIFFUSERS_VERBOSITY": "error",
            "PYTHONUNBUFFERED": "1",
        }
    )
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with WORKER_LOG.open("w+", encoding="utf-8") as worker_log:
        process = subprocess.Popen(
            [sys.executable, str(ENTRYPOINT), "--worker"],
            stdout=worker_log,
            stderr=worker_log,
            text=True,
            env=env,
        )
        root = psutil.Process(process.pid)
        peak_rss = 0
        peak_gpu = baseline_gpu
        while process.poll() is None:
            try:
                tree = [root, *root.children(recursive=True)]
                peak_rss = max(
                    peak_rss,
                    sum(item.memory_info().rss for item in tree if item.is_running()),
                )
                peak_gpu = max(peak_gpu, gpu_used_mib())
            except (psutil.NoSuchProcess, subprocess.CalledProcessError):
                pass
            time.sleep(0.5)
        worker_log.flush()
        worker_log.seek(0)
        stdout = worker_log.read()
    if process.returncode != 0:
        raise RuntimeError(f"R20 generation failed: {stdout[-12000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"R20 worker returned no JSON: {stdout[-4000:]}")
    generation = json.loads(lines[-1])
    generation.update(
        {
            "peak_rss_gib": round(peak_rss / 1024**3, 2),
            "gpu_baseline_mib": baseline_gpu,
            "gpu_peak_mib": peak_gpu,
            "gpu_after_worker_exit_mib": gpu_used_mib(),
        }
    )
    if LATENT_ONLY:
        blocked = generation["latent_critic"]["blocked"]
        if IDENTITY_MODE == "BO_ONLY":
            causal_conclusion = (
                "SINGLE_REFERENCE_FULL_SCENE_CONDITIONING_CAUSES_PRECURSOR"
                if blocked
                else "MEAN_TWO_REFERENCE_AGGREGATION_CAUSES_PRECURSOR"
            )
        elif IDENTITY_MODE == "ME_ONLY":
            causal_conclusion = (
                "MOTHER_REFERENCE_BRANCH_CAUSES_PRECURSOR"
                if blocked
                else "MEAN_TWO_REFERENCE_AGGREGATION_CAUSES_PRECURSOR_CONFIRMED"
            )
        elif IDENTITY_MODE == "TIME_MULTIPLEXED_BO_ME":
            causal_conclusion = (
                "TIME_MULTIPLEXED_TWO_IDENTITY_CONDITIONING_CAUSES_PRECURSOR"
                if blocked
                else "TIME_MULTIPLEXED_TWO_IDENTITY_CONDITIONING_IS_LATENT_SAFE"
            )
        else:
            causal_conclusion = (
                "FULL_SCENE_PROMPT_CFG_PATH_CAUSES_PRECURSOR_WITHOUT_IP_ADAPTER"
                if blocked
                else "MULTI_REFERENCE_IDENTITY_CONDITIONING_CAUSES_PRECURSOR"
            )
        result = {
            "schema_version": "1.0",
            "phase": PHASE,
            "status": (
                BLOCKED_CONTROL_STATUS if blocked else CLEAN_CONTROL_STATUS
            ),
            "case_id": "youth-torn-paper-boat",
            "role": "CLIMAX_LATENT_CONTROL",
            "attempt_count": 1,
            "generation": generation,
            "causal_conclusion": causal_conclusion,
            "guards": {
                "latent_only": True,
                "vae_decode_calls": generation["vae_calls"]["decode"],
                "images_created": generation["images_created"],
                "additional_generation_authorized": False,
                "phase4n_opened": False,
            },
        }
        RESULT_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False))
        return
    assessment = assess_candidate()
    ASSESSMENT_PATH.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    automatic_pass = assessment["status"] == "ASSESSED_PASS"
    result = {
        "schema_version": "1.0",
        "phase": PHASE,
        "status": "AWAITING_MANUAL_REVIEW" if automatic_pass else "AUTO_REJECT_AWAITING_MANUAL_REVIEW",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "attempt": 1,
        "attempt_count": 1,
        "authorization_consumed": True,
        "attempts_consumed": 1,
        "candidate_path": str(CANDIDATE.resolve()),
        "candidate_sha256": file_sha256(CANDIDATE),
        "assessment_path": str(ASSESSMENT_PATH.resolve()),
        "prompt": PHOTOREALISTIC_INTERACTION_PROMPT,
        "negative_prompt": PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
        "generation": generation,
        "automatic_qa": assessment,
        "candidate_promotable": automatic_pass,
        "manual_review_required": True,
        "next_attempt_started": False,
        "phase4n_opened": False,
        "source_package_modified": False,
        "production_profile_changed": False,
        "guards": {
            "exactly_one_attempt": True,
            "locked_profile_sha256": authorization["locked_profile_sha256"],
            "composition_canvas_used": False,
            "vae_boundary_instrumented": True,
            "profile_override_used": False,
        },
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
