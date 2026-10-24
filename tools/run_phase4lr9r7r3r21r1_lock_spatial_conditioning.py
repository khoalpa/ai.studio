from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R21_ROOT = BASELINE_ROOT / "phase4lr9r7r3r21-time-multiplexed-climax-v1"
R21_RESULT = R21_ROOT / "phase4lr9r7r3r21-result.json"
R21_ASSESSMENT = R21_ROOT / "candidates/climax/attempt-1-assessment.json"
NEGATIVE_FIXTURE = R21_ROOT / "candidates/climax/attempt-1.png"
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r1-negative-spatial-conditioning-lock-v1"
)
EXPECTED_NEGATIVE_SHA256 = (
    "ef78fd36781dfa3ffb2f32874da246564097ceb90c0e6ef66c0aa3da2e2bd1d6"
)
EXPECTED_FAILED_GATES = {
    "hand_anatomy_gate",
    "hand_prop_contact_gate",
    "paper_boat_shape_scale_gate",
    "two_visible_faces_cast_gate",
    "exactly_two_interaction_hands_gate",
}
CANVAS_SIZE = (512, 512)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def pixels(box: list[float]) -> list[int]:
    width, height = CANVAS_SIZE
    return [
        round(box[0] * width),
        round(box[1] * height),
        round(box[2] * width),
        round(box[3] * height),
    ]


def area(box: list[float]) -> float:
    return (box[2] - box[0]) * (box[3] - box[1])


def intersection_area(left: list[float], right: list[float]) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    return width * height


def contains(outer: list[float], inner: list[float]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def layout_contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "canvas": {"width": 512, "height": 512, "aspect_ratio": "1:1"},
        "safe_frame": [0.06, 0.05, 0.94, 0.95],
        "regions": {
            "bo_identity": {
                "box": [0.06, 0.08, 0.47, 0.91],
                "face_box": [0.12, 0.12, 0.38, 0.40],
                "side": "left",
                "identity": "BO",
            },
            "mother_identity": {
                "box": [0.53, 0.08, 0.94, 0.91],
                "face_box": [0.62, 0.11, 0.88, 0.39],
                "side": "right",
                "identity": "ME",
            },
            "interaction": {
                "box": [0.37, 0.52, 0.63, 0.74],
                "bo_hand_box": [0.385, 0.555, 0.475, 0.695],
                "mother_hand_box": [0.525, 0.555, 0.615, 0.695],
                "boat_box": [0.465, 0.605, 0.535, 0.665],
                "bo_contact_point": [0.472, 0.635],
                "mother_contact_point": [0.528, 0.635],
                "required_hand_count": 2,
                "required_prop_count": 1,
            },
        },
        "conditioning": {
            "identity_mode": "REGIONAL_TIME_MULTIPLEXED_BO_ME",
            "temporal_schedule": [
                {"effective_step": 0, "scale": 0.0},
                {"effective_step": 8, "scale": 0.25, "identity": "BO"},
                {"effective_step": 12, "scale": 0.25, "identity": "ME"},
                {"effective_step": 16, "scale": 0.0},
            ],
            "spatial_policy": {
                "bo_tokens_attend_only_to": "bo_identity",
                "mother_tokens_attend_only_to": "mother_identity",
                "identity_mask_overlap_allowed": False,
                "interaction_roi_receives_identity_tokens": False,
                "interaction_roi_control": "POSE_AND_GEOMETRY_ONLY",
            },
        },
        "hard_constraints": {
            "both_faces_fully_inside_safe_frame": True,
            "identity_regions_non_overlapping": True,
            "exactly_two_interaction_hands": True,
            "hand_regions_non_overlapping": True,
            "boat_inside_interaction_roi": True,
            "boat_area_max_fraction_of_interaction_roi": 0.08,
            "contact_points_on_opposite_boat_edges": True,
            "no_third_person_or_third_hand_region": True,
        },
    }


def validate_layout(layout: dict[str, Any]) -> dict[str, bool]:
    regions = layout["regions"]
    bo = regions["bo_identity"]
    mother = regions["mother_identity"]
    interaction = regions["interaction"]
    safe = layout["safe_frame"]
    boat_fraction = area(interaction["boat_box"]) / area(interaction["box"])
    return {
        "bo_face_inside_safe_frame": contains(safe, bo["face_box"]),
        "mother_face_inside_safe_frame": contains(safe, mother["face_box"]),
        "identity_regions_non_overlapping": (
            intersection_area(bo["box"], mother["box"]) == 0.0
        ),
        "hand_regions_non_overlapping": (
            intersection_area(
                interaction["bo_hand_box"], interaction["mother_hand_box"]
            )
            == 0.0
        ),
        "bo_hand_inside_interaction": contains(
            interaction["box"], interaction["bo_hand_box"]
        ),
        "mother_hand_inside_interaction": contains(
            interaction["box"], interaction["mother_hand_box"]
        ),
        "boat_inside_interaction": contains(
            interaction["box"], interaction["boat_box"]
        ),
        "boat_scale_bounded": boat_fraction <= 0.08,
        "opposite_contact_order": (
            interaction["bo_contact_point"][0]
            < interaction["mother_contact_point"][0]
        ),
    }


