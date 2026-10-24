from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
SOURCE_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3-full-scene-candidate-v1")
SOURCE_RESULT = SOURCE_ROOT / "phase4lr9r7r3r21r7r4r5r3-result.json"
SOURCE_ASSESSMENT = SOURCE_ROOT / "candidates/climax/attempt-1-assessment.json"
SOURCE_CANDIDATE = SOURCE_ROOT / "candidates/climax/attempt-1.png"
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r1-reject-and-structural-design-v1")
CONTRACT_PATH = OUTPUT_ROOT / "structural-conditioning-contract.json"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r1-result.json"

EXPECTED_HASHES = {
    "result": "6c4596b0d07fc81b541903f24dc53442d6a34f2e48baa27a235b09cc23fe3372",
    "assessment": "5e926da968a241f9042f4f881a6cf853c718986263bdc2f81bbb0150568e6fc4",
    "candidate": "21624955f0fa89b9ddb410232a2d510927b0264f7d0b419d02f829baf85f84c7",
}
EXPECTED_FAILED_GATES = {
    "hand_anatomy_gate",
    "hand_prop_contact_gate",
    "paper_boat_shape_scale_gate",
    "two_visible_faces_cast_gate",
    "exactly_two_interaction_hands_gate",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def structural_contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "purpose": "CAPABILITY_SPIKE_ONLY",
        "identity_schedule_unchanged": [
            {"step": 0, "identity": "bo", "scale": 0.0},
            {"step": 8, "identity": "bo", "scale": 0.25},
            {"step": 12, "identity": "mother", "scale": 0.25},
            {"step": 16, "identity": "mother", "scale": 0.0},
        ],
        "stages": [
            {
                "id": "early_framing_cast",
                "active_steps": list(range(2, 8)),
                "active_blocks": list(range(0, 10)),
                "scale_candidates": [0.00125, 0.0025],
                "channels": [
                    "bo_silhouette_and_face_box",
                    "mother_silhouette_and_face_box",
                ],
                "hard_constraints": [
                    "exactly_two_full_faces",
                    "left_right_cast_placement",
                    "both_upper_bodies_inside_frame",
                ],
            },
            {
                "id": "middle_pose_contact",
                "active_steps": list(range(8, 16)),
                "active_blocks": list(range(18, 28)),
                "scale_candidates": [0.0025, 0.005],
                "channels": [
                    "forearm_and_hand_keypoints",
                    "two_contact_endpoints",
                    "boat_center_and_triangle",
                ],
                "hard_constraints": [
                    "exactly_two_interaction_hands",
                    "connected_wrists",
                    "opposite_edge_contact",
                    "tiny_palm_sized_paper_boat",
                ],
            },
            {
                "id": "terminal_refinement",
                "active_steps": [22, 23],
                "active_blocks": list(range(28, 38)),
                "scale_candidates": [0.01],
                "role": "REFINEMENT_ONLY_NOT_SOLE_STRUCTURAL_CONTROL",
            },
        ],
        "isolation": {
            "independent_stage_controls": True,
            "zero_control_bitwise_parity_required": True,
            "identity_must_not_encode_pose_contact_or_prop_geometry": True,
        },
        "acceptance": {
            "all_values_finite": True,
            "zero_control_bitwise_parity": True,
            "maximum_relative_global_delta": 0.05,
            "update_norm_ratio_range": [0.5, 1.5],
            "minimum_spatial_dominance_ratio": 0.95,
            "absolute_latent_critic_clean": True,
            "paired_latent_critic_clean_or_baseline_match": True,
            "active_only_seams_forbidden": True,
        },
        "progression": [
            "registration_and_zero_parity_dry_run",
            "single_step_block_window_ab",
            "latent_only_trajectory_ab",
            "request_new_generation_authorization",
        ],
        "production_profile_changed": False,
        "generation_authorized": False,
    }


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R1 checkpoint already exists; refusing to overwrite")

    observed_hashes = {
        "result": sha256(SOURCE_RESULT),
        "assessment": sha256(SOURCE_ASSESSMENT),
        "candidate": sha256(SOURCE_CANDIDATE),
    }
    if observed_hashes != EXPECTED_HASHES:
        raise RuntimeError(f"R3 evidence changed: {observed_hashes}")

    source = json.loads(SOURCE_RESULT.read_text(encoding="utf-8"))
    assessment = json.loads(SOURCE_ASSESSMENT.read_text(encoding="utf-8"))
    failed = set(source["automatic_qa"]["failed_gate_ids"])
    if source["status"] != "AUTO_REJECT_AWAITING_MANUAL_REVIEW":
        raise RuntimeError("R3 is not awaiting manual rejection")
    if assessment["status"] != "ASSESSED_FAIL" or failed != EXPECTED_FAILED_GATES:
        raise RuntimeError("R3 assessment or structural blocker set changed")
    if not source["authorization_consumed"] or source["attempt_count"] != 1:
        raise RuntimeError("R3 authorization accounting changed")
    if source["candidate_promotable"] or not all(
        gate["status"] == "PASS" for gate in source["latent_qa"].values()
    ):
        raise RuntimeError("R3 promotion or latent QA state changed")

    contract = structural_contract()
    write_json(CONTRACT_PATH, contract)
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R1",
        "status": "PASS_REJECTED_ATTEMPT_AND_STRUCTURAL_SPIKE_DESIGN",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "manual_disposition": {
            "status": "REJECTED",
            "candidate_promotable": False,
            "reason": "FIVE_MANDATORY_STRUCTURAL_IMAGE_GATES_FAILED",
        },
        "negative_fixture": {
            "path": str(SOURCE_CANDIDATE.resolve()),
            "sha256": observed_hashes["candidate"],
            "source_result_sha256": observed_hashes["result"],
            "assessment_sha256": observed_hashes["assessment"],
            "mandatory": True,
            "failed_gate_ids": sorted(failed),
            "all_five_structural_gates_must_reject": True,
        },
        "diagnosis": {
            "latent_safety": "PASS",
            "identity_and_photorealism": "PASS",
            "structural_conditioning": "FAIL",
            "root_boundary": (
                "Terminal-only explicit control is latent-safe but begins too late to "
                "establish framing, cast visibility, limb topology, hand-prop contact, "
                "or prop scale."
            ),
        },
        "structural_conditioning": {
            "contract_path": str(CONTRACT_PATH.resolve()),
            "contract_sha256": sha256(CONTRACT_PATH),
            "ready_for_registration_dry_run": True,
            "wired_to_transformer": False,
        },
        "phase4l_closure": {
            "status": "OPEN_PENDING_STRUCTURAL_CAPABILITY_VALIDATION",
            "improvement_from_previous": [
                "manual_disposition_closed",
                "negative_regression_locked",
                "failure_boundary_locked",
                "three_stage_control_contract_ready",
            ],
            "all_requirements_satisfied": False,
        },
        "guards": {
            "inference_performed": False,
            "transformer_called": False,
            "scheduler_called": False,
            "vae_called": False,
            "images_created": 0,
            "new_generation_authorized": False,
            "production_profile_changed": False,
            "source_package_modified": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
        },
    }
    write_json(RESULT_PATH, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
