from __future__ import annotations

import hashlib
import json
from pathlib import Path

import run_phase4lr9r7r3r21r5_regional_trajectory as runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
AUTHORIZATION = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r2-decode-authorization-v1/phase4lr9r7r3r21r7r4r5r2-result.json"
)
BASELINE_CACHE = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r4-late-tail-micro-window-isolation-v1/branch-cache/baseline.pt"
)
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3-full-scene-candidate-v1")
EXPECTED_AUTHORIZATION_SHA256 = "2029eff8e1429d13a05b6c93f728159defdeae2b517924b2eeb55ba5f6df60fd"
EXPECTED_PROFILE_SHA256 = "512096d1b73e0599a7fbe6b629d2c315474f2593cae203fb3b97210eee8f9d13"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if sha256(AUTHORIZATION) != EXPECTED_AUTHORIZATION_SHA256:
        raise RuntimeError("R4-R5-R2 authorization digest changed")
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    if authorization.get("status") != "PASS_ONE_FULL_SCENE_DECODE_ATTEMPT_AUTHORIZED":
        raise RuntimeError("R4-R5-R2 authorization is not valid")
    if authorization.get("locked_profile_sha256") != EXPECTED_PROFILE_SHA256:
        raise RuntimeError("locked profile digest changed")
    for label, lock in authorization["evidence_locks"].items():
        path = Path(lock["path"])
        if not path.is_file() or sha256(path) != lock["sha256"]:
            raise RuntimeError(f"locked authorization evidence changed: {label}")
    auth = authorization["authorization"]
    if auth != {
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
    }:
        raise RuntimeError("one-attempt authorization contract changed")
    profile = authorization["locked_profile"]
    if profile["explicit_control"] != {
        "active_blocks": list(range(28, 38)),
        "scale": 0.01,
        "active_steps": [22, 23],
    }:
        raise RuntimeError("explicit control profile changed")

    runtime.PHASE = "4L-R9-R7-R3-R21-R7-R4-R5-R3"
    runtime.OUTPUT_ROOT = OUTPUT_ROOT
    runtime.RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3-result.json"
    runtime.CANDIDATE_PATH = OUTPUT_ROOT / "candidates/climax/attempt-1.png"
    runtime.ASSESSMENT_PATH = OUTPUT_ROOT / "candidates/climax/attempt-1-assessment.json"
    runtime.AUTHORIZATION_RESULT = AUTHORIZATION
    runtime.DECODE_CANDIDATE = True
    runtime.EXPLICIT_CONTROL_PROFILE = profile["explicit_control"]
    runtime.PAIRED_BASELINE_CACHE = BASELINE_CACHE
    runtime.main()


if __name__ == "__main__":
    main()
