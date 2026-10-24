from __future__ import annotations

from typing import Any

import run_phase4lr9r7r3r21r7r4r3_temporal_window_isolation as runner

R4_R4_RESULT = runner.BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r4-late-tail-micro-window-isolation-v1/"
    "phase4lr9r7r3r21r7r4r4-result.json"
)
EXPECTED_R4_R4_SHA256 = (
    "18b067c23498e5c7ed27a9873f1ebdb0beb8125588899ac3f222588a3b0a0bdc"
)


def validate_r4_r4(prior: dict[str, Any], prior_digest: str) -> None:
    if prior_digest != EXPECTED_R4_R4_SHA256:
        raise RuntimeError("R4-R4 checkpoint digest changed")
    if prior.get("status") != "PASS_DENOISE_TIME_WINDOW_ISOLATION":
        raise RuntimeError("R4-R4 no longer passes temporal isolation")
    if prior.get("eligible_profiles") != ["late_terminal"]:
        raise RuntimeError("R4-R4 eligible profile set changed")
    if prior.get("selected_profile") != "late_terminal":
        raise RuntimeError("R4-R4 terminal profile is no longer selected")
    terminal = prior["profiles"]["late_terminal"]
    if terminal.get("active_steps") != [22, 23] or not terminal.get("eligible"):
        raise RuntimeError("R4-R4 terminal profile is no longer eligible")


runner.R4_R2_RESULT = R4_R4_RESULT
runner.EXPECTED_R4_R2_SHA256 = EXPECTED_R4_R4_SHA256
runner.PHASE = "4L-R9-R7-R3-R21-R7-R4-R5"
runner.NEGATIVE_FIXTURE_FLAG = "terminal_profile_source_locked"
runner.OUTPUT_ROOT = runner.BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r5-terminal-profile-confirmation-v1"
)
runner.RESULT_PATH = runner.OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5-result.json"
runner.CACHE_ROOT = runner.OUTPUT_ROOT / "branch-cache"
runner.BASELINE_CACHE_FALLBACK = None
runner.SEED = 420918
runner.WINDOWS = {"confirmation": [22, 23]}
runner.validate_prior = validate_r4_r4


if __name__ == "__main__":
    runner.main()
