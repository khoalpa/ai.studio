from __future__ import annotations

from pathlib import Path

import run_phase4lr9r7r3r16_late_tail_adapter_cutoff as cutoff_supervisor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R16_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r16-late-tail-adapter-cutoff-v1/phase4lr9r7r3r16-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r17-midpoint-conditioning-window-v1"


def configure() -> None:
    cutoff_supervisor.PRIOR_RESULT = R16_RESULT
    cutoff_supervisor.PRIOR_STATUS = "PASS_BLOCKED_LATE_TAIL_CUTOFF"
    cutoff_supervisor.PHASE = "4L-R9-R7-R3-R17"
    cutoff_supervisor.CLEAN_STATUS = "PASS_CLEAN_MIDPOINT_CUTOFF"
    cutoff_supervisor.BLOCKED_STATUS = "PASS_BLOCKED_MIDPOINT_CUTOFF"
    cutoff_supervisor.OUTPUT_ROOT = OUTPUT_ROOT
    cutoff_supervisor.RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r17-result.json"
    cutoff_supervisor.WORKER_LOG = OUTPUT_ROOT / "worker.log"
    cutoff_supervisor.EARLY_SCALE = 0.25
    cutoff_supervisor.LATE_SCALE = 0.0
    cutoff_supervisor.CUTOFF_STEP = 8
    cutoff_supervisor.ENTRYPOINT = Path(__file__).resolve()


def main() -> None:
    configure()
    cutoff_supervisor.main()


if __name__ == "__main__":
    main()
