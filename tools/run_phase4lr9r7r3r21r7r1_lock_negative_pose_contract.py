from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R7_ROOT = BASELINE_ROOT / "phase4lr9r7r3r21r7-regional-candidate-v1"
R7_RESULT = R7_ROOT / "phase4lr9r7r3r21r7-result.json"
R7_ASSESSMENT = R7_ROOT / "candidates/climax/attempt-1-assessment.json"
R7_CANDIDATE = R7_ROOT / "candidates/climax/attempt-1.png"
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r1-negative-pose-contract-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r1-result.json"
CONTRACT_PATH = OUTPUT_ROOT / "explicit-pose-composition-control.json"
EXPECTED_SHA256 = (
    "bcd0ae3e8a1a0b4299ab1f35abfcac71dcbafe9e8c075740d5d02b5522d4c3ca"
)
EXPECTED_FAILED_GATES = {
    "hand_anatomy_gate",
    "hand_prop_contact_gate",
    "paper_boat_shape_scale_gate",
    "two_visible_faces_cast_gate",
    "exactly_two_interaction_hands_gate",
}
CANVAS = (512, 512)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def px(point: list[float]) -> tuple[int, int]:
    return round(point[0] * CANVAS[0]), round(point[1] * CANVAS[1])


def box_px(box: list[float]) -> tuple[int, int, int, int]:
    left, top = px(box[:2])
    right, bottom = px(box[2:])
    return left, top, right, bottom


def contains(box: list[float], point: list[float]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def box_contains(outer: list[float], inner: list[float]) -> bool:
    return contains(outer, inner[:2]) and contains(outer, inner[2:])


def distance(left: list[float], right: list[float]) -> float:
    return ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5


def control_contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "canvas": {"width": 512, "height": 512},
        "safe_frame": [0.06, 0.05, 0.94, 0.95],
        "composition": {
            "people_count": 2,
            "visible_face_count": 2,
            "interaction_hand_count": 2,
            "prop_count": 1,
            "face_anchors": {
                "bo": {"center": [0.27, 0.25], "box": [0.17, 0.13, 0.37, 0.37]},
                "mother": {
                    "center": [0.73, 0.25],
                    "box": [0.63, 0.13, 0.83, 0.37],
                },
            },
            "interaction_roi": [0.34, 0.50, 0.66, 0.74],
            "negative_space": [0.40, 0.38, 0.60, 0.49],
        },
        "pose": {
            "bo": {
                "shoulder": [0.35, 0.40],
                "elbow": [0.39, 0.52],
                "wrist": [0.43, 0.61],
                "contact": [0.475, 0.625],
                "visible_interaction_hands": 1,
            },
            "mother": {
                "shoulder": [0.65, 0.40],
                "elbow": [0.61, 0.52],
                "wrist": [0.57, 0.61],
                "contact": [0.525, 0.625],
                "visible_interaction_hands": 1,
            },
            "forbidden": {
                "extra_wrist_or_hand_keypoints": True,
                "crossed_wrists": True,
                "detached_contact_from_wrist_chain": True,
            },
        },
        "prop_geometry": {
            "type": "FOLDED_PAPER_BOAT",
            "center": [0.50, 0.625],
            "bounding_box": [0.465, 0.595, 0.535, 0.655],
            "silhouette_polygon": [
                [0.465, 0.635],
                [0.485, 0.605],
                [0.500, 0.625],
                [0.515, 0.605],
                [0.535, 0.635],
                [0.520, 0.650],
                [0.480, 0.650],
            ],
            "maximum_canvas_area_fraction": 0.0042,
            "left_contact": [0.475, 0.625],
            "right_contact": [0.525, 0.625],
        },
        "conditioning_design": {
            "identity_path": "REGIONAL_TIME_MULTIPLEXED_IP_ADAPTER",
            "identity_role": "IDENTITY_ONLY",
            "pose_path": "EXPLICIT_SKELETON_HEATMAP_OR_CONTROL_RESIDUAL",
            "composition_path": "FACE_ANCHOR_AND_SAFE_FRAME_HEATMAPS",
            "prop_path": "BINARY_SILHOUETTE_OR_EDGE_CONTROL",
            "interaction_path": "TWO_ENDPOINT_CONTACT_HEATMAP",
            "routing": {
                "identity": "REGIONAL_ATTENTION_PROCESSORS",
                "pose_composition_prop": "SEPARATE_CONTROL_RESIDUAL_PATH",
                "must_not_encode_prop_in_identity_embedding": True,
            },
            "integration_order": [
                "render_control_tensors",
                "validate_counts_bounds_and_contacts",
                "single_step_zero_residual_equivalence",
                "single_step_control_locality_ab",
                "latent_only_trajectory_ab",
                "request_new_decode_authorization",
            ],
        },
        "hard_guards": {
            "both_face_boxes_inside_safe_frame": True,
            "exactly_two_people": True,
            "exactly_two_interaction_hands": True,
            "one_connected_arm_chain_per_interaction_hand": True,
            "contacts_on_opposite_prop_edges": True,
            "prop_inside_interaction_roi": True,
            "prop_area_bounded": True,
            "identity_conditioning_cannot_override_pose_or_prop_controls": True,
            "decode_forbidden_until_control_integration_passes": True,
        },
    }


