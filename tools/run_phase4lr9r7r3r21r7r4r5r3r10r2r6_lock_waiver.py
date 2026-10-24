from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
SOURCE_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r4-early-block-isolation-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r4-result.json"
)
SOURCE_PROFILE_RESULT = SOURCE_RESULT.parent / "a_blocks_0_4/result.json"
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6-waiver-lock-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r6-result.json"
LOCKED_LATENT_PATH = SOURCE_RESULT.parent / "a_blocks_0_4/final-active-latent.pt"


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R10-R2-R6 checkpoint already exists; refusing to overwrite")
    source = json.loads(SOURCE_RESULT.read_text(encoding="utf-8"))
    profile = json.loads(SOURCE_PROFILE_RESULT.read_text(encoding="utf-8"))
    if source["status"] != "FAIL":
        raise RuntimeError("expected the accepted source checkpoint to remain FAIL")
    if source["phase4l_closure"]["status"] != "OPEN_PENDING_TRAJECTORY_REPAIR":
        raise RuntimeError("unexpected source Phase 4L closure state")
    accepted = source["profiles"]["a_blocks_0_4"]
    delta = accepted["comparison"]["maximum_relative_latent_delta"]
    spatial = accepted["comparison"]["final_spatial_ratio"]
    if accepted["early_blocks"] != [0, 1, 2, 3, 4] or accepted["early_steps"] != [2, 3]:
        raise RuntimeError("accepted profile topology drifted")
    if profile["guards"]["vae_calls"] != {"forward": 0, "decode": 0}:
        raise RuntimeError("source profile unexpectedly touched VAE")
    latent_available = LOCKED_LATENT_PATH.is_file()
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R6",
        "status": (
            "PASS_WAIVER_LOCKED_READY_FOR_SINGLE_DECODE"
            if latent_available
            else "BLOCKED_MISSING_LOCKED_LATENT"
        ),
        "waiver": {
            "type": "USER_ACCEPTED_RECORDED_DEVIATION",
            "original_thresholds_unchanged": {
                "maximum_relative_latent_delta": 0.05,
                "minimum_final_spatial_ratio": 0.95,
            },
            "accepted_profile": {
                "source_result": str(SOURCE_PROFILE_RESULT.resolve()),
                "early_blocks": [0, 1, 2, 3, 4],
                "early_steps": [2, 3],
                "early_scale": 0.00125,
                "maximum_relative_latent_delta": delta,
                "final_spatial_ratio": spatial,
            },
            "critic_recalibrated_to_force_pass": False,
            "production_profile_changed": False,
        },
        "decode_contract": {
            "locked_latent_path": str(LOCKED_LATENT_PATH.resolve()),
            "locked_latent_available": latent_available,
            "denoise_rerun_authorized": False,
            "maximum_vae_decodes": 1 if latent_available else 0,
            "decode_authorized": latent_available,
            "stop_for_manual_review_after_decode": True,
        },
        "phase4l_closure": {
            "status": (
                "OPEN_PENDING_SINGLE_DECODE_AND_MANUAL_REVIEW"
                if latent_available
                else "OPEN_BLOCKED_MISSING_LOCKED_LATENT"
            ),
            "all_requirements_satisfied": False,
        },
        "guards": {
            "denoise_runs": 0,
            "vae_calls": {"forward": 0, "decode": 0},
            "images_created": 0,
            "production_profile_changed": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not latent_available:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
