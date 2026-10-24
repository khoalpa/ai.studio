from __future__ import annotations

from pathlib import Path

import run_phase4lr9r7r3r21r7r4r5r3r6_structural_trajectory as runner

BASELINE_ROOT = runner.BASELINE_ROOT
R9_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r9-error-feedback-isolation-v1/phase4lr9r7r3r21r7r4r5r3r9-result.json"
)
R7_BASELINE_CACHE = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5r3r7-scale-terminal-isolation-v1/baseline-cache.pt"
)
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r10-error-feedback-trajectory-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r10-result.json"


def main() -> None:
    runner.R5_RESULT = R9_RESULT
    runner.OUTPUT_ROOT = OUTPUT_ROOT
    runner.RESULT_PATH = RESULT_PATH
    runner.PHASE = "4L-R9-R7-R3-R21-R7-R4-R5-R3-R10"
    runner.EXPECTED_PRIOR_STATUS = "PASS_ERROR_FEEDBACK_CAUSAL_ISOLATION"
    runner.EXPECTED_PRIOR_CLOSURE = "OPEN_PENDING_ERROR_FEEDBACK_TRAJECTORY"
    runner.BASELINE_CACHE_INPUT = Path(R7_BASELINE_CACHE)
    runner.BASELINE_CACHE_OUTPUT = None
    runner.EARLY_SCALE = 0.0025
    runner.MIDDLE_SCALE = 0.0025
    runner.TERMINAL_STEPS = []
    runner.TERMINAL_BLOCKS = []
    runner.TERMINAL_SCALE = 0.0
    runner.ERROR_FEEDBACK = True
    runner.main()


if __name__ == "__main__":
    main()
