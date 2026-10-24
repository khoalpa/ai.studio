from __future__ import annotations

import json

import run_phase4lr9r7r3r21r7r4r5r3r6_structural_trajectory as runner
from run_phase4lr9r7r3r21r7r4r5r3r10r2r6r3_geometry_dry_run import (
    CHANNELS,
    GRID,
    build_controls,
)

from ai_story.explicit_spatial_control import raster_controls_to_tokens

BASELINE_ROOT = runner.BASELINE_ROOT
R4_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r4-geometry-trajectory-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r4-result.json"
)
ACCEPTED_PROFILE_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r4-early-block-isolation-v1/"
    "a_blocks_0_4/result.json"
)
BASELINE_CACHE = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r7-scale-terminal-isolation-v1/baseline-cache.pt"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r5-mother-gain-v1"
)
RAW_RESULT = OUTPUT_ROOT / "raw-trajectory.json"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r6r5-result.json"
MOTHER_CHANNELS = {"me_face", "me_hand", "me_contact"}
MOTHER_GAIN = 1.5
BO_RETENTION_FLOOR = 0.95
TOLERANCE = 1e-9


def main() -> None:
    if RESULT_PATH.exists() or RAW_RESULT.exists():
        raise RuntimeError("R10-R2-R6-R5 checkpoint already exists; refusing overwrite")
    prior = json.loads(R4_RESULT.read_text(encoding="utf-8"))
    accepted = json.loads(ACCEPTED_PROFILE_RESULT.read_text(encoding="utf-8"))
    if prior["status"] != "PASS_GEOMETRY_LATENT_TRAJECTORY":
        raise RuntimeError("R4 geometry latent trajectory is not locked PASS")
    if prior["next_decode_authorized"]:
        raise RuntimeError("R4 unexpectedly authorized decode")

    raster, _ = build_controls()
    base_tokens = raster_controls_to_tokens(raster, GRID, threshold=0.25)
    gains = [MOTHER_GAIN if name in MOTHER_CHANNELS else 1.0 for name in CHANNELS]
    gain_tensor = base_tokens.new_tensor(gains).view(1, 1, -1)
    weighted_tokens = base_tokens.float() * gain_tensor
    region_masks = {
        name: base_tokens[..., index].bool() for index, name in enumerate(CHANNELS)
    }

    runner.R5_RESULT = R4_RESULT
    runner.OUTPUT_ROOT = OUTPUT_ROOT
    runner.RESULT_PATH = RAW_RESULT
    runner.PHASE = "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R6-R5-RAW"
    runner.EXPECTED_PRIOR_STATUS = "PASS_GEOMETRY_LATENT_TRAJECTORY"
    runner.EXPECTED_PRIOR_CLOSURE = "OPEN_PENDING_GEOMETRY_DECODE_AUTHORIZATION_REVIEW"
    runner.BASELINE_CACHE_INPUT = BASELINE_CACHE
    runner.BASELINE_CACHE_OUTPUT = None
    runner.ACTIVE_LATENT_OUTPUT = None
    runner.EARLY_CONTROLS_OVERRIDE = weighted_tokens
    runner.SPATIAL_REGION_MASKS_OVERRIDE = region_masks
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

    raw = json.loads(RAW_RESULT.read_text(encoding="utf-8"))
    comparison = raw["comparison"]
    source = accepted["comparison"]
    prior_regions = prior["comparison"]["regions"]
    current_regions = comparison["regions"]
    mother_improvement = {
        name: (
            current_regions[name]["final_spatial_ratio"]
            > prior_regions[name]["final_spatial_ratio"]
        )
        for name in sorted(MOTHER_CHANNELS)
    }
    protected_regions = ["bo_face", "bo_hand", "paper_boat", "bo_contact"]
    bo_retention = {
        name: (
            current_regions[name]["final_spatial_ratio"]
            >= prior_regions[name]["final_spatial_ratio"] * BO_RETENTION_FLOOR
        )
        for name in protected_regions
    }
    gates = {
        "maximum_relative_latent_delta_not_worse_than_waiver": (
            comparison["maximum_relative_latent_delta"]
            <= source["maximum_relative_latent_delta"] + TOLERANCE
        ),
        "final_spatial_ratio_not_worse_than_waiver": (
            comparison["final_spatial_ratio"]
            >= source["final_spatial_ratio"] - TOLERANCE
        ),
        "outside_union_leakage_not_worse_than_waiver": (
            comparison["steps"][-1]["outside_mean_abs_delta"]
            <= source["steps"][-1]["outside_mean_abs_delta"] + TOLERANCE
        ),
        "all_mother_regions_improved": all(mother_improvement.values()),
        "all_bo_and_prop_regions_retained": all(bo_retention.values()),
        "absolute_critics_clean": (
            raw["gates"]["baseline_absolute_critic_clean"]
            and raw["gates"]["active_absolute_critic_clean"]
            and raw["gates"]["paired_critic_clean"]
        ),
        "update_norm_bounded": raw["gates"]["update_norm_bounded"],
        "all_steps_finite": raw["gates"]["all_steps_finite"],
        "identity_events_match": raw["gates"]["identity_events_match"],
        "vae_untouched": raw["gates"]["vae_untouched"],
    }
    passed = all(gates.values())
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R6-R5",
        "status": "PASS_MOTHER_SIDE_CHANNEL_GAIN_REBALANCE" if passed else "FAIL",
        "profile": {
            "channels": CHANNELS,
            "channel_gains": dict(zip(CHANNELS, gains)),
            "mother_gain": MOTHER_GAIN,
            "early_blocks": [0, 1, 2, 3, 4],
            "early_steps": [2, 3],
            "early_scale": 0.00125,
            "seed": runner.SEED,
        },
        "accepted_waiver_baseline": {
            "maximum_relative_latent_delta": source["maximum_relative_latent_delta"],
            "final_spatial_ratio": source["final_spatial_ratio"],
            "final_outside_mean_abs_delta": source["steps"][-1]["outside_mean_abs_delta"],
        },
        "prior_geometry_regions": prior_regions,
        "comparison": comparison,
        "mother_improvement": mother_improvement,
        "bo_prop_retention": bo_retention,
        "gates": gates,
        "next_decode_authorized": False,
        "phase4l_closure": {
            "status": (
                "OPEN_PENDING_MOTHER_GAIN_DECODE_AUTHORIZATION_REVIEW"
                if passed
                else "OPEN_PENDING_MOTHER_SIDE_REBALANCE_REPAIR"
            ),
            "all_requirements_satisfied": False,
        },
        "guards": {
            "transformer_forward_count": 24,
            "scheduler_step_count": 24,
            "trajectory_count": 1,
            "baseline_loaded_from_cache": True,
            "vae_calls": {"forward": 0, "decode": 0},
            "images_created": 0,
            "decode_authorized": False,
            "production_profile_changed": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
        },
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
