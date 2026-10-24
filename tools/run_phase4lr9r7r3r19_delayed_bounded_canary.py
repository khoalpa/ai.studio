from __future__ import annotations

from pathlib import Path

import run_phase4lr9r7r3r13_neutral_scale0375_canary as canary_supervisor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R18_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r18-delayed-bounded-conditioning-v1/phase4lr9r7r3r18-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r19-delayed-bounded-canary-v1"
SCHEDULE = [
    {"effective_step": 0, "scale": 0.0},
    {"effective_step": 8, "scale": 0.25},
    {"effective_step": 16, "scale": 0.0},
]


def configure() -> None:
    canary_supervisor.PRIOR_RESULT = R18_RESULT
    canary_supervisor.PRIOR_STATUS = "PASS_CLEAN_DELAYED_BOUNDED_WINDOW"
    canary_supervisor.PHASE = "4L-R9-R7-R3-R19"
    canary_supervisor.OUTPUT_ROOT = OUTPUT_ROOT
    canary_supervisor.CANDIDATE = (
        OUTPUT_ROOT / "candidates/neutral-identity/attempt-1.png"
    )
    canary_supervisor.ASSESSMENT_PATH = OUTPUT_ROOT / (
        "candidates/neutral-identity/attempt-1-assessment.json"
    )
    canary_supervisor.RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r19-result.json"
    canary_supervisor.WORKER_LOG = OUTPUT_ROOT / "worker.log"
    canary_supervisor.SCALE = 0.0
    canary_supervisor.SCALE_SCHEDULE = SCHEDULE
    canary_supervisor.ENTRYPOINT = Path(__file__).resolve()


def main() -> None:
    configure()
    canary_supervisor.main()


if __name__ == "__main__":
    main()
