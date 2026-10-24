from __future__ import annotations

from pathlib import Path

import run_phase4lr9r7r3r13_neutral_scale0375_canary as canary_supervisor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R13_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r13-neutral-scale0375-canary-v1/phase4lr9r7r3r13-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r14-neutral-scale025-canary-v1"


def configure() -> None:
    canary_supervisor.PRIOR_RESULT = R13_RESULT
    canary_supervisor.PRIOR_STATUS = "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
    canary_supervisor.PHASE = "4L-R9-R7-R3-R14"
    canary_supervisor.OUTPUT_ROOT = OUTPUT_ROOT
    canary_supervisor.CANDIDATE = (
        OUTPUT_ROOT / "candidates/neutral-identity/attempt-1.png"
    )
    canary_supervisor.ASSESSMENT_PATH = OUTPUT_ROOT / (
        "candidates/neutral-identity/attempt-1-assessment.json"
    )
    canary_supervisor.RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r14-result.json"
    canary_supervisor.WORKER_LOG = OUTPUT_ROOT / "worker.log"
    canary_supervisor.SCALE = 0.25
    canary_supervisor.ENTRYPOINT = Path(__file__).resolve()


def main() -> None:
    configure()
    canary_supervisor.main()


if __name__ == "__main__":
    main()
