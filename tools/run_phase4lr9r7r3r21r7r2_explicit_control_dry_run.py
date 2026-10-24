from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import torch
from PIL import Image
from run_phase4lr9r7r3r21r2_regional_attention_dry_run import (
    load_block,
    regional_forward,
)

from ai_story.explicit_spatial_control import (
    ExplicitSpatialControlResidual,
    raster_controls_to_tokens,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R1_ROOT = BASELINE_ROOT / "phase4lr9r7r3r21r7r1-negative-pose-contract-v1"
R1_RESULT = R1_ROOT / "phase4lr9r7r3r21r7r1-result.json"
CONTRACT_PATH = R1_ROOT / "explicit-pose-composition-control.json"
CONTROL_PATHS = {
    "composition": R1_ROOT / "composition-control.png",
    "pose": R1_ROOT / "pose-control.png",
    "prop": R1_ROOT / "prop-silhouette-control.png",
}
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r2-explicit-control-dry-run-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r2-result.json"
EXPECTED_CONTRACT_SHA256 = (
    "6aeae1c47d6423c92808ea4efc009bcb65fa6e47756e3562e3c69c54c1f222d5"
)
GRID = (32, 32)
HIDDEN_SIZE = 2432
SEED = 420917
ACTIVE_SCALE = 0.01
TOLERANCE = 1e-7


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_controls() -> torch.Tensor:
    channels = []
    for path in CONTROL_PATHS.values():
        with Image.open(path) as image:
            values = torch.frombuffer(bytearray(image.convert("L").tobytes()), dtype=torch.uint8)
            channels.append(values.reshape(image.height, image.width).float() / 255.0)
    return torch.stack(channels).unsqueeze(0)


def locality_metrics(
    baseline: torch.Tensor,
    active: torch.Tensor,
    mask: torch.Tensor,
) -> dict[str, float | int | bool]:
    delta = (active - baseline).abs().amax(dim=-1)
    active_mask = mask.bool()
    inside = delta[active_mask]
    outside = delta[~active_mask]
    inside_min = float(inside.min().item()) if inside.numel() else 0.0
    outside_max = float(outside.max().item()) if outside.numel() else 0.0
    return {
        "active_token_count": int(active_mask.sum().item()),
        "inside_min_abs_delta": inside_min,
        "outside_max_abs_delta": outside_max,
        "inside_effect_nonzero": inside_min > TOLERANCE,
        "outside_leakage_below_tolerance": outside_max <= TOLERANCE,
    }


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R21-R7-R2 already exists; refusing to overwrite checkpoint")
    prior = json.loads(R1_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_NEGATIVE_LOCK_AND_EXPLICIT_CONTROL_DESIGN":
        raise RuntimeError("R21-R7-R1 explicit control design is not locked")
    contract_digest = sha256(CONTRACT_PATH)
    if contract_digest != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError(f"Explicit control contract changed: {contract_digest}")

    rasters = load_controls()
    token_controls = raster_controls_to_tokens(rasters, GRID, threshold=0.25)
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    vectors = torch.randn((3, HIDDEN_SIZE), generator=generator)
    adapter = ExplicitSpatialControlResidual(vectors).eval()
    processor, attention = load_block()
    hidden = torch.randn((1, GRID[0] * GRID[1], HIDDEN_SIZE), generator=generator)
    context = torch.randn((1, 3, HIDDEN_SIZE), generator=generator)
    ip_hidden = torch.randn((1, 64, HIDDEN_SIZE), generator=generator)
    temb = torch.randn((1, 1280), generator=generator)
    zero_identity_mask = torch.zeros((1, GRID[0] * GRID[1], 1))
    with torch.inference_mode():
        block_output, block_context = regional_forward(
            processor,
            attention,
            hidden,
            context,
            ip_hidden,
            temb,
            zero_identity_mask,
            0.0,
        )
        zero = adapter(block_output, token_controls, scale=0.0)
        branches = {}
        metrics = {}
        for index, name in enumerate(CONTROL_PATHS):
            isolated = torch.zeros_like(token_controls)
            isolated[..., index] = token_controls[..., index]
            branches[name] = adapter(block_output, isolated, scale=ACTIVE_SCALE)
            metrics[name] = locality_metrics(
                block_output, branches[name], isolated[..., index]
            )
        combined = adapter(block_output, token_controls, scale=ACTIVE_SCALE)

    zero_max_error = float((zero - block_output).abs().max().item())
    combined_delta = combined - block_output
    union = token_controls.any(dim=-1)
    combined_outside_max = float(combined_delta.abs().amax(dim=-1)[~union].max().item())
    active_delta_norm = float(combined_delta.norm().item())
    baseline_norm = float(block_output.norm().item())
    relative_residual_norm = active_delta_norm / baseline_norm
    passed = (
        zero_max_error == 0.0
        and all(
            branch["inside_effect_nonzero"]
            and branch["outside_leakage_below_tolerance"]
            for branch in metrics.values()
        )
        and combined_outside_max <= TOLERANCE
        and 0.0 < relative_residual_norm < 0.01
    )
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R2",
        "status": "PASS_EXPLICIT_CONTROL_INTEGRATION_DRY_RUN" if passed else "FAIL",
        "contract_sha256": contract_digest,
        "integration": {
            "location": "POST_TRANSFORMER_BLOCK_OUTPUT_PRE_NEXT_BLOCK",
            "identity_attention_path_modified": False,
            "grid": list(GRID),
            "token_count": GRID[0] * GRID[1],
            "hidden_size": HIDDEN_SIZE,
            "control_channel_order": list(CONTROL_PATHS),
            "raster_sampling": "AREA_DOWNSAMPLE_THEN_BINARY_THRESHOLD_0.25",
            "active_scale": ACTIVE_SCALE,
            "actual_sd35_transformer_block_index": 0,
            "context_output_shape": list(block_context.shape),
        },
        "zero_residual_parity": {
            "max_abs_error": zero_max_error,
            "bitwise_equal": torch.equal(zero, block_output),
            "tolerance": 0.0,
        },
        "single_channel_locality": metrics,
        "combined_control": {
            "union_active_token_count": int(union.sum().item()),
            "outside_union_max_abs_delta": combined_outside_max,
            "relative_residual_norm": relative_residual_norm,
            "bounded_below_one_percent": relative_residual_norm < 0.01,
        },
        "conclusion": (
            "Explicit composition, pose, and prop controls preserve exact scale-zero "
            "parity and produce bounded residuals only on their assigned query tokens."
            if passed
            else "Explicit control parity, locality, or residual bound failed."
        ),
        "guards": {
            "single_block_output_contract_only": True,
            "actual_transformer_weights_loaded": True,
            "full_transformer_instantiated": False,
            "denoise_performed": False,
            "latents_created": False,
            "vae_instantiated": False,
            "image_generation_performed": False,
            "next_full_scene_attempt_authorized": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    write_json(RESULT_PATH, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
