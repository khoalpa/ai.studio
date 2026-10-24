from __future__ import annotations

import gc
import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

import torch
from run_phase4lr9r7r3r21r5_regional_trajectory import assess_candidate
from run_phase4lr9r7r3r21r7r4r3_temporal_window_isolation import latent_critic

from ai_story.latent_discontinuity import (
    LatentDiscontinuityDecision,
    PairedLatentDiscontinuityConfig,
    evaluate_paired_latent_discontinuity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
AUTHORIZATION = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r2-decode-authorization-v1/phase4lr9r7r3r21r7r4r5r2-result.json"
)
R4_R4_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r4-late-tail-micro-window-isolation-v1")
ACTIVE_CACHE = R4_R4_ROOT / "branch-cache/late_terminal.pt"
BASELINE_CACHE = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r3-temporal-window-isolation-v1/branch-cache/baseline.pt"
)
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3-full-scene-candidate-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3-result.json"
CANDIDATE_PATH = OUTPUT_ROOT / "candidates/climax/attempt-1.png"
ASSESSMENT_PATH = OUTPUT_ROOT / "candidates/climax/attempt-1-assessment.json"
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
EXPECTED_AUTHORIZATION_SHA256 = "2029eff8e1429d13a05b6c93f728159defdeae2b517924b2eeb55ba5f6df60fd"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decision(payload: dict) -> LatentDiscontinuityDecision:
    return LatentDiscontinuityDecision(**payload)


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists() or CANDIDATE_PATH.exists():
        raise RuntimeError("R4-R5-R3 output already exists; refusing a second decode")
    if sha256(AUTHORIZATION) != EXPECTED_AUTHORIZATION_SHA256:
        raise RuntimeError("authorization digest changed")
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    auth = authorization["authorization"]
    if not (
        auth["authorized"]
        and auth["maximum_trajectory_attempts"] == 1
        and auth["maximum_vae_decodes"] == 1
        and auth["attempts_consumed"] == 0
        and not auth["automatic_retry_allowed"]
    ):
        raise RuntimeError("one-attempt authorization is not intact")

    baseline_cache = torch.load(BASELINE_CACHE, map_location="cpu", weights_only=False)
    active_cache = torch.load(ACTIVE_CACHE, map_location="cpu", weights_only=False)
    if baseline_cache.get("seed") != 420917 or baseline_cache.get("active_steps") != []:
        raise RuntimeError("paired baseline cache metadata changed")
    if active_cache.get("seed") != 420917 or active_cache.get("active_steps") != [22, 23]:
        raise RuntimeError("terminal active cache metadata changed")
    if active_cache.get("active_blocks") != list(range(28, 38)):
        raise RuntimeError("terminal active block set changed")
    baseline_absolute = latent_critic(baseline_cache["branch"]["profiles"])
    active_absolute = latent_critic(active_cache["branch"]["profiles"])
    paired = evaluate_paired_latent_discontinuity(
        decision(baseline_absolute),
        decision(active_absolute),
        PairedLatentDiscontinuityConfig(),
    )
    if paired.blocked or active_absolute["blocked"]:
        raise RuntimeError("locked latent no longer passes both latent gates")

    from diffusers import AutoencoderKL
    from diffusers.image_processor import VaeImageProcessor

    started = time.perf_counter()
    vae = AutoencoderKL.from_pretrained(
        LARGE_ROOT,
        subfolder="vae",
        local_files_only=True,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    ).to("cuda")
    vae.disable_tiling()
    vae.disable_slicing()
    decode_calls = 0

    def count_decode(*_args, **_kwargs) -> None:
        nonlocal decode_calls
        decode_calls += 1

    hook = vae.decoder.register_forward_pre_hook(count_decode)
    latent = active_cache["branch"]["final_latent"].to("cuda", dtype=torch.bfloat16)
    scaled = latent / vae.config.scaling_factor + vae.config.shift_factor
    with torch.inference_mode():
        decoded = vae.decode(scaled, return_dict=False)[0]
    hook.remove()
    if decode_calls != 1:
        raise RuntimeError(f"expected exactly one VAE decode, got {decode_calls}")
    images = VaeImageProcessor(vae_scale_factor=8).postprocess(decoded, output_type="pil")
    if len(images) != 1:
        raise RuntimeError(f"expected one image, got {len(images)}")
    CANDIDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(CANDIDATE_PATH, format="PNG")
    candidate_sha = sha256(CANDIDATE_PATH)
    decode_seconds = round(time.perf_counter() - started, 3)
    del latent, scaled, decoded, images, vae
    gc.collect()
    torch.cuda.empty_cache()

    assessment = assess_candidate(CANDIDATE_PATH)
    ASSESSMENT_PATH.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    latent_qa = {
        "paired_latent_discontinuity_gate": {
            "status": "PASS",
            "decision": asdict(paired),
        },
        "vae_amplification_precursor_gate": {
            "status": "PASS",
            "decision": active_absolute,
        },
    }
    automatic_pass = assessment["status"] == "ASSESSED_PASS"
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3",
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
        "authorization_sha256": EXPECTED_AUTHORIZATION_SHA256,
        "locked_profile_sha256": authorization["locked_profile_sha256"],
        "candidate_path": str(CANDIDATE_PATH.resolve()),
        "candidate_sha256": candidate_sha,
        "assessment_path": str(ASSESSMENT_PATH.resolve()),
        "generation": {
            "trajectory_completed_before_recovery": True,
            "trajectory_rerun": False,
            "recovered_from_locked_terminal_cache": True,
            "active_cache_sha256": sha256(ACTIVE_CACHE),
            "baseline_cache_sha256": sha256(BASELINE_CACHE),
            "seed": 420917,
            "dimensions": [512, 512],
            "steps": 24,
            "guidance_scale": 5.0,
            "explicit_control": {
                "active_blocks": list(range(28, 38)),
                "scale": 0.01,
                "active_steps": [22, 23],
            },
            "absolute_latent_critic": active_absolute,
            "paired_latent_critic": asdict(paired),
            "vae_calls": {"forward": 0, "decode": decode_calls},
            "images_created": 1,
            "decode_seconds": decode_seconds,
        },
        "automatic_qa": assessment,
        "latent_qa": latent_qa,
        "all_automatic_gates_pass": automatic_pass,
        "candidate_promotable": automatic_pass,
        "manual_review_required": True,
        "manual_review_status": "PENDING",
        "next_attempt_started": False,
        "phase4l_closed": False,
        "phase4n_opened": False,
        "source_package_modified": False,
        "guards": {
            "exactly_one_trajectory_attempt_consumed": True,
            "exactly_one_vae_decode": decode_calls == 1,
            "profile_override_used": False,
            "critic_policy_override_used": False,
            "automatic_retry_started": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