def validate(contract: dict[str, Any]) -> dict[str, bool]:
    composition = contract["composition"]
    pose = contract["pose"]
    prop = contract["prop_geometry"]
    safe = contract["safe_frame"]
    roi = composition["interaction_roi"]
    prop_box = prop["bounding_box"]
    prop_area = (prop_box[2] - prop_box[0]) * (prop_box[3] - prop_box[1])
    chains = [pose["bo"], pose["mother"]]
    return {
        "bo_face_inside_safe_frame": box_contains(
            safe, composition["face_anchors"]["bo"]["box"]
        ),
        "mother_face_inside_safe_frame": box_contains(
            safe, composition["face_anchors"]["mother"]["box"]
        ),
        "exact_people_and_faces": (
            composition["people_count"] == composition["visible_face_count"] == 2
        ),
        "exact_interaction_hands": (
            composition["interaction_hand_count"] == 2
            and sum(chain["visible_interaction_hands"] for chain in chains) == 2
        ),
        "arm_chains_end_at_contacts": all(
            distance(chain["wrist"], chain["contact"]) <= 0.08 for chain in chains
        ),
        "contacts_inside_interaction_roi": all(
            contains(roi, chain["contact"]) for chain in chains
        ),
        "opposite_contact_order": (
            pose["bo"]["contact"][0]
            < prop["center"][0]
            < pose["mother"]["contact"][0]
        ),
        "contacts_match_prop_edges": (
            pose["bo"]["contact"] == prop["left_contact"]
            and pose["mother"]["contact"] == prop["right_contact"]
        ),
        "prop_inside_interaction_roi": box_contains(roi, prop_box),
        "prop_area_bounded": (
            prop_area <= prop["maximum_canvas_area_fraction"] + 1e-12
        ),
        "identity_separated_from_geometry": (
            contract["conditioning_design"]["identity_role"] == "IDENTITY_ONLY"
            and contract["conditioning_design"]["routing"][
                "must_not_encode_prop_in_identity_embedding"
            ]
        ),
    }


