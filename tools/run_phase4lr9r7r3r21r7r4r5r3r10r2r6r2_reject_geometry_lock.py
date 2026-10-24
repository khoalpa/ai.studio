from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R1_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r1-replay-decode-v1"
)
R1_RESULT = R1_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r6r1-result.json"
CANDIDATE_PATH = R1_ROOT / "candidates/climax/attempt-1.png"
ASSESSMENT_PATH = R1_ROOT / "candidates/climax/attempt-1-assessment.json"
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r2-reject-geometry-lock-v1"
)
GEOMETRY_CONTRACT_PATH = OUTPUT_ROOT / "geometry-contract.json"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10r2r6r2-result.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if RESULT_PATH.exists() or GEOMETRY_CONTRACT_PATH.exists():
        raise RuntimeError("R10-R2-R6-R2 checkpoint already exists; refusing overwrite")
    prior = json.loads(R1_RESULT.read_text(encoding="utf-8"))
    assessment = json.loads(ASSESSMENT_PATH.read_text(encoding="utf-8"))
    if prior["status"] != "AUTO_REJECT_AWAITING_MANUAL_REVIEW":
        raise RuntimeError("R1 candidate is not awaiting rejected manual review")
    if prior["manual_review_status"] != "PENDING":
        raise RuntimeError("R1 manual review state changed")
    if assessment["status"] != "ASSESSED_FAIL":
        raise RuntimeError("R1 assessment no longer rejects the candidate")

    required_failures = [
        "hand_anatomy_gate",
        "hand_prop_contact_gate",
        "paper_boat_shape_scale_gate",
        "two_visible_faces_cast_gate",
        "exactly_two_interaction_hands_gate",
    ]
    for gate in required_failures:
        if assessment["gates"][gate]["status"] != "FAIL":
            raise RuntimeError(f"expected locked negative gate failure: {gate}")

    geometry_contract = {
        "schema_version": "1.0",
        "contract_id": "climax-two-person-paper-boat-geometry-v1",
        "canvas": {"width": 512, "height": 512},
        "requirements": {
            "visible_faces": {
                "exact_count": 2,
                "subjects": ["BO", "ME"],
                "both_fully_inside_frame": True,
                "no_face_occlusion_by_crop": True,
            },
            "interaction_hands": {
                "exact_count": 2,
                "one_hand_per_subject": True,
                "both_anatomically_plausible": True,
                "no_fused_or_duplicate_fingers": True,
            },
            "paper_boat": {
                "exact_count": 1,
                "recognizable_folded_paper_silhouette": True,
                "scale_relative_to_hands": "SMALL_HANDHELD_PROP",
                "must_not_resemble": ["cup", "pedestal", "large sculpture"],
            },
            "contact": {
                "both_hands_contact_same_boat": True,
                "contact_points_visible": True,
                "no_hand_prop_interpenetration": True,
            },
            "composition": {
                "subjects_and_prop_inside_frame": True,
                "interaction_roi_unobstructed": True,
                "mother_face_must_not_be_cropped": True,
            },
        },
        "authorization_policy": {
            "latent_only_dry_run_required_before_next_decode": True,
            "roi_coverage_gate_required": True,
            "face_layout_gate_required": True,
            "hand_layout_gate_required": True,
            "prop_layout_gate_required": True,
            "next_decode_authorized": False,
            "automatic_retry_authorized": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    GEOMETRY_CONTRACT_PATH.write_text(
        json.dumps(geometry_contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10-R2-R6-R2",
        "status": "PASS_MANUAL_REJECT_AND_GEOMETRY_FAILURE_LOCK",
        "manual_review": {
            "candidate_status": "REJECTED",
            "reason": "AUTOMATIC_AND_VISUAL_GEOMETRY_FAILURE_CONFIRMED",
            "candidate_path": str(CANDIDATE_PATH.resolve()),
            "candidate_sha256": sha256(CANDIDATE_PATH),
            "assessment_path": str(ASSESSMENT_PATH.resolve()),
            "assessment_sha256": sha256(ASSESSMENT_PATH),
        },
        "negative_regression": {
            "fixture_role": "REQUIRED_NEGATIVE",
            "locked_failure_gates": required_failures,
            "passing_invariants": [
                "photorealism_fidelity_gate",
                "bo_identity",
                "me_identity",
                "text_artifact",
            ],
        },
        "geometry_contract_path": str(GEOMETRY_CONTRACT_PATH.resolve()),
        "geometry_contract_sha256": sha256(GEOMETRY_CONTRACT_PATH),
        "phase4l_closure": {
            "status": "OPEN_PENDING_GEOMETRY_CONTROL_DRY_RUN",
            "all_requirements_satisfied": False,
        },
        "guards": {
            "denoise_runs": 0,
            "vae_calls": {"forward": 0, "decode": 0},
            "images_created": 0,
            "next_candidate_authorized": False,
            "production_profile_changed": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
        },
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
