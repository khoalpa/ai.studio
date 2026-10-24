from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ai_story.latent_discontinuity import (
    evaluate_latent_discontinuity,
    observation_from_profile,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R5_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r5-late-step-decomposition-v1/phase4lr9r7r3r5-result.json"
)
R13_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r13-neutral-scale0375-canary-v1/phase4lr9r7r3r13-result.json"
)
R14_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r14-neutral-scale025-canary-v1/phase4lr9r7r3r14-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r15-vae-precursor-critic-lock-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r15-result.json"


def observations_from_tail(tail: list[dict], boundary_path: tuple[str, ...]) -> list:
    observations = []
    for step in tail:
        boundaries = step
        for key in boundary_path:
            boundaries = boundaries[key]
        for axis, profile_key in (
            ("row", "row_boundaries"),
            ("column", "column_boundaries"),
        ):
            observations.append(
                observation_from_profile(
                    step=step["step"],
                    axis=axis,
                    profile=boundaries[profile_key],
                )
            )
    return observations


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R15 already exists; refusing to overwrite critic lock")
    r5 = json.loads(R5_RESULT.read_text(encoding="utf-8"))
    r13 = json.loads(R13_RESULT.read_text(encoding="utf-8"))
    r14 = json.loads(R14_RESULT.read_text(encoding="utf-8"))
    if r13["status"] != "AUTO_REJECT_AWAITING_MANUAL_REVIEW":
        raise RuntimeError("R13 negative fixture is not locked")
    if r14["status"] != "AUTO_REJECT_AWAITING_MANUAL_REVIEW":
        raise RuntimeError("R14 negative fixture is not locked")

    scale0 = evaluate_latent_discontinuity(
        observations_from_tail(
            r5["smoke"]["tail_steps"], ("latent_after", "boundaries")
        )
    )
    scale0375 = evaluate_latent_discontinuity(
        observations_from_tail(r13["generation"]["latent_tail_profiles"], ("boundaries",))
    )
    scale025 = evaluate_latent_discontinuity(
        observations_from_tail(r14["generation"]["latent_tail_profiles"], ("boundaries",))
    )
    lock_passed = (
        not scale0.blocked
        and scale0375.blocked
        and scale025.blocked
        and scale0375.status == "PERSISTENT_VAE_AMPLIFICATION_PRECURSOR"
        and scale025.status == "PERSISTENT_VAE_AMPLIFICATION_PRECURSOR"
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R15",
        "status": "PASS" if lock_passed else "FAIL",
        "controls": {
            "scale0_clean": asdict(scale0),
            "scale0375_negative": asdict(scale0375),
            "scale025_negative": asdict(scale025),
        },
        "thresholds": {
            "minimum_ratio": 1.8,
            "minimum_robust_z": 1.8,
            "persistence_steps": 2,
            "interior_only": True,
        },
        "analysis": {
            "negative_fixture_count": 2,
            "clean_control_count": 1,
            "conclusion": (
                "VAE_AMPLIFICATION_PRECURSOR_LOCKED"
                if lock_passed
                else "VAE_AMPLIFICATION_PRECURSOR_NOT_LOCKED"
            ),
        },
        "guards": {
            "offline_only": True,
            "gpu_used": False,
            "model_loaded": False,
            "vae_decode_performed": False,
            "image_generation_performed": False,
            "next_attempt_started": False,
            "climax_generated": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    if not lock_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