def save_controls(contract: dict[str, Any]) -> dict[str, str]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    pose_image = Image.new("L", CANVAS, 0)
    pose_draw = ImageDraw.Draw(pose_image)
    for identity in ("bo", "mother"):
        chain = contract["pose"][identity]
        points = [px(chain[name]) for name in ("shoulder", "elbow", "wrist", "contact")]
        pose_draw.line(points, fill=255, width=7, joint="curve")
        for point in points:
            pose_draw.ellipse(
                (point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5),
                fill=255,
            )
    pose_path = OUTPUT_ROOT / "pose-control.png"
    pose_image.save(pose_path, optimize=True)

    composition_image = Image.new("L", CANVAS, 0)
    composition_draw = ImageDraw.Draw(composition_image)
    for face in contract["composition"]["face_anchors"].values():
        composition_draw.ellipse(box_px(face["box"]), fill=255)
    composition_path = OUTPUT_ROOT / "composition-control.png"
    composition_image.save(composition_path, optimize=True)

    prop_image = Image.new("L", CANVAS, 0)
    prop_draw = ImageDraw.Draw(prop_image)
    prop_draw.polygon(
        [px(point) for point in contract["prop_geometry"]["silhouette_polygon"]],
        fill=255,
    )
    prop_path = OUTPUT_ROOT / "prop-silhouette-control.png"
    prop_image.save(prop_path, optimize=True)

    preview = Image.new("RGB", CANVAS, (27, 29, 34))
    preview_draw = ImageDraw.Draw(preview)
    for identity, color in (("bo", (60, 145, 230)), ("mother", (225, 100, 155))):
        face = contract["composition"]["face_anchors"][identity]
        preview_draw.ellipse(box_px(face["box"]), outline=color, width=5)
        chain = contract["pose"][identity]
        preview_draw.line(
            [px(chain[name]) for name in ("shoulder", "elbow", "wrist", "contact")],
            fill=color,
            width=7,
            joint="curve",
        )
    preview_draw.rectangle(
        box_px(contract["composition"]["interaction_roi"]),
        outline=(235, 188, 62),
        width=3,
    )
    preview_draw.polygon(
        [px(point) for point in contract["prop_geometry"]["silhouette_polygon"]],
        fill=(245, 239, 216),
        outline=(255, 255, 255),
    )
    preview_path = OUTPUT_ROOT / "explicit-control-preview.png"
    preview.save(preview_path, optimize=True)
    return {
        "pose": str(pose_path.resolve()),
        "composition": str(composition_path.resolve()),
        "prop_silhouette": str(prop_path.resolve()),
        "preview": str(preview_path.resolve()),
    }


def main() -> None:
    if RESULT_PATH.exists():
        previous = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        if previous.get("status") != "FAIL":
            raise RuntimeError(
                "R21-R7-R1 already passed; refusing to overwrite checkpoint"
            )
    result = json.loads(R7_RESULT.read_text(encoding="utf-8"))
    assessment = json.loads(R7_ASSESSMENT.read_text(encoding="utf-8"))
    digest = sha256(R7_CANDIDATE)
    failed = set(result["automatic_qa"]["failed_gate_ids"])
    if digest != EXPECTED_SHA256 or result["candidate_sha256"] != digest:
        raise RuntimeError("R7 candidate hash changed")
    if result["status"] != "AUTO_REJECT_AWAITING_MANUAL_REVIEW":
        raise RuntimeError("R7 is not an auto-rejected checkpoint")
    if assessment.get("status") != "ASSESSED_FAIL":
        raise RuntimeError("R7 assessment no longer rejects the candidate")
    if failed != EXPECTED_FAILED_GATES:
        raise RuntimeError(f"R7 blocker set changed: {sorted(failed)}")

    contract = control_contract()
    validation = validate(contract)
    passed = all(validation.values())
    write_json(CONTRACT_PATH, contract)
    control_files = save_controls(contract)
    checkpoint = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R1",
        "status": "PASS_NEGATIVE_LOCK_AND_EXPLICIT_CONTROL_DESIGN" if passed else "FAIL",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "negative_fixture": {
            "path": str(R7_CANDIDATE.resolve()),
            "sha256": digest,
            "mandatory": True,
            "critic_status": assessment["status"],
            "failed_gate_ids": sorted(failed),
            "all_five_structural_gates_reject": failed == EXPECTED_FAILED_GATES,
        },
        "explicit_control": {
            "contract": str(CONTRACT_PATH.resolve()),
            "files": control_files,
            "validation": validation,
            "ready_for_integration_dry_run": passed,
            "not_yet_wired_to_transformer": True,
        },
        "diagnosis": {
            "regional_identity_succeeded": True,
            "structural_control_failed": True,
            "root_boundary": (
                "Regional IP-Adapter masks constrain identity influence but do not "
                "hard-constrain framing, limb topology, contact, or prop geometry."
            ),
        },
        "guards": {
            "image_generation_performed": False,
            "inference_performed": False,
            "latents_created": False,
            "transformer_called": False,
            "vae_called": False,
            "new_decode_authorized": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
            "source_package_modified": False,
        },
    }
    write_json(RESULT_PATH, checkpoint)
    print(json.dumps(checkpoint, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
