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
R6_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r6-critic-regression-lock-v1/phase4lr9r7r3r6-result.json"
)
R5_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r5-late-step-decomposition-v1/phase4lr9r7r3r5-result.json"
)
R7_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r7-vae-instrumented-canary-v1/phase4lr9r7r3r7-result.json"
)
R8_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r8-vae-decoder-activation-forensic-v1/phase4lr9r7r3r8-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r9-static-seam-regression-lock-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r9-result.json"
CONFIG = LatentDiscontinuityConfig()


def trajectory_observations(
    steps: list[dict], *, component: str | None = None
) -> list[BoundaryObservation]:
    observations = []
    for step in steps:
        boundaries = step[component]["boundaries"] if component else step["boundaries"]
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries")):
            observations.append(
                observation_from_profile(
                    step=step["step"], axis=axis, profile=boundaries[key]
                )
            )
    return observations


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R9 already exists; refusing to overwrite regression lock")
    r6 = json.loads(R6_RESULT.read_text(encoding="utf-8"))
    r5 = json.loads(R5_RESULT.read_text(encoding="utf-8"))
    r7 = json.loads(R7_RESULT.read_text(encoding="utf-8"))
    r8 = json.loads(R8_RESULT.read_text(encoding="utf-8"))
    if r6["status"] != "PASS" or r8["status"] != "PASS":
        raise RuntimeError("R6 and R8 must pass before static-seam lock")

    r5_decision = evaluate_latent_discontinuity(
        trajectory_observations(r5["smoke"]["tail_steps"], component="latent_after"),
        CONFIG,
    )
    r7_decision = evaluate_latent_discontinuity(
        trajectory_observations(r7["generation"]["latent_tail_profiles"]),
        CONFIG,
    )
    r8_input = next(
        item
        for item in r8["analysis"]["interior_layer_sequence"]
        if item["name"] == "decoder_input"
    )
    r8_target = r8["analysis"]["target_neighborhood_trace"][0]

    edge_fixture = [
        BoundaryObservation(22, "row", 1.4, 0.9, 0.02, 0, 64),
        BoundaryObservation(23, "row", 1.39, 0.9, 0.02, 1, 64),
    ]
    edge_decision = evaluate_latent_discontinuity(edge_fixture, CONFIG)
    static_fixture = [
        BoundaryObservation(22, "row", 1.4, 0.9, 0.02, 31, 64),
        BoundaryObservation(23, "row", 1.39, 0.9, 0.02, 31, 64),
    ]
    static_decision = evaluate_latent_discontinuity(static_fixture, CONFIG)

    r8_corresponds_to_r7 = (
        r8["smoke"]["in_memory_png_sha256"] == r7["candidate_sha256"]
        and r8["smoke"]["latent_critic"]["blocked"] is False
        and r8_input["robust_z"] >= CONFIG.minimum_robust_z
        and r8_target["normalized_position"] > CONFIG.interior_margin_fraction
        and r8_target["normalized_position"]
        < 1.0 - CONFIG.interior_margin_fraction
    )
    passed = (
        r5_decision.blocked is False
        and r7_decision.blocked is True
        and r7_decision.status == "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY"
        and r7_decision.axis == "row"
        and edge_decision.blocked is False
        and static_decision.blocked is True
        and r8_corresponds_to_r7
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R9",
        "status": "PASS" if passed else "FAIL",
        "critic_config": asdict(CONFIG),
        "regressions": {
            "r5_denominator_collapse_negative": asdict(r5_decision),
            "r7_static_latent_seam_positive": asdict(r7_decision),
            "r8_decoder_input_evidence": {
                "interior_signal": r8_input,
                "target_signal": r8_target,
                "corresponds_to_r7": r8_corresponds_to_r7,
            },
            "synthetic_edge_negative": asdict(edge_decision),
            "synthetic_static_interior_positive": asdict(static_decision),
        },
        "guards": {
            "r5_remains_accepted": r5_decision.blocked is False,
            "r7_now_blocked_before_decode": r7_decision.blocked is True,
            "edge_exclusion_locked": edge_decision.blocked is False,
            "static_growth_not_required": static_decision.absolute_growth is None,
            "gpu_used": False,
            "model_loaded": False,
            "vae_decode_performed": False,
            "image_generation_performed": False,
            "next_attempt_started": False,
            "climax_generated": False,
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
