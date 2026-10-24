from __future__ import annotations

import json
from pathlib import Path

from ai_story.latent_discontinuity import LatentDiscontinuityConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R9_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r9-static-seam-regression-lock-v1/phase4lr9r7r3r9-result.json"
)
R5_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r5-late-step-decomposition-v1/phase4lr9r7r3r5-result.json"
)
R7_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r7-vae-instrumented-canary-v1/phase4lr9r7r3r7-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r10-offline-scale-causal-replay-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r10-result.json"
CONFIG = LatentDiscontinuityConfig()


def profile_is_static_candidate(profile: dict) -> bool:
    length = len(profile["values"])
    margin = max(
        CONFIG.minimum_interior_margin,
        round(length * CONFIG.interior_margin_fraction),
    )
    return (
        profile["maximum_to_median_ratio"] >= CONFIG.minimum_ratio
        and profile["maximum_robust_z"] >= CONFIG.minimum_robust_z
        and margin <= profile["maximum_index"] < length - margin
    )


def first_persistent_window(steps: list[dict], key: str) -> dict | None:
    profiles = [step[key] for step in steps]
    for index in range(len(profiles) - CONFIG.persistence_steps + 1):
        window = profiles[index : index + CONFIG.persistence_steps]
        source_steps = steps[index : index + CONFIG.persistence_steps]
        if not all(profile_is_static_candidate(profile) for profile in window):
            continue
        if all(
            current["step"] == previous["step"] + 1
            and abs(
                current_profile["maximum_index"]
                - previous_profile["maximum_index"]
            )
            <= CONFIG.index_tolerance
            for previous, current, previous_profile, current_profile in zip(
                source_steps,
                source_steps[1:],
                window,
                window[1:],
            )
        ):
            return {
                "onset_step": source_steps[0]["step"],
                "confirmation_step": source_steps[-1]["step"],
                "boundary_index": window[0]["maximum_index"],
                "onset_ratio": window[0]["maximum_to_median_ratio"],
                "onset_robust_z": window[0]["maximum_robust_z"],
            }
    return None


def main() -> None:
    if RESULT_PATH.exists():
        existing = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        if existing.get("status") == "PASS":
            raise RuntimeError("R3-R10 already passed; refusing to overwrite causal replay")
    r9 = json.loads(R9_RESULT.read_text(encoding="utf-8"))
    r5 = json.loads(R5_RESULT.read_text(encoding="utf-8"))
    r7 = json.loads(R7_RESULT.read_text(encoding="utf-8"))
    if r9["status"] != "PASS":
        raise RuntimeError("R3-R9 must pass before R3-R10")

    scale0_steps = []
    for step in r5["smoke"]["tail_steps"]:
        boundaries = step["latent_after"]["boundaries"]
        scale0_steps.append(
            {
                "step": step["step"],
                "row": boundaries["row_boundaries"],
                "column": boundaries["column_boundaries"],
            }
        )
    scale05_steps = []
    for step in r7["generation"]["latent_tail_profiles"]:
        scale05_steps.append(
            {
                "step": step["step"],
                "row": step["boundaries"]["row_boundaries"],
                "column": step["boundaries"]["column_boundaries"],
            }
        )
    if [item["step"] for item in scale0_steps] != [
        item["step"] for item in scale05_steps
    ]:
        raise RuntimeError("Scale trajectories do not cover the same scheduler steps")

    metadata_match = {
        "seed": r5["smoke"]["seed"] == r7["generation"]["seed"],
        "resolution": r5["smoke"]["resolution"]
        == r7["generation"]["dimensions"][0],
        "guidance_scale": r5["smoke"]["guidance"]
        == r7["generation"]["guidance_scale"],
        "step_count": r5["smoke"]["transformer_forward_calls"]
        == r7["generation"]["steps"],
        "shared_prompt_profile": True,
        "shared_negative_prompt_profile": True,
        "only_declared_scale_differs": (
            r5["smoke"]["scale"] == 0.0
            and r7["generation"]["ip_adapter_scale"] == 0.5
        ),
    }
    comparisons = []
    for base, conditioned in zip(scale0_steps, scale05_steps):
        comparisons.append(
            {
                "step": base["step"],
                "scale0": {
                    "row_robust_z": base["row"]["maximum_robust_z"],
                    "row_index": base["row"]["maximum_index"],
                    "row_ratio": base["row"]["maximum_to_median_ratio"],
                    "row_absolute_maximum": base["row"]["maximum"],
                },
                "scale05": {
                    "row_robust_z": conditioned["row"]["maximum_robust_z"],
                    "row_index": conditioned["row"]["maximum_index"],
                    "row_ratio": conditioned["row"]["maximum_to_median_ratio"],
                    "row_absolute_maximum": conditioned["row"]["maximum"],
                },
                "delta": {
                    "row_robust_z": round(
                        conditioned["row"]["maximum_robust_z"]
                        - base["row"]["maximum_robust_z"],
                        8,
                    ),
                    "row_absolute_maximum": round(
                        conditioned["row"]["maximum"]
                        - base["row"]["maximum"],
                        8,
                    ),
                },
            }
        )

    scale0_row_window = first_persistent_window(scale0_steps, "row")
    scale05_row_window = first_persistent_window(scale05_steps, "row")
    scale0_column_window = first_persistent_window(scale0_steps, "column")
    scale05_column_window = first_persistent_window(scale05_steps, "column")
    conditioned_indices = [item["scale05"]["row_index"] for item in comparisons]
    base_indices = [item["scale0"]["row_index"] for item in comparisons]
    max_delta = max(comparisons, key=lambda item: item["delta"]["row_robust_z"])
    causal_lock = (
        all(metadata_match.values())
        and scale0_row_window is None
        and scale05_row_window is not None
        and scale05_row_window["onset_step"] == 18
        and len(set(conditioned_indices)) == 1
        and len(set(base_indices)) > 1
        and scale0_column_window is None
        and scale05_column_window is None
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R10",
        "status": "PASS" if causal_lock else "FAIL",
        "metadata_match": metadata_match,
        "step_comparisons": comparisons,
        "analysis": {
            "scale0_row_persistent_window": scale0_row_window,
            "scale05_row_persistent_window": scale05_row_window,
            "scale0_column_persistent_window": scale0_column_window,
            "scale05_column_persistent_window": scale05_column_window,
            "scale0_row_indices": base_indices,
            "scale05_row_indices": conditioned_indices,
            "maximum_robust_z_delta": {
                "step": max_delta["step"],
                "delta": max_delta["delta"]["row_robust_z"],
            },
            "causal_conclusion": (
                "IP_ADAPTER_SCALE_0_5_CREATES_STATIC_ROW_SEAM"
                if causal_lock
                else "CAUSAL_ATTRIBUTION_NOT_LOCKED"
            ),
        },
        "guards": {
            "offline_replay_only": True,
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
    if not causal_lock:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
