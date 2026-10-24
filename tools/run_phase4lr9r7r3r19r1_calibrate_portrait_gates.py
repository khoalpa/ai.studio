from __future__ import annotations

import json
from pathlib import Path

import run_phase4lr9r7r3r7_vae_instrumented_canary as canary_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R19_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r19-delayed-bounded-canary-v1/phase4lr9r7r3r19-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r19r1-portrait-gate-calibration-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r19r1-result.json"
FIXTURES = {
    "r19_positive": BASELINE_ROOT
    / "phase4lr9r7r3r19-delayed-bounded-canary-v1/candidates/neutral-identity/attempt-1.png",
    "r13_negative": BASELINE_ROOT
    / "phase4lr9r7r3r13-neutral-scale0375-canary-v1/candidates/neutral-identity/attempt-1.png",
    "r14_negative": BASELINE_ROOT
    / "phase4lr9r7r3r14-neutral-scale025-canary-v1/candidates/neutral-identity/attempt-1.png",
}


def main() -> None:
    prior = json.loads(R19_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "AUTO_REJECT_AWAITING_MANUAL_REVIEW":
        raise RuntimeError("Required R19 checkpoint is not satisfied")
    if RESULT_PATH.exists():
        raise RuntimeError("R19-R1 already completed; refusing to overwrite checkpoint")
    if not all(path.is_file() for path in FIXTURES.values()):
        raise RuntimeError("A required positive or negative fixture is missing")

    assessments = {}
    original_candidate = canary_runtime.CANDIDATE
    try:
        for fixture_id, path in FIXTURES.items():
            canary_runtime.CANDIDATE = path
            assessments[fixture_id] = canary_runtime.assess_candidate()
    finally:
        canary_runtime.CANDIDATE = original_candidate

    positive_passed = assessments["r19_positive"]["status"] == "ASSESSED_PASS"
    negative_results = {
        fixture_id: assessment["status"] == "ASSESSED_FAIL"
        for fixture_id, assessment in assessments.items()
        if fixture_id.endswith("negative")
    }
    controls_passed = positive_passed and all(negative_results.values())
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R19-R1",
        "status": "PASS" if controls_passed else "FAIL_CALIBRATION_CONTROLS",
        "calibration": {
            "portrait_anatomy_minimum_expected_score": 0.24,
            "portrait_anatomy_minimum_contrast_margin": 0.015,
            "localized_anatomy_minimum_expected_score": 0.24,
            "localized_anatomy_minimum_contrast_margin": 0.0,
            "single_subject_minimum_expected_score": 0.20,
            "single_subject_minimum_contrast_margin": -0.005,
        },
        "controls": assessments,
        "control_assertions": {
            "r19_positive_passed": positive_passed,
            "r13_negative_rejected": negative_results["r13_negative"],
            "r14_negative_rejected": negative_results["r14_negative"],
        },
        "guards": {
            "image_generation_performed": False,
            "existing_fixtures_only": True,
            "climax_generated": False,
            "phase4n_opened": False,
            "production_generation_profile_changed": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    if not controls_passed:
        raise RuntimeError("Portrait gate calibration controls did not pass")


if __name__ == "__main__":
    main()
