from __future__ import annotations

import hashlib
import json
from pathlib import Path

import run_phase4lr9r7r3r21r5_regional_trajectory as runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
AUTHORIZATION = BASELINE_ROOT / (
    "phase4lr9r7r3r21r6-regional-decode-authorization-v1/"
    "phase4lr9r7r3r21r6-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r21r7-regional-candidate-v1"
EXPECTED_PROFILE_SHA256 = "a60f562d66dd61d85f4069311ec2a8256319aaf5245bed080e5854368cf7ec32"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    if authorization.get("status") != "PASS_ONE_FULL_SCENE_DECODE_ATTEMPT_AUTHORIZED":
        raise RuntimeError("R21-R6 authorization is not valid")
    if authorization.get("locked_profile_sha256") != EXPECTED_PROFILE_SHA256:
        raise RuntimeError("R21-R6 locked profile changed")
    for label, lock in authorization["evidence_locks"].items():
        path = Path(lock["path"])
        if not path.is_file() or sha256(path) != lock["sha256"]:
            raise RuntimeError(f"Locked R21-R6 evidence changed: {label}")
    auth = authorization["authorization"]
    if not (
        auth["authorized"]
        and auth["maximum_trajectory_attempts"] == 1
        and auth["maximum_vae_decodes"] == 1
        and auth["attempts_consumed"] == 0
        and auth["automatic_retry_allowed"] is False
    ):
        raise RuntimeError("R21-R6 one-attempt authorization is not intact")

    runtime.PHASE = "4L-R9-R7-R3-R21-R7"
    runtime.OUTPUT_ROOT = OUTPUT_ROOT
    runtime.RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7-result.json"
    runtime.CANDIDATE_PATH = OUTPUT_ROOT / "candidates/climax/attempt-1.png"
    runtime.ASSESSMENT_PATH = (
        OUTPUT_ROOT / "candidates/climax/attempt-1-assessment.json"
    )
    runtime.AUTHORIZATION_RESULT = AUTHORIZATION
    runtime.DECODE_CANDIDATE = True
    runtime.main()


if __name__ == "__main__":
    main()
