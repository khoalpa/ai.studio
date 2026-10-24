from __future__ import annotations

import json
from pathlib import Path

import run_phase4lr9r7r3r21r7r4r5r3r6_structural_trajectory as runner

BASELINE_ROOT = runner.BASELINE_ROOT
R6_RESULT = runner.RESULT_PATH
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r7-scale-terminal-isolation-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r7-result.json"
CACHE_PATH = OUTPUT_ROOT / "baseline-cache.pt"


def run_profile(profile_id: str, terminal: bool, baseline_input: Path | None) -> Path:
    profile_root = OUTPUT_ROOT / profile_id
    runner.R5_RESULT = R6_RESULT
    runner.OUTPUT_ROOT = profile_root
    runner.RESULT_PATH = profile_root / "result.json"
    runner.PHASE = f"4L-R9-R7-R3-R21-R7-R4-R5-R3-R7-{profile_id.upper()}"
    runner.EXPECTED_PRIOR_STATUS = "FAIL"
    runner.EXPECTED_PRIOR_CLOSURE = "OPEN_PENDING_TRAJECTORY_REPAIR"
    runner.EARLY_SCALE = 0.000625
    runner.MIDDLE_SCALE = 0.00125
    runner.TERMINAL_STEPS = [22, 23] if terminal else []
    runner.TERMINAL_BLOCKS = list(range(28, 38)) if terminal else []
    runner.TERMINAL_SCALE = 0.0025 if terminal else 0.0
    runner.BASELINE_CACHE_INPUT = baseline_input
    runner.BASELINE_CACHE_OUTPUT = CACHE_PATH if baseline_input is None else None
    try:
        runner.main()
    except SystemExit as error:
        if error.code != 1:
            raise
    return runner.RESULT_PATH


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R7 checkpoint already exists; refusing to overwrite")
    a_path = run_profile("a_half_scale", False, None)
    b_path = run_profile("b_half_scale_terminal", True, CACHE_PATH)
    profiles = {
        "a_half_scale": json.loads(a_path.read_text(encoding="utf-8")),
        "b_half_scale_terminal": json.loads(b_path.read_text(encoding="utf-8")),
    }
    eligible = [name for name, value in profiles.items() if value["status"].startswith("PASS_")]
    selected = (
        max(
            eligible,
            key=lambda name: profiles[name]["comparison"]["final_spatial_ratio"],
        )
        if eligible
        else None
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R7",
        "status": "PASS_SCALE_TERMINAL_TRAJECTORY_ISOLATION" if selected else "FAIL",
        "baseline_cache": str(CACHE_PATH.resolve()),
        "profiles": {
            name: {
                "result_path": str(path.resolve()),
                "status": profiles[name]["status"],
                "gates": profiles[name]["gates"],
                "comparison": profiles[name]["comparison"],
                "latent_critics": {
                    "baseline": profiles[name]["baseline"]["latent_critic"],
                    "active": profiles[name]["active"]["latent_critic"],
                    "paired": profiles[name]["paired_critic"],
                },
            }
            for name, path in (
                ("a_half_scale", a_path),
                ("b_half_scale_terminal", b_path),
            )
        },
        "eligible_profiles": eligible,
        "selected_profile": selected,
        "phase4l_closure": {
            "status": (
                "OPEN_PENDING_DECODE_AUTHORIZATION_REVIEW"
                if selected
                else "OPEN_PENDING_TRAJECTORY_REPAIR"
            ),
            "all_requirements_satisfied": False,
        },
        "guards": {
            "total_trajectory_count": 3,
            "baseline_reused_for_profile_b": True,
            "vae_calls": {"forward": 0, "decode": 0},
            "images_created": 0,
            "decode_authorized": False,
            "new_generation_authorized": False,
            "production_profile_changed": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if selected is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
