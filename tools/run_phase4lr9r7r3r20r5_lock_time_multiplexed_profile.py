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
R20_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r20-locked-climax-v1/phase4lr9r7r3r20-result.json"
)
R20_R4_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r20r4-time-multiplexed-control-v1/"
    "phase4lr9r7r3r20r4-result.json"
)
SOURCE_WORK = BASELINE_ROOT / "phase4l-climax-canary-v1/youth-torn-paper-boat/work"
BO_REFERENCE = SOURCE_WORK / "characters/bo.png"
ME_REFERENCE = SOURCE_WORK / "characters/me.png"
RUNTIME = PROJECT_ROOT / "tools/run_phase4lr9r7r3r20_locked_climax.py"
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r20r5-time-multiplexed-lock-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r20r5-result.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_lock(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def main() -> None:
    failed_attempt = json.loads(R20_RESULT.read_text(encoding="utf-8"))
    control = json.loads(R20_R4_RESULT.read_text(encoding="utf-8"))
    if failed_attempt.get("status") != "AUTO_BLOCKED_PRE_DECODE":
        raise RuntimeError("R20 consumed-attempt checkpoint is not satisfied")
    if not (
        failed_attempt.get("authorization_consumed") is True
        and failed_attempt.get("attempts_consumed") == 1
    ):
        raise RuntimeError("R20 prior authorization consumption is not locked")
    if control.get("status") != "PASS_CLEAN_TIME_MULTIPLEXED_TWO_IDENTITY":
        raise RuntimeError("R20-R4 time-multiplexed control must be clean")
    generation = control["generation"]
    if generation["latent_critic"]["blocked"] is not False:
        raise RuntimeError("R20-R4 latent critic is not clean")
    if generation["vae_calls"] != {"forward": 0, "decode": 0}:
        raise RuntimeError("R20-R4 violated latent-only guard")
    if RESULT_PATH.exists():
        raise RuntimeError("R20-R5 already completed; refusing to overwrite checkpoint")

    locked_profile = {
        "seed": generation["seed"],
        "resolution": generation["dimensions"],
        "pipeline_dtype": generation["pipeline_dtype"],
        "steps": generation["steps"],
        "guidance_scale": generation["guidance_scale"],
        "ip_adapter_scale_schedule": generation["ip_adapter_scale_schedule"],
        "identity_conditioning": generation["identity_conditioning"],
        "identity_schedule": generation["identity_schedule"],
        "prompt": PHOTOREALISTIC_INTERACTION_PROMPT,
        "negative_prompt": PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
        "composition_canvas_used": False,
        "vae_boundary_instrumentation_required": True,
    }
    profile_sha256 = hashlib.sha256(
        json.dumps(
            locked_profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R20-R5",
        "status": "PASS_ONE_FULL_SCENE_ATTEMPT_REAUTHORIZED",
        "prior_attempt": {
            "phase": "4L-R9-R7-R3-R20",
            "status": failed_attempt["status"],
            "authorization_consumed": True,
            "attempts_consumed": 1,
            "candidate_created": False,
        },
        "causal_evidence": {
            "phase": "4L-R9-R7-R3-R20-R4",
            "status": control["status"],
            "conclusion": control["causal_conclusion"],
        },
        "reference_locks": {
            "bo": file_lock(BO_REFERENCE),
            "me": file_lock(ME_REFERENCE),
        },
        "runtime_lock": file_lock(RUNTIME),
        "locked_profile": locked_profile,
        "locked_profile_sha256": profile_sha256,
        "authorization": {
            "target": "youth-torn-paper-boat/climax.png",
            "maximum_attempts": 1,
            "attempts_consumed": 0,
            "full_scene_only": True,
            "time_multiplexed_identity_required": True,
            "profile_override_allowed": False,
            "automatic_qa_required": True,
            "manual_review_after_generation_required": True,
            "authorized": True,
        },
        "required_image_gates": [
            "photorealism_fidelity_gate",
            "hand_anatomy_gate",
            "hand_prop_contact_gate",
            "paper_boat_shape_scale_gate",
            "two_visible_faces_cast_gate",
            "exactly_two_interaction_hands_gate",
            "bo_identity",
            "me_identity",
            "text_artifact",
        ],
        "guards": {
            "image_generation_performed": False,
            "candidate_modified": False,
            "source_package_modified": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
