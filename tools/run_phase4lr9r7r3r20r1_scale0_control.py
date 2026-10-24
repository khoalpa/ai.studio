from __future__ import annotations

from pathlib import Path

import run_phase4lr9r7r3r20_locked_climax as control_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R20_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r20-locked-climax-v1/phase4lr9r7r3r20-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r20r1-scale0-control-v1"
SCHEDULE = [{"effective_step": 0, "scale": 0.0}]


def configure() -> None:
    control_runtime.PHASE = "4L-R9-R7-R3-R20-R1"
    control_runtime.PRIOR_RESULT = R20_RESULT
    control_runtime.PRIOR_STATUS = "AUTO_BLOCKED_PRE_DECODE"
    control_runtime.REQUIRE_AUTHORIZATION = False
    control_runtime.LATENT_ONLY = True
    control_runtime.SCHEDULE = SCHEDULE
    control_runtime.OUTPUT_ROOT = OUTPUT_ROOT
    control_runtime.CANDIDATE = OUTPUT_ROOT / "forbidden-candidate.png"
    control_runtime.ASSESSMENT_PATH = OUTPUT_ROOT / "forbidden-assessment.json"
    control_runtime.RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r20r1-result.json"
    control_runtime.WORKER_LOG = OUTPUT_ROOT / "worker.log"
    control_runtime.ENTRYPOINT = Path(__file__).resolve()


def main() -> None:
    configure()
    control_runtime.main()


if __name__ == "__main__":
    main()
