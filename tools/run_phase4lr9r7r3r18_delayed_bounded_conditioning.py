from __future__ import annotations

from pathlib import Path

import run_phase4lr9r7r3r16_late_tail_adapter_cutoff as window_supervisor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R17_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r17-midpoint-conditioning-window-v1/phase4lr9r7r3r17-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r18-delayed-bounded-conditioning-v1"
SCHEDULE = [
    {"effective_step": 0, "scale": 0.0},
    {"effective_step": 8, "scale": 0.25},
    {"effective_step": 16, "scale": 0.0},
]


def configure() -> None:
    window_supervisor.PRIOR_RESULT = R17_RESULT
    window_supervisor.PRIOR_STATUS = "PASS_BLOCKED_MIDPOINT_CUTOFF"
    window_supervisor.PHASE = "4L-R9-R7-R3-R18"
    window_supervisor.CLEAN_STATUS = "PASS_CLEAN_DELAYED_BOUNDED_WINDOW"
    window_supervisor.BLOCKED_STATUS = "PASS_BLOCKED_DELAYED_BOUNDED_WINDOW"
    window_supervisor.OUTPUT_ROOT = OUTPUT_ROOT
    window_supervisor.RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r18-result.json"
    window_supervisor.WORKER_LOG = OUTPUT_ROOT / "worker.log"
    window_supervisor.EARLY_SCALE = 0.0
    window_supervisor.LATE_SCALE = 0.0
    window_supervisor.CUTOFF_STEP = 16
    window_supervisor.ADAPTER_SCALE_SCHEDULE = SCHEDULE
    window_supervisor.ENTRYPOINT = Path(__file__).resolve()


def main() -> None:
    configure()
    window_supervisor.main()


if __name__ == "__main__":
    main()
