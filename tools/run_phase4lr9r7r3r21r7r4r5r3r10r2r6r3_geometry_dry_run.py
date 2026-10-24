from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import torch

from ai_story.explicit_spatial_control import (
    ExplicitSpatialControlResidual,
    StagedExplicitControlRegistration,
    raster_controls_to_tokens,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R2_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r2-reject-geometry-lock-v1"
)
R2_RESULT = R2_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r6r2-result.json"
CONTRACT_PATH = R2_ROOT / "geometry-contract.json"
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r3-geometry-dry-run-v1"
)
CONTROL_LAYOUT_PATH = OUTPUT_ROOT / "geometry-control-layout.json"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r6r3-result.json"
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
ADAPTER_WEIGHT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter/ip-adapter.bin")
CANVAS = 512
GRID = (32, 32)
BLOCK_COUNT = 38
HIDDEN_SIZE = 2432
CHANNELS = [
    "bo_face",
    "me_face",
    "bo_hand",
    "me_hand",
    "paper_boat",
    "bo_contact",
    "me_contact",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def disk(xx: torch.Tensor, yy: torch.Tensor, x: int, y: int, radius: int) -> torch.Tensor:
    return (xx - x).square() + (yy - y).square() <= radius * radius


def build_controls() -> tuple[torch.Tensor, dict[str, Any]]:
    yy, xx = torch.meshgrid(torch.arange(CANVAS), torch.arange(CANVAS), indexing="ij")
    bo_face = (xx >= 48) & (xx < 176) & (yy >= 48) & (yy < 192)
    me_face = (xx >= 320) & (xx < 464) & (yy >= 40) & (yy < 192)
    bo_hand = disk(xx, yy, 218, 330, 30)
    me_hand = disk(xx, yy, 294, 330, 30)
    # Symmetric folded-paper silhouette: low center, two raised outer folds.
    boat = (
        (yy >= 328)
        & (yy <= 382)
        & (xx >= 214)
        & (xx <= 298)
        & ((yy - 328) * 84 >= (xx - 256).abs() * 26)
    )
    bo_contact = disk(xx, yy, 234, 340, 12)
    me_contact = disk(xx, yy, 278, 340, 12)
    masks = [bo_face, me_face, bo_hand, me_hand, boat, bo_contact, me_contact]
    raster = torch.stack(masks).float().unsqueeze(0)
    interaction_roi = (xx >= 176) & (xx < 336) & (yy >= 272) & (yy < 416)
    layout = {
        "canvas": [CANVAS, CANVAS],
        "token_grid": list(GRID),
        "channel_order": CHANNELS,
        "regions": {
            "bo_face": {"box": [48, 48, 176, 192]},
            "me_face": {"box": [320, 40, 464, 192]},
            "bo_hand": {"center": [218, 330], "radius": 30},
            "me_hand": {"center": [294, 330], "radius": 30},
            "paper_boat": {"bounds": [214, 328, 298, 382]},
            "bo_contact": {"center": [234, 340], "radius": 12},
            "me_contact": {"center": [278, 340], "radius": 12},
            "interaction_roi": {"box": [176, 272, 336, 416]},
        },
        "pixel_metrics": {
            "face_overlap_pixels": int((bo_face & me_face).sum()),
            "hand_overlap_pixels": int((bo_hand & me_hand).sum()),
            "bo_contact_hand_overlap_pixels": int((bo_contact & bo_hand).sum()),
            "me_contact_hand_overlap_pixels": int((me_contact & me_hand).sum()),
            "bo_contact_boat_overlap_pixels": int((bo_contact & boat).sum()),
            "me_contact_boat_overlap_pixels": int((me_contact & boat).sum()),
            "interaction_controls_outside_roi_pixels": int(
                ((bo_hand | me_hand | boat | bo_contact | me_contact) & ~interaction_roi).sum()
            ),
        },
    }
    return raster, layout


def registration_worker() -> dict[str, Any]:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from diffusers import SD3Transformer2DModel

    transformer = SD3Transformer2DModel.from_pretrained(
        LARGE_ROOT,
        subfolder="transformer",
        local_files_only=True,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
    )
    state = torch.load(ADAPTER_WEIGHT, map_location="cpu", weights_only=True)
    transformer._load_ip_adapter_weights(state, low_cpu_mem_usage=True)
    del state
    gc.collect()
    blocks = transformer.transformer_blocks
    before_hooks = [len(block._forward_hooks) for block in blocks]
    before_processors = [id(block.attn.processor) for block in blocks]
    before_keys = set(transformer.state_dict().keys())
    vectors = torch.randn((len(CHANNELS), HIDDEN_SIZE), generator=torch.Generator().manual_seed(420917))
    adapter = ExplicitSpatialControlResidual(vectors).half()
    registration = StagedExplicitControlRegistration(transformer, {"geometry": adapter})
    controls, _ = build_controls()
    tokens = raster_controls_to_tokens(controls, GRID, threshold=0.25).half()
    registration.configure_stage("geometry", tokens, [0.0] * BLOCK_COUNT)
    registered_hooks = [len(block._forward_hooks) for block in blocks]
    registered_processors = [id(block.attn.processor) for block in blocks]
    registered_keys = set(transformer.state_dict().keys())
    registration.unregister()
    after_hooks = [len(block._forward_hooks) for block in blocks]
    after_keys = set(transformer.state_dict().keys())
    passed = (
        len(blocks) == BLOCK_COUNT
        and sum(registered_hooks[i] - before_hooks[i] for i in range(BLOCK_COUNT)) == BLOCK_COUNT
        and registered_processors == before_processors
        and registered_keys - before_keys == {"staged_explicit_controls.geometry.channel_vectors"}
        and after_hooks == before_hooks
        and after_keys == before_keys
        and not hasattr(transformer, StagedExplicitControlRegistration.module_name)
        and not torch.cuda.is_initialized()
    )
    result = {
        "status": "PASS" if passed else "FAIL",
        "transformer_blocks": len(blocks),
        "registered_control_hooks": sum(
            registered_hooks[i] - before_hooks[i] for i in range(BLOCK_COUNT)
        ),
        "identity_processors_preserved": registered_processors == before_processors,
        "control_state_keys": sorted(registered_keys - before_keys),
        "lifecycle_restored_after_unregister": after_hooks == before_hooks and after_keys == before_keys,
        "transformer_forward_called": False,
        "cpu_only": True,
        "cuda_initialized": torch.cuda.is_initialized(),
    }
    del transformer, blocks, adapter, registration, tokens
    gc.collect()
    return result


def run_registration_worker() -> dict[str, Any]:
    environment = os.environ.copy()
    environment.update({"CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1"})
    process = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        capture_output=True,
        text=True,
        env=environment,
    )
    if process.returncode != 0:
        raise RuntimeError(f"geometry registration worker failed: {process.stderr[-4000:]}")
    lines = [line for line in process.stdout.splitlines() if line.startswith("{")]
    if not lines:
        raise RuntimeError("geometry registration worker returned no JSON")
    return json.loads(lines[-1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(registration_worker()), flush=True)
        return
    if RESULT_PATH.exists() or CONTROL_LAYOUT_PATH.exists():
        raise RuntimeError("R10-R2-R6-R3 checkpoint already exists; refusing overwrite")
    prior = json.loads(R2_RESULT.read_text(encoding="utf-8"))
    json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if prior["status"] != "PASS_MANUAL_REJECT_AND_GEOMETRY_FAILURE_LOCK":
        raise RuntimeError("R2 rejection and geometry failure lock is not intact")
    if prior["geometry_contract_sha256"] != sha256(CONTRACT_PATH):
        raise RuntimeError("geometry contract digest changed")

    controls, layout = build_controls()
    tokens = raster_controls_to_tokens(controls, GRID, threshold=0.25)
    token_counts = {
        channel: int(tokens[0, :, index].sum()) for index, channel in enumerate(CHANNELS)
    }
    pixels = layout["pixel_metrics"]
    geometry_gates = {
        "exactly_two_nonoverlapping_face_regions": (
            token_counts["bo_face"] > 0
            and token_counts["me_face"] > 0
            and pixels["face_overlap_pixels"] == 0
        ),
        "exactly_two_separate_hand_regions": (
            token_counts["bo_hand"] > 0
            and token_counts["me_hand"] > 0
            and pixels["hand_overlap_pixels"] == 0
        ),
        "single_boat_region_present": token_counts["paper_boat"] > 0,
        "bo_contact_connects_hand_and_boat": (
            pixels["bo_contact_hand_overlap_pixels"] > 0
            and pixels["bo_contact_boat_overlap_pixels"] > 0
        ),
        "me_contact_connects_hand_and_boat": (
            pixels["me_contact_hand_overlap_pixels"] > 0
            and pixels["me_contact_boat_overlap_pixels"] > 0
        ),
        "interaction_controls_contained_in_roi": (
            pixels["interaction_controls_outside_roi_pixels"] == 0
        ),
        "all_channels_survive_tokenization": all(count > 0 for count in token_counts.values()),
    }
    layout["token_counts"] = token_counts
    layout["geometry_gates"] = geometry_gates
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    CONTROL_LAYOUT_PATH.write_text(
        json.dumps(layout, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    registration = run_registration_worker()
    passed = all(geometry_gates.values()) and registration["status"] == "PASS"
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R6-R3",
        "status": "PASS_GEOMETRY_CONTROL_LAYOUT_DRY_RUN" if passed else "FAIL",
        "source_contract": str(CONTRACT_PATH.resolve()),
        "source_contract_sha256": sha256(CONTRACT_PATH),
        "control_layout_path": str(CONTROL_LAYOUT_PATH.resolve()),
        "control_layout_sha256": sha256(CONTROL_LAYOUT_PATH),
        "channel_order": CHANNELS,
        "token_counts": token_counts,
        "pixel_metrics": pixels,
        "geometry_gates": geometry_gates,
        "registration_smoke": registration,
        "next_stage_authorized": passed,
        "next_decode_authorized": False,
        "phase4l_closure": {
            "status": (
                "OPEN_PENDING_GEOMETRY_LATENT_TRAJECTORY"
                if passed
                else "OPEN_PENDING_GEOMETRY_CONTROL_DRY_RUN"
            ),
            "all_requirements_satisfied": False,
        },
        "guards": {
            "subprocess_isolation": True,
            "cpu_only": True,
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
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
