from __future__ import annotations

from typing import Any

import run_phase4lr9r7r3r21r7r4r3_temporal_window_isolation as runner

R4_R3_RESULT = runner.BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r3-temporal-window-isolation-v1/"
    "phase4lr9r7r3r21r7r4r3-result.json"
)
EXPECTED_R4_R3_SHA256 = (
    "8646c1104d6d9ccf304aa9d4658ae5e6bc2183d8dc589275f96564d0b2e2a7fb"
)


def validate_r4_r3(prior: dict[str, Any], prior_digest: str) -> None:
    if prior_digest != EXPECTED_R4_R3_SHA256 or prior.get("status") != "FAIL":
        raise RuntimeError("R4-R3 temporal-window negative fixture changed")
    if prior.get("eligible_profiles") != [] or prior.get("selected_profile") is not None:
        raise RuntimeError("R4-R3 no longer rejects every coarse temporal window")
    if any(profile.get("eligible") for profile in prior["profiles"].values()):
        raise RuntimeError("R4-R3 contains an unexpectedly eligible profile")


runner.R4_R2_RESULT = R4_R3_RESULT
runner.EXPECTED_R4_R2_SHA256 = EXPECTED_R4_R3_SHA256
runner.PHASE = "4L-R9-R7-R3-R21-R7-R4-R4"
runner.NEGATIVE_FIXTURE_FLAG = "coarse_temporal_profiles_forbidden"
runner.OUTPUT_ROOT = runner.BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r4r4-late-tail-micro-window-isolation-v1"
)
runner.RESULT_PATH = runner.OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r4-result.json"
runner.CACHE_ROOT = runner.OUTPUT_ROOT / "branch-cache"
runner.BASELINE_CACHE_FALLBACK = R4_R3_RESULT.parent / "branch-cache/baseline.pt"
runner.WINDOWS = {
    "late_early": list(range(16, 20)),
    "late_middle": list(range(20, 22)),
    "late_terminal": list(range(22, 24)),
}
runner.validate_prior = validate_r4_r3


if __name__ == "__main__":
    runner.main()
