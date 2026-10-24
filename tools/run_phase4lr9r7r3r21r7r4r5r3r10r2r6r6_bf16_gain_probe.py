from __future__ import annotations

import json

import run_phase4lr9r7r3r21r7r4r5r3r6_structural_trajectory as runner
import torch
from run_phase4lr9r7r3r21r7r4r5r3r10r2r6r3_geometry_dry_run import (
    CHANNELS,
    GRID,
    HIDDEN_SIZE,
    build_controls,
)

from ai_story.explicit_spatial_control import (
    ExplicitSpatialControlResidual,
    raster_controls_to_tokens,
)

BASELINE_ROOT = runner.BASELINE_ROOT
R5_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r5-mother-gain-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r5-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r6-bf16-gain-probe-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r6r6-result.json"
GAINS = [1.0, 1.5, 2.0, 4.0]
MOTHER_CHANNELS = {"me_face", "me_hand", "me_contact"}
SCALE = 0.00125
FORWARDS = 8
SEED = 420917


def run_mode(
    hidden: torch.Tensor,
    controls: torch.Tensor,
    vectors: torch.Tensor,
    *,
    carry_error_feedback: bool,
) -> dict[str, object]:
    profiles: dict[str, object] = {}
    baseline_output: torch.Tensor | None = None
    for gain in GAINS:
        weighted = controls.float().clone()
        for index, channel in enumerate(CHANNELS):
            if channel in MOTHER_CHANNELS:
                weighted[..., index] *= gain
        adapter = ExplicitSpatialControlResidual(
            vectors,
            accumulate_in_fp32=True,
            error_feedback=True,
        ).to(torch.bfloat16)
        outputs = []
        target = torch.matmul(weighted.float(), adapter.channel_vectors.float()) * SCALE
        target_mean_abs = float(target.abs().mean())
        target_norm = float(target.norm())
        for _ in range(FORWARDS):
            if not carry_error_feedback:
                adapter.reset_error_feedback()
            outputs.append(adapter(hidden, weighted, scale=SCALE).detach().clone())
        observed = [(output.float() - hidden.float()) for output in outputs]
        observed_mean_abs = [float(delta.abs().mean()) for delta in observed]
        observed_norms = [float(delta.norm()) for delta in observed]
        unique_output_count = len({output.view(torch.uint16).numpy().tobytes() for output in outputs})
        profile = {
            "gain": gain,
            "target_mean_abs": target_mean_abs,
            "target_norm": target_norm,
            "observed_mean_abs_by_forward": observed_mean_abs,
            "observed_norm_by_forward": observed_norms,
            "unique_output_count": unique_output_count,
            "pending_error_mean_abs": (
                float(adapter.pending_error.abs().mean())
                if adapter.pending_error is not None
                else 0.0
            ),
        }
        if baseline_output is None:
            baseline_output = outputs[0]
            profile["first_output_differs_from_gain_1"] = False
            profile["first_output_max_abs_delta_from_gain_1"] = 0.0
        else:
            difference = outputs[0].float() - baseline_output.float()
            profile["first_output_differs_from_gain_1"] = not torch.equal(
                outputs[0], baseline_output
            )
            profile["first_output_max_abs_delta_from_gain_1"] = float(
                difference.abs().max()
            )
        profiles[str(gain)] = profile
    return {
        "carry_error_feedback": carry_error_feedback,
        "forwards_per_gain": FORWARDS,
        "profiles": profiles,
    }


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R10-R2-R6-R6 checkpoint already exists; refusing overwrite")
    prior = json.loads(R5_RESULT.read_text(encoding="utf-8"))
    if prior["status"] != "FAIL":
        raise RuntimeError("R5 ineffective gain checkpoint must remain FAIL")
    if prior["phase4l_closure"]["status"] != "OPEN_PENDING_MOTHER_SIDE_REBALANCE_REPAIR":
        raise RuntimeError("unexpected R5 Phase 4L closure state")

    raster, _ = build_controls()
    controls = raster_controls_to_tokens(raster, GRID, threshold=0.25)
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    vectors = torch.randn((len(CHANNELS), HIDDEN_SIZE), generator=generator)
    hidden = torch.randn(
        (1, GRID[0] * GRID[1], HIDDEN_SIZE), generator=generator
    ).to(torch.bfloat16)
    reset = run_mode(hidden, controls, vectors, carry_error_feedback=False)
    carry = run_mode(hidden, controls, vectors, carry_error_feedback=True)

    reset_profiles = reset["profiles"]
    carry_profiles = carry["profiles"]
    first_reset_observable = next(
        (
            gain
            for gain in GAINS[1:]
            if reset_profiles[str(gain)]["first_output_differs_from_gain_1"]
        ),
        None,
    )
    first_carry_observable = next(
        (
            gain
            for gain in GAINS
            if carry_profiles[str(gain)]["unique_output_count"] > 1
        ),
        None,
    )
    finite = all(
        torch.isfinite(torch.tensor(profile["observed_norm_by_forward"])).all().item()
        for mode in (reset, carry)
        for profile in mode["profiles"].values()
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R6-R6",
        "status": "PASS_BF16_CHANNEL_GAIN_OBSERVABILITY_FORENSIC" if finite else "FAIL",
        "configuration": {
            "seed": SEED,
            "dtype": "torch.bfloat16",
            "grid": list(GRID),
            "hidden_size": HIDDEN_SIZE,
            "scale": SCALE,
            "gains": GAINS,
            "mother_channels": sorted(MOTHER_CHANNELS),
            "forwards_per_gain": FORWARDS,
        },
        "reset_each_forward": reset,
        "carry_across_forwards": carry,
        "conclusion": {
            "first_reset_gain_observable_against_gain_1": first_reset_observable,
            "first_gain_with_carry_output_evolution": first_carry_observable,
            "all_observed_values_finite": finite,
            "gain_1_5_observable_with_reset": reset_profiles["1.5"][
                "first_output_differs_from_gain_1"
            ],
            "carry_changes_outputs_at_gain_1_5": carry_profiles["1.5"][
                "unique_output_count"
            ]
            > 1,
        },
        "next_decode_authorized": False,
        "phase4l_closure": {
            "status": "OPEN_PENDING_MOTHER_RESIDUAL_WRITE_POLICY",
            "all_requirements_satisfied": False,
        },
        "guards": {
            "cpu_only": True,
            "transformer_instantiated": False,
            "transformer_forward_called": False,
            "denoise_runs": 0,
            "latents_created": 0,
            "vae_instantiated": False,
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
    if not finite:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