def save_mask(path: Path, boxes: list[list[float]]) -> None:
    image = Image.new("L", CANVAS_SIZE, 0)
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle(pixels(box), fill=255)
    image.save(path, format="PNG", optimize=True)


def save_preview(path: Path, layout: dict[str, Any]) -> None:
    image = Image.new("RGB", CANVAS_SIZE, (32, 34, 38))
    draw = ImageDraw.Draw(image)
    regions = layout["regions"]
    palette = {
        "bo_identity": (54, 133, 214),
        "mother_identity": (210, 92, 142),
        "interaction": (230, 181, 58),
    }
    for name in ("bo_identity", "mother_identity", "interaction"):
        draw.rectangle(pixels(regions[name]["box"]), outline=palette[name], width=5)
    draw.rectangle(pixels(regions["bo_identity"]["face_box"]), fill=(54, 133, 214))
    draw.rectangle(pixels(regions["mother_identity"]["face_box"]), fill=(210, 92, 142))
    draw.rectangle(
        pixels(regions["interaction"]["bo_hand_box"]), fill=(103, 170, 230)
    )
    draw.rectangle(
        pixels(regions["interaction"]["mother_hand_box"]), fill=(232, 139, 177)
    )
    draw.polygon(
        [
            (pixels(regions["interaction"]["boat_box"])[0], 326),
            (256, pixels(regions["interaction"]["boat_box"])[1]),
            (pixels(regions["interaction"]["boat_box"])[2], 326),
            (256, pixels(regions["interaction"]["boat_box"])[3]),
        ],
        fill=(244, 238, 216),
        outline=(255, 255, 255),
    )
    image.save(path, format="PNG", optimize=True)


def main() -> None:
    result = json.loads(R21_RESULT.read_text(encoding="utf-8"))
    assessment = json.loads(R21_ASSESSMENT.read_text(encoding="utf-8"))
    digest = sha256(NEGATIVE_FIXTURE)
    if digest != EXPECTED_NEGATIVE_SHA256:
        raise RuntimeError(f"R21 negative fixture changed: {digest}")
    failed = set(result["automatic_qa"]["failed_gate_ids"])
    if result["status"] != "AUTO_REJECT_AWAITING_MANUAL_REVIEW":
        raise RuntimeError("R21 is not an auto-rejected checkpoint")
    if failed != EXPECTED_FAILED_GATES:
        raise RuntimeError(f"R21 blocker set changed: {sorted(failed)}")
    if assessment.get("status") != "ASSESSED_FAIL":
        raise RuntimeError("R21 negative assessment no longer rejects the fixture")

    layout = layout_contract()
    validation = validate_layout(layout)
    passed = all(validation.values())
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_ROOT / "regional-spatial-conditioning.json", layout)
    save_mask(
        OUTPUT_ROOT / "bo-region-mask.png", [layout["regions"]["bo_identity"]["box"]]
    )
    save_mask(
        OUTPUT_ROOT / "mother-region-mask.png",
        [layout["regions"]["mother_identity"]["box"]],
    )
    save_mask(
        OUTPUT_ROOT / "interaction-region-mask.png",
        [layout["regions"]["interaction"]["box"]],
    )
    save_preview(OUTPUT_ROOT / "regional-spatial-conditioning-preview.png", layout)

    checkpoint = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R1",
        "status": "PASS_NEGATIVE_LOCK_AND_SPATIAL_DESIGN" if passed else "FAIL",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "negative_fixture": {
            "path": str(NEGATIVE_FIXTURE.resolve()),
            "sha256": digest,
            "mandatory": True,
            "critic_status": assessment["status"],
            "failed_gate_ids": sorted(failed),
            "all_five_structural_gates_reject": failed == EXPECTED_FAILED_GATES,
        },
        "regional_spatial_conditioning": {
            "contract": str(
                (OUTPUT_ROOT / "regional-spatial-conditioning.json").resolve()
            ),
            "preview": str(
                (OUTPUT_ROOT / "regional-spatial-conditioning-preview.png").resolve()
            ),
            "validation": validation,
            "ready_for_integration_dry_run": passed,
            "not_yet_wired_to_transformer": True,
        },
        "guards": {
            "image_generation_performed": False,
            "inference_performed": False,
            "latents_created": False,
            "transformer_called": False,
            "vae_called": False,
            "next_full_scene_attempt_authorized": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
            "source_package_modified": False,
        },
    }
    write_json(OUTPUT_ROOT / "phase4lr9r7r3r21r1-result.json", checkpoint)
    print(json.dumps(checkpoint, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
