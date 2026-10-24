from __future__ import annotations

import gc
import hashlib
import json
import os
import time
from pathlib import Path

import run_phase4lr9r7r3r21r7r4r5r3r6_structural_trajectory as runner
import torch
from run_phase4lr9r7r3r21r5_regional_trajectory import assess_candidate

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
WAIVER_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6-waiver-lock-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6-result.json"
)
SOURCE_PROFILE_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r4-early-block-isolation-v1/"
    "a_blocks_0_4/result.json"
)
BASELINE_CACHE = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r7-scale-terminal-isolation-v1/baseline-cache.pt"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r1-replay-decode-v1"
)
REPLAY_ROOT = OUTPUT_ROOT / "replay"
REPLAY_RESULT = REPLAY_ROOT / "result.json"
LATENT_PATH = OUTPUT_ROOT / "locked-final-active-latent.pt"
CANDIDATE_PATH = OUTPUT_ROOT / "candidates/climax/attempt-1.png"
ASSESSMENT_PATH = OUTPUT_ROOT / "candidates/climax/attempt-1-assessment.json"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r6r1-result.json"
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
PARITY_ABS_TOLERANCE = 1e-9


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    if RESULT_PATH.exists() or LATENT_PATH.exists() or CANDIDATE_PATH.exists():
        raise RuntimeError("R10-R2-R6-R1 output already exists; refusing replay or decode retry")
    waiver = json.loads(WAIVER_RESULT.read_text(encoding="utf-8"))
    if waiver["status"] != "BLOCKED_MISSING_LOCKED_LATENT":
        raise RuntimeError("waiver checkpoint is not in the expected blocked state")
    contract = waiver["decode_contract"]
    if contract["denoise_rerun_authorized"] or contract["decode_authorized"]:
        raise RuntimeError("original waiver contract unexpectedly changed")
    source = json.loads(SOURCE_PROFILE_RESULT.read_text(encoding="utf-8"))

    runner.R5_RESULT = WAIVER_RESULT
    runner.OUTPUT_ROOT = REPLAY_ROOT
    runner.RESULT_PATH = REPLAY_RESULT
    runner.PHASE = "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R6-R1-REPLAY"
    runner.EXPECTED_PRIOR_STATUS = "BLOCKED_MISSING_LOCKED_LATENT"
    runner.EXPECTED_PRIOR_CLOSURE = "OPEN_BLOCKED_MISSING_LOCKED_LATENT"
    runner.BASELINE_CACHE_INPUT = BASELINE_CACHE
    runner.BASELINE_CACHE_OUTPUT = None
    runner.ACTIVE_LATENT_OUTPUT = LATENT_PATH
    runner.EARLY_BLOCKS = [0, 1, 2, 3, 4]
    runner.MIDDLE_BLOCKS = []
    runner.TERMINAL_BLOCKS = []
    runner.EARLY_STEPS = [2, 3]
    runner.MIDDLE_STEPS = []
    runner.TERMINAL_STEPS = []
    runner.EARLY_SCALE = 0.00125
    runner.MIDDLE_SCALE = 0.0
    runner.TERMINAL_SCALE = 0.0
    runner.ERROR_FEEDBACK = True
    runner.RESET_ERROR_FEEDBACK_PER_FORWARD = True
    try:
        runner.main()
    except SystemExit as error:
        if error.code != 1:
            raise

    replay = json.loads(REPLAY_RESULT.read_text(encoding="utf-8"))
    source_delta = source["comparison"]["maximum_relative_latent_delta"]
    source_spatial = source["comparison"]["final_spatial_ratio"]
    replay_delta = replay["comparison"]["maximum_relative_latent_delta"]
    replay_spatial = replay["comparison"]["final_spatial_ratio"]
    delta_error = abs(replay_delta - source_delta)
    spatial_error = abs(replay_spatial - source_spatial)
    parity_pass = (
        delta_error <= PARITY_ABS_TOLERANCE
        and spatial_error <= PARITY_ABS_TOLERANCE
        and replay["guards"]["trajectory_count"] == 1
        and replay["guards"]["active_latent_persisted"] is True
        and replay["guards"]["vae_calls"] == {"forward": 0, "decode": 0}
    )
    if not parity_pass:
        raise RuntimeError(
            f"deterministic parity failed: delta_error={delta_error}, spatial_error={spatial_error}"
        )

    cache = torch.load(LATENT_PATH, map_location="cpu", weights_only=False)
    if cache["seed"] != runner.SEED or cache["steps"] != runner.STEPS:
        raise RuntimeError("persisted latent metadata drifted")
    if cache["profile"]["early_blocks"] != [0, 1, 2, 3, 4]:
        raise RuntimeError("persisted latent topology drifted")

    from diffusers import AutoencoderKL
    from diffusers.image_processor import VaeImageProcessor

    decode_started = time.perf_counter()
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
    latent = cache["final_latent"].to("cuda", dtype=torch.bfloat16)
    scaled = latent / vae.config.scaling_factor + vae.config.shift_factor
    with torch.inference_mode():
        decoded = vae.decode(scaled, return_dict=False)[0]
    hook.remove()
    if decode_calls != 1:
        raise RuntimeError(f"expected exactly one VAE decode, got {decode_calls}")
    images = VaeImageProcessor(vae_scale_factor=8).postprocess(decoded, output_type="pil")
    if len(images) != 1:
        raise RuntimeError(f"expected exactly one decoded image, got {len(images)}")
    CANDIDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(CANDIDATE_PATH, format="PNG")
    decode_seconds = round(time.perf_counter() - decode_started, 3)
    candidate_sha = sha256(CANDIDATE_PATH)
    latent_sha = sha256(LATENT_PATH)
    del latent, scaled, decoded, images, vae, cache
    gc.collect()
    torch.cuda.empty_cache()

    assessment = assess_candidate(CANDIDATE_PATH)
    ASSESSMENT_PATH.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    automatic_pass = assessment["status"] == "ASSESSED_PASS"
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R6-R1",
        "status": (
            "AUTO_PASS_AWAITING_MANUAL_REVIEW"
            if automatic_pass
            else "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
        ),
        "waiver_source": str(WAIVER_RESULT.resolve()),
        "accepted_profile": waiver["waiver"]["accepted_profile"],
        "replay": {
            "trajectory_attempts": 1,
            "deterministic_parity_pass": True,
            "absolute_tolerance": PARITY_ABS_TOLERANCE,
            "source_delta": source_delta,
            "replay_delta": replay_delta,
            "delta_error": delta_error,
            "source_spatial_ratio": source_spatial,
            "replay_spatial_ratio": replay_spatial,
            "spatial_error": spatial_error,
            "latent_path": str(LATENT_PATH.resolve()),
            "latent_sha256": latent_sha,
        },
        "candidate_path": str(CANDIDATE_PATH.resolve()),
        "candidate_sha256": candidate_sha,
        "assessment_path": str(ASSESSMENT_PATH.resolve()),
        "automatic_qa": assessment,
        "all_automatic_gates_pass": automatic_pass,
        "candidate_promotable": automatic_pass,
        "manual_review_required": True,
        "manual_review_status": "PENDING",
        "phase4l_closure": {
            "status": "OPEN_PENDING_MANUAL_REVIEW",
            "all_requirements_satisfied": False,
        },
        "guards": {
            "exactly_one_denoise_replay": True,
            "exactly_one_vae_decode": decode_calls == 1,
            "images_created": 1,
            "automatic_retry_started": False,
            "production_profile_changed": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
            "decode_seconds": decode_seconds,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
