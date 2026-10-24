from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ai_story.latent_discontinuity import (
    BoundaryObservation,
    LatentDiscontinuityConfig,
    evaluate_latent_discontinuity,
    observation_from_profile,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r6-critic-regression-lock-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r6-result.json"
CHECKPOINTS = {
    "R2": BASELINE_ROOT
    / "phase4lr9r7r3r2-latent-resolution-smoke-v1/phase4lr9r7r3r2-result.json",
    "R3": BASELINE_ROOT
    / "phase4lr9r7r3r3-latent-trajectory-ab-v1/phase4lr9r7r3r3-result.json",
    "R4": BASELINE_ROOT
    / "phase4lr9r7r3r4-late-tail-isolation-v1/phase4lr9r7r3r4-result.json",
    "R5": BASELINE_ROOT
    / "phase4lr9r7r3r5-late-step-decomposition-v1/phase4lr9r7r3r5-result.json",
}
CONFIG = LatentDiscontinuityConfig()


def r5_observations(payload: dict) -> list[BoundaryObservation]:
    observations = []
    for step in payload["smoke"]["tail_steps"]:
        boundaries = step["latent_after"]["boundaries"]
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries")):
            observations.append(
                observation_from_profile(
                    step=step["step"], axis=axis, profile=boundaries[key]
                )
            )
    return observations


def synthetic_positive(axis: str, amplitude: float) -> list[BoundaryObservation]:
    return [
        BoundaryObservation(0, axis, 1.0, 0.96, 0.02, 12),
        BoundaryObservation(1, axis, 1.0 + amplitude, 0.96, 0.02, 31),
        BoundaryObservation(2, axis, 1.0 + amplitude * 0.99, 0.96, 0.02, 31),
    ]


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R6 already exists; refusing to overwrite regression lock")
    payloads = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in CHECKPOINTS.items()
    }
    replay = []
    for name in ("R2", "R3", "R4"):
        decision = evaluate_latent_discontinuity([], CONFIG)
        replay.append(
            {
                "checkpoint": name,
                "source_status": payloads[name]["status"],
                "critic_status": decision.status,
                "blocked": decision.blocked,
                "authoritative": False,
                "reason": "legacy checkpoint lacks absolute boundary profiles and MAD",
            }
        )
    r5_decision = evaluate_latent_discontinuity(
        r5_observations(payloads["R5"]), CONFIG
    )
    replay.append(
        {
            "checkpoint": "R5",
            "source_status": payloads["R5"]["status"],
            "critic_status": r5_decision.status,
            "blocked": r5_decision.blocked,
            "authoritative": True,
            "expected": "negative_control_must_not_block",
        }
    )

    positives = []
    for axis in ("row", "column"):
        for amplitude in (0.25, 0.3, 0.5):
            decision = evaluate_latent_discontinuity(
                synthetic_positive(axis, amplitude), CONFIG
            )
            positives.append(
                {
                    "axis": axis,
                    "amplitude": amplitude,
                    "blocked": decision.blocked,
                    "status": decision.status,
                    "onset_step": decision.onset_step,
                    "boundary_index": decision.boundary_index,
                }
            )
    transient = synthetic_positive("row", 0.3)
    transient[-1] = BoundaryObservation(2, "row", 1.0, 0.96, 0.02, 31)
    transient_decision = evaluate_latent_discontinuity(transient, CONFIG)
    moving = synthetic_positive("column", 0.3)
    moving[-1] = BoundaryObservation(2, "column", 1.29, 0.96, 0.02, 47)
    moving_decision = evaluate_latent_discontinuity(moving, CONFIG)

    passed = (
        r5_decision.blocked is False
        and all(item["blocked"] for item in positives)
        and transient_decision.blocked is False
        and moving_decision.blocked is False
        and all(item["blocked"] is False for item in replay[:3])
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R6",
        "status": "PASS" if passed else "FAIL",
        "critic_config": asdict(CONFIG),
        "checkpoint_replay": replay,
        "positive_controls": positives,
        "negative_controls": {
            "r5_denominator_collapse": asdict(r5_decision),
            "transient_spike": asdict(transient_decision),
            "moving_peak": asdict(moving_decision),
        },
        "guards": {
            "ratio_alone_cannot_block": True,
            "absolute_growth_required": True,
            "robust_z_required": True,
            "persistent_location_required": True,
            "legacy_summary_is_non_authoritative": True,
            "gpu_used": False,
            "model_loaded": False,
            "vae_decode_performed": False,
            "image_generation_performed": False,
            "next_neutral_attempt_authorized": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
