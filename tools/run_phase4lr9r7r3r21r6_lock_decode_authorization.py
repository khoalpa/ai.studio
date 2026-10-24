from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ai_story.image_gate_profiles import (
    PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
    PHOTOREALISTIC_INTERACTION_PROMPT,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R5_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r5-regional-trajectory-v1/phase4lr9r7r3r21r5-result.json"
)
SPATIAL_CONTRACT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r1-negative-spatial-conditioning-lock-v1/"
    "regional-spatial-conditioning.json"
)
REGIONAL_PROCESSOR = PROJECT_ROOT / "src/ai_story/regional_ip_adapter.py"
BO_REFERENCE = BASELINE_ROOT / (
    "phase4l-climax-canary-v1/youth-torn-paper-boat/work/characters/bo.png"
)
ME_REFERENCE = BASELINE_ROOT / (
    "phase4l-climax-canary-v1/youth-torn-paper-boat/work/characters/me.png"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r6-regional-decode-authorization-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r6-result.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_lock(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R21-R6 already exists; refusing to overwrite authorization")
    trajectory = json.loads(R5_RESULT.read_text(encoding="utf-8"))
    regional = trajectory["regional_b"]
    if trajectory.get("status") != "PASS_CLEAN_REGIONAL_TIME_MULTIPLEXED_TRAJECTORY":
        raise RuntimeError("R21-R5 clean regional trajectory is required")
    if regional["latent_critic"]["blocked"] is not False:
        raise RuntimeError("R21-R5 latent critic is not clean")
    if trajectory["guards"]["vae_calls"] != {"forward": 0, "decode": 0}:
        raise RuntimeError("R21-R5 violated latent-only guard")

    locked_profile = {
        "seed": regional["seed"],
        "resolution": [512, 512],
        "pipeline_dtype": "torch.bfloat16",
        "steps": regional["steps"],
        "guidance_scale": regional["guidance_scale"],
        "events": regional["events"],
        "identity_mode": "REGIONAL_TIME_MULTIPLEXED_BO_ME",
        "prompt": PHOTOREALISTIC_INTERACTION_PROMPT,
        "negative_prompt": PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
        "vae_decode_limit": 1,
        "automatic_retry_allowed": False,
    }
    profile_sha256 = hashlib.sha256(
        json.dumps(
            locked_profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    gates = [
        "photorealism_fidelity_gate",
        "hand_anatomy_gate",
        "hand_prop_contact_gate",
        "paper_boat_shape_scale_gate",
        "two_visible_faces_cast_gate",
        "exactly_two_interaction_hands_gate",
        "bo_identity",
        "me_identity",
        "text_artifact",
    ]
    closure_requirements = [
        {
            "id": "regional_trajectory_clean",
            "status": "PASS",
            "evidence": str(R5_RESULT.resolve()),
        },
        {
            "id": "single_candidate_passes_all_nine_automatic_gates",
            "status": "PENDING",
        },
        {
            "id": "manual_review_approves_photorealism_cast_hands_contact_and_boat",
            "status": "PENDING",
        },
        {
            "id": "approved_candidate_promoted_to_package_climax_with_hash_lock",
            "status": "PENDING",
        },
        {
            "id": "r21_negative_rejected_and_promoted_positive_passes_regression",
            "status": "PENDING",
        },
        {
            "id": "full_regression_suite_passes_without_profile_override",
            "status": "PENDING",
        },
        {
            "id": "phase4l_closure_checkpoint_records_no_open_visual_blocker",
            "status": "PENDING",
        },
    ]
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R6",
        "status": "PASS_ONE_FULL_SCENE_DECODE_ATTEMPT_AUTHORIZED",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "evidence_locks": {
            "trajectory": file_lock(R5_RESULT),
            "spatial_contract": file_lock(SPATIAL_CONTRACT),
            "regional_processor": file_lock(REGIONAL_PROCESSOR),
            "bo_reference": file_lock(BO_REFERENCE),
            "mother_reference": file_lock(ME_REFERENCE),
        },
        "locked_profile": locked_profile,
        "locked_profile_sha256": profile_sha256,
        "required_image_gates": gates,
        "authorization": {
            "target": "youth-torn-paper-boat/climax.png",
            "maximum_trajectory_attempts": 1,
            "maximum_vae_decodes": 1,
            "attempts_consumed": 0,
            "regional_time_multiplexing_required": True,
            "spatial_contract_override_allowed": False,
            "profile_override_allowed": False,
            "automatic_retry_allowed": False,
            "automatic_qa_required": True,
            "manual_review_required": True,
            "authorized": True,
        },
        "phase4l_closure": {
            "status": "OPEN_PENDING_AUTHORIZED_ATTEMPT",
            "requirements": closure_requirements,
            "all_requirements_satisfied": False,
        },
        "guards": {
            "image_generation_performed": False,
            "trajectory_run": False,
            "vae_called": False,
            "candidate_created": False,
            "source_package_modified": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
