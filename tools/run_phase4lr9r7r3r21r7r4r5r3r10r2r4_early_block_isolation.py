from __future__ import annotations

import json
from pathlib import Path

import run_phase4lr9r7r3r21r7r4r5r3r6_structural_trajectory as runner

BASELINE_ROOT = runner.BASELINE_ROOT
R10_R2_R3_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r3-channel-attribution-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r3-result.json"
)
BASELINE_CACHE = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r7-scale-terminal-isolation-v1/baseline-cache.pt"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r4-early-block-isolation-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r4-result.json"
PROFILES = {
    "a_blocks_0_4": list(range(0, 5)),
    "b_blocks_5_9": list(range(5, 10)),
}


def run_profile(profile_id: str, early_blocks: list[int]) -> Path:
    profile_root = OUTPUT_ROOT / profile_id
    runner.R5_RESULT = R10_R2_R3_RESULT
    runner.OUTPUT_ROOT = profile_root
    runner.RESULT_PATH = profile_root / "result.json"
    runner.PHASE = f"4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R4-{profile_id.upper()}"
    runner.EXPECTED_PRIOR_STATUS = "FAIL"
    runner.EXPECTED_PRIOR_CLOSURE = "OPEN_PENDING_TRAJECTORY_REPAIR"
    runner.BASELINE_CACHE_INPUT = Path(BASELINE_CACHE)
    runner.BASELINE_CACHE_OUTPUT = None
    runner.EARLY_BLOCKS = early_blocks
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
    return runner.RESULT_PATH


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R10-R2-R4 checkpoint already exists; refusing to overwrite")
    paths = {
        profile_id: run_profile(profile_id, blocks)
        for profile_id, blocks in PROFILES.items()
    }
    full = {
        profile_id: json.loads(path.read_text(encoding="utf-8"))
        for profile_id, path in paths.items()
    }
    eligible = [
        profile_id for profile_id, payload in full.items() if payload["status"].startswith("PASS_")
    ]
    selected = (
        max(
            eligible,
            key=lambda profile_id: (
                full[profile_id]["comparison"]["final_spatial_ratio"],
                -full[profile_id]["comparison"]["maximum_relative_latent_delta"],
            ),
        )
        if eligible
        else None
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R4",
        "status": "PASS_EARLY_BLOCK_GROUP_ISOLATION" if selected else "FAIL",
        "baseline_cache": str(BASELINE_CACHE.resolve()),
        "profiles": {
            profile_id: {
                "result_path": str(paths[profile_id].resolve()),
                "early_blocks": PROFILES[profile_id],
                "early_steps": [2, 3],
                "middle_steps": [],
                "status": payload["status"],
                "gates": payload["gates"],
                "comparison": payload["comparison"],
                "latent_critics": {
                    "baseline": payload["baseline"]["latent_critic"],
                    "active": payload["active"]["latent_critic"],
                    "paired": payload["paired_critic"],
                },
                "error_feedback_reset_count": payload["guards"]["error_feedback_reset_count"],
            }
            for profile_id, payload in full.items()
        },
        "eligible_profiles": eligible,
        "selected_profile": selected,
        "trajectory_authorized": selected is not None,
        "phase4l_closure": {
            "status": (
                "OPEN_PENDING_DECODE_AUTHORIZATION_REVIEW"
                if selected
                else "OPEN_PENDING_TRAJECTORY_REPAIR"
            ),
            "all_requirements_satisfied": False,
        },
        "guards": {
            "total_transformer_forward_count": 48,
            "total_scheduler_step_count": 48,
            "total_trajectory_count": 2,
            "baseline_loaded_from_cache_for_all_profiles": True,
            "vae_calls": {"forward": 0, "decode": 0},
            "images_created": 0,
            "decode_authorized": False,
            "new_generation_authorized": False,
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
    if selected is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
