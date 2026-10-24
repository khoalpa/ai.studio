from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from typing import Any

import torch

from ai_story.explicit_spatial_control import ExplicitSpatialControlResidual

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
PRIOR_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r1r1-clean-scale-revalidation-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r1r1-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r10r1r2-schedule-profile-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r1r2-result.json"
EARLY_SCALES = [0.00125, 0.0025]
MIDDLE_SCALES = [0.000625, 0.0025]


def metrics(payload: dict[str, Any], step: int, scale: float) -> dict[str, float]:
    direct = payload["results"][str(step)]["variants"][f"bf16_direct_scale_{scale}"]
    active = payload["results"][str(step)]["variants"][f"error_feedback_scale_{scale}"]
    return {
        "direct_locality": direct["minimum_localization_ratio"],
        "active_locality": active["minimum_localization_ratio"],
        "locality_delta": active["minimum_localization_ratio"]
        - direct["minimum_localization_ratio"],
        "maximum_relative_global_delta": active["maximum_relative_global_delta"],
        "final_output_mean_abs_delta": active["final_output_mean_abs_delta"],
    }


def zero_control_parity() -> dict[str, Any]:
    generator = torch.Generator(device="cpu").manual_seed(420917)
    hidden = torch.randn((1, 16, 8), generator=generator).to(torch.bfloat16)
    controls = torch.ones((1, 16, 1))
    adapter = ExplicitSpatialControlResidual(
        torch.randn((1, 8), generator=generator), error_feedback=True
    )
    adapter(hidden, controls, scale=0.001)
    pending_before = adapter.pending_error.detach().clone()
    output = adapter(hidden, controls, scale=0.0)
    pending_after = adapter.pending_error
    return {
        "bitwise_equal": torch.equal(output, hidden),
        "maximum_absolute_delta": float((output.float() - hidden.float()).abs().max()),
        "pending_error_unchanged": pending_after is not None
        and torch.equal(pending_before, pending_after),
        "terminal_scale": 0.0,
    }


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R10-R1-R2 checkpoint already exists; refusing to overwrite")
    prior = json.loads(PRIOR_RESULT.read_text(encoding="utf-8"))
    if (
        prior["status"] != "PASS_CLEAN_SCALE_ERROR_FEEDBACK_REVALIDATION"
        or prior["phase4l_closure"]["status"] != "OPEN_PENDING_RESIDUAL_PROFILE_REDESIGN"
        or prior["error_feedback_decision"]["trajectory_authorized"] is not False
    ):
        raise RuntimeError("clean-scale checkpoint changed")

    terminal = zero_control_parity()
    profiles: dict[str, Any] = {}
    for early_scale, middle_scale in product(EARLY_SCALES, MIDDLE_SCALES):
        early = metrics(prior, 2, early_scale)
        middle_bo = metrics(prior, 8, middle_scale)
        middle_mother = metrics(prior, 15, middle_scale)
        gates = {
            "early_locality_non_degrading": early["locality_delta"] >= 0.0,
            "middle_bo_locality_non_degrading": middle_bo["locality_delta"] >= 0.0,
            "middle_mother_locality_non_degrading": middle_mother["locality_delta"] >= 0.0,
            "active_global_delta_bounded": max(
                early["maximum_relative_global_delta"],
                middle_bo["maximum_relative_global_delta"],
                middle_mother["maximum_relative_global_delta"],
            )
            < 0.01,
            "terminal_zero_control_bitwise_parity": terminal["bitwise_equal"],
            "terminal_zero_control_state_unchanged": terminal["pending_error_unchanged"],
        }
        profile_id = f"early_{early_scale}_middle_{middle_scale}"
        profiles[profile_id] = {
            "early_scale": early_scale,
            "middle_scale": middle_scale,
            "terminal_scale": 0.0,
            "measurements": {
                "step_2_early": early,
                "step_8_middle_bo": middle_bo,
                "step_15_middle_mother": middle_mother,
            },
            "gates": gates,
            "eligible": all(gates.values()),
        }

    eligible = [name for name, profile in profiles.items() if profile["eligible"]]
    selected = (
        min(
            eligible,
            key=lambda name: (
                profiles[name]["early_scale"] + profiles[name]["middle_scale"],
                profiles[name]["middle_scale"],
                profiles[name]["early_scale"],
            ),
        )
        if eligible
        else None
    )
    passed = selected is not None
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R1-R2",
        "status": "PASS_SCHEDULE_ALIGNED_ASYMMETRIC_PROFILE" if passed else "FAIL",
        "source_checkpoint": str(PRIOR_RESULT.resolve()),
        "profiles": profiles,
        "eligible_profiles": eligible,
        "selected_profile": selected,
        "selected_profile_values": profiles[selected] if selected else None,
        "terminal_zero_control_parity": terminal,
        "selection_policy": "minimum early+middle scale, then minimum middle scale",
        "trajectory_authorized": passed,
        "phase4l_closure": {
            "status": (
                "OPEN_PENDING_SCHEDULE_ALIGNED_TRAJECTORY"
                if passed
                else "OPEN_PENDING_RESIDUAL_PROFILE_REDESIGN"
            ),
            "all_requirements_satisfied": False,
        },
        "guards": {
            "transformer_forward_count": 0,
            "scheduler_step_count": 0,
            "trajectory_count": 0,
            "reused_locked_measurements": True,
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
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
