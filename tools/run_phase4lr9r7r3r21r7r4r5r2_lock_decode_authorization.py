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
R4_R4_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r4-late-tail-micro-window-isolation-v1/phase4lr9r7r3r21r7r4r4-result.json"
)
R4_R5_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5-terminal-profile-confirmation-v1/phase4lr9r7r3r21r7r4r5-result.json"
)
R4_R5_R1_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r1-paired-critic-calibration-v1/phase4lr9r7r3r21r7r4r5r1-result.json"
)
LAYOUT_PATH = BASELINE_ROOT / (
    "phase4lr9r7r3r21r1-negative-spatial-conditioning-lock-v1/regional-spatial-conditioning.json"
)
EXPLICIT_CONTROL = PROJECT_ROOT / "src/ai_story/explicit_spatial_control.py"
PAIRED_CRITIC = PROJECT_ROOT / "src/ai_story/latent_discontinuity.py"
SOURCE_WORK = BASELINE_ROOT / "phase4l-climax-canary-v1/youth-torn-paper-boat/work"
BO_REFERENCE = SOURCE_WORK / "characters/bo.png"
ME_REFERENCE = SOURCE_WORK / "characters/me.png"
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r2-decode-authorization-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r2-result.json"
EXPECTED_HASHES = {
    R4_R4_RESULT: "18b067c23498e5c7ed27a9873f1ebdb0beb8125588899ac3f222588a3b0a0bdc",
    R4_R5_RESULT: "d12062b2f944b80654455026423e5acf03d913eb1a23331cc8cc2dcbe9ffd9e8",
    R4_R5_R1_RESULT: "1a29ccdb7b70bbe0a53579516f0acb4baa29b0806f40d96904af14ae9d17ef8b",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_lock(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R4-R5-R2 already exists; refusing to overwrite authorization")
    for path, expected in EXPECTED_HASHES.items():
        if sha256(path) != expected:
            raise RuntimeError(f"evidence lock changed: {path}")
    r4_r4 = json.loads(R4_R4_RESULT.read_text(encoding="utf-8"))
    r4_r5 = json.loads(R4_R5_RESULT.read_text(encoding="utf-8"))
    calibration = json.loads(R4_R5_R1_RESULT.read_text(encoding="utf-8"))
    if r4_r4.get("selected_profile") != "late_terminal":
        raise RuntimeError("R4-R4 terminal profile is not selected")
    if r4_r5.get("seed") != 420918 or r4_r5.get("status") != "FAIL":
        raise RuntimeError("R4-R5 confirmation fixture changed")
    if calibration.get("status") != "PASS_PAIRED_BASELINE_CRITIC_CALIBRATION":
        raise RuntimeError("paired critic calibration is not passing")
    if calibration["paired_decision"]["blocked"]:
        raise RuntimeError("paired critic still blocks the confirmation")
    if not all(calibration["metric_gates"].values()):
        raise RuntimeError("confirmation metric gates are not all passing")
    if not calibration["negative_controls_reject"]:
        raise RuntimeError("paired critic negative controls are not locked")

    locked_profile = {
        "seed": 420917,
        "resolution": [512, 512],
        "pipeline_dtype": "torch.bfloat16",
        "steps": 24,
        "guidance_scale": 5.0,
        "identity_mode": "REGIONAL_TIME_MULTIPLEXED_BO_ME",
        "identity_events": [
            {"effective_step": 0, "scale": 0.0, "identity": "BO"},
            {"effective_step": 8, "scale": 0.25, "identity": "BO"},
            {"effective_step": 12, "scale": 0.25, "identity": "ME"},
            {"effective_step": 16, "scale": 0.0, "identity": "ME"},
        ],
        "explicit_control": {
            "active_blocks": list(range(28, 38)),
            "scale": 0.01,
            "active_steps": [22, 23],
        },
        "paired_critic": calibration["critic_policy"],
        "prompt": PHOTOREALISTIC_INTERACTION_PROMPT,
        "negative_prompt": PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
        "automatic_retry_allowed": False,
    }
    profile_sha256 = hashlib.sha256(
        json.dumps(
            locked_profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    image_gates = [
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
    latent_gates = [
        "paired_latent_discontinuity_gate",
        "vae_amplification_precursor_gate",
    ]
    closure_requirements = [
        {
            "id": "two_seed_terminal_profile_and_paired_critic_locked",
            "status": "PASS",
            "evidence": str(R4_R5_R1_RESULT.resolve()),
        },
        {
            "id": "single_candidate_passes_all_automatic_gates",
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
            "id": "negative_fixtures_reject_and_promoted_positive_passes_regression",
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
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R2",
        "status": "PASS_ONE_FULL_SCENE_DECODE_ATTEMPT_AUTHORIZED",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "evidence_locks": {
            "r4_r4_profile_selection": file_lock(R4_R4_RESULT),
            "r4_r5_independent_confirmation": file_lock(R4_R5_RESULT),
            "r4_r5_r1_paired_calibration": file_lock(R4_R5_R1_RESULT),
            "spatial_contract": file_lock(LAYOUT_PATH),
            "explicit_control": file_lock(EXPLICIT_CONTROL),
            "paired_critic": file_lock(PAIRED_CRITIC),
            "bo_reference": file_lock(BO_REFERENCE),
            "mother_reference": file_lock(ME_REFERENCE),
        },
        "locked_profile": locked_profile,
        "locked_profile_sha256": profile_sha256,
        "required_image_gates": image_gates,
        "required_latent_gates": latent_gates,
        "authorization": {
            "target": "youth-torn-paper-boat/climax.png",
            "maximum_trajectory_attempts": 1,
            "maximum_vae_decodes": 1,
            "attempts_consumed": 0,
            "profile_override_allowed": False,
            "critic_policy_override_allowed": False,
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
