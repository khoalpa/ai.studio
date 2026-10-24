from __future__ import annotations

import hashlib
import json
from pathlib import Path

import run_phase4lr9r7r3r20_locked_climax as climax_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
AUTH_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r20r5-time-multiplexed-lock-v1/phase4lr9r7r3r20r5-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r21-time-multiplexed-climax-v1"
SCHEDULE = [
    {"effective_step": 0, "scale": 0.0},
    {"effective_step": 8, "scale": 0.25},
    {"effective_step": 16, "scale": 0.0},
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_lock(lock: dict[str, str], label: str) -> None:
    path = Path(lock["path"])
    if not path.is_file() or sha256(path) != lock["sha256"]:
        raise RuntimeError(f"Locked {label} is missing or changed")


def configure() -> None:
    climax_runtime.PHASE = "4L-R9-R7-R3-R21"
    climax_runtime.PRIOR_RESULT = AUTH_RESULT
    climax_runtime.PRIOR_STATUS = "PASS_ONE_FULL_SCENE_ATTEMPT_REAUTHORIZED"
    climax_runtime.REQUIRE_AUTHORIZATION = True
    climax_runtime.LATENT_ONLY = False
    climax_runtime.IDENTITY_MODE = "TIME_MULTIPLEXED_BO_ME"
    climax_runtime.SCHEDULE = SCHEDULE
    climax_runtime.OUTPUT_ROOT = OUTPUT_ROOT
    climax_runtime.CANDIDATE = OUTPUT_ROOT / "candidates/climax/attempt-1.png"
    climax_runtime.ASSESSMENT_PATH = (
        OUTPUT_ROOT / "candidates/climax/attempt-1-assessment.json"
    )
    climax_runtime.RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21-result.json"
    climax_runtime.WORKER_LOG = OUTPUT_ROOT / "worker.log"
    climax_runtime.ENTRYPOINT = Path(__file__).resolve()


def main() -> None:
    authorization = json.loads(AUTH_RESULT.read_text(encoding="utf-8"))
    verify_lock(authorization["runtime_lock"], "runtime")
    for reference_id, lock in authorization["reference_locks"].items():
        verify_lock(lock, f"{reference_id} reference")
    configure()
    climax_runtime.main()


if __name__ == "__main__":
    main()
