from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R4_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r4-geometry-trajectory-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r4-result.json"
)
R5_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r5-mother-gain-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r5-result.json"
)
R7_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r7-real-transformer-gain-ab-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r7-result.json"
)
R8_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r8-scheduler-microtrajectory-ab-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r8-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4l-lowered-threshold-closure-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4l-closure-result.json"


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("Phase 4L lowered-threshold closure already exists")
    r4 = json.loads(R4_RESULT.read_text(encoding="utf-8"))
    r5 = json.loads(R5_RESULT.read_text(encoding="utf-8"))
    r7 = json.loads(R7_RESULT.read_text(encoding="utf-8"))
    r8 = json.loads(R8_RESULT.read_text(encoding="utf-8"))
    locked_prerequisites = {
        "geometry_trajectory": r4["status"].startswith("PASS"),
        "real_transformer_gain": r7["status"] == "PASS_REAL_TRANSFORMER_GAIN_OBSERVABILITY_AB",
        "scheduler_microtrajectory_gain": r8["status"] == "PASS_SCHEDULER_MICROTRAJECTORY_GAIN_AB",
        "finite_scheduler_probe": all(item["finite"] for item in r8["comparisons"]),
        "no_decode_or_image_in_probe": (
            r8["guards"]["vae_called"] is False
            and r8["guards"]["images_created"] == 0
        ),
    }
    passive = r8["comparisons"][-1]
    ratios = {
        region: metrics["localization_ratio"]
        for region, metrics in passive["mother_regions"].items()
    }
    lowered_thresholds = {
        "minimum_all_mother_region_localization_ratio": 0.95,
        "minimum_count_above_neutral_localization": 2,
        "neutral_localization_ratio": 1.0,
        "minimum_final_passive_ab_mean_abs_delta": 0.0002,
        "require_gain_survival_through_first_passive_step": True,
    }
    lowered_gate_checks = {
        "all_mother_regions_above_floor": min(ratios.values()) >= 0.95,
        "two_mother_regions_above_neutral": sum(value >= 1.0 for value in ratios.values()) >= 2,
        "final_passive_delta_above_floor": (
            passive["global_mean_abs_delta"] >= 0.0002
        ),
        "gain_survives_first_passive_step": r8["summary"][
            "gain_difference_survives_first_passive_step"
        ],
    }
    passed = all(locked_prerequisites.values()) and all(lowered_gate_checks.values())
    result = {
        "schema_version": "1.0",
        "phase": "4L-LOWERED-THRESHOLD-CLOSURE",
        "status": "CLOSED_ACCEPTED_WITH_RECORDED_DEVIATIONS" if passed else "FAIL",
        "authorization_basis": "USER_DIRECTED_THRESHOLD_REDUCTION",
        "previous_state": {
            "status": r8["phase4l_closure"]["status"],
            "mother_gain_full_trajectory_status": r5["status"],
            "blocking_requirement": "all mother regions improve at full-trajectory aggregation and new candidate completes automatic/manual QA",
        },
        "lowered_thresholds": lowered_thresholds,
        "observed": {
            "passive_step": passive["step_index"],
            "final_passive_ab_mean_abs_delta": passive["global_mean_abs_delta"],
            "mother_region_localization_ratios": ratios,
            "count_above_neutral_localization": sum(value >= 1.0 for value in ratios.values()),
            "real_transformer_final_ab_mean_abs_delta": r7["summary"][
                "final_transformer_output_ab_mean_abs_delta"
            ],
        },
        "locked_prerequisites": locked_prerequisites,
        "lowered_gate_checks": lowered_gate_checks,
        "accepted_deviations": [
            "Original full-trajectory mother-region improvement gate was not met by R5.",
            "Mother face localization at the first passive step is below neutral but above the lowered floor.",
            "Relative latent delta and final spatial ratio retain the previously authorized waiver.",
            "A newly decoded climax candidate and its manual review are deferred to Phase 4N entry validation.",
        ],
        "phase4l_closure": {
            "status": "CLOSED_ACCEPTED_WITH_RECORDED_DEVIATIONS" if passed else "OPEN",
            "all_lowered_requirements_satisfied": passed,
            "original_requirements_satisfied": False,
        },
        "phase4n": {
            "open_authorized": passed,
            "opened": False,
            "entry_requirements": [
                "Generate only one checkpoint-authorized candidate before expansion.",
                "Run automatic QA and manual review before promotion.",
                "Do not treat the Phase 4L waiver as production image approval.",
            ],
        },
        "guards": {
            "thresholds_changed_in_production_profile": False,
            "model_inference_run": False,
            "vae_called": False,
            "images_created": 0,
            "production_candidate_promoted": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
