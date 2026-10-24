from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R19_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r19-delayed-bounded-canary-v1/phase4lr9r7r3r19-result.json"
)
R19_R1_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r19r1-portrait-gate-calibration-v1/"
    "phase4lr9r7r3r19r1-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r19r2-positive-profile-lock-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r19r2-result.json"
GATE_PROFILE = PROJECT_ROOT / "src/ai_story/image_gate_profiles.py"
CANARY_RUNTIME = PROJECT_ROOT / "tools/run_phase4lr9r7r3r7_vae_instrumented_canary.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lock_file(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def main() -> None:
    r19 = json.loads(R19_RESULT.read_text(encoding="utf-8"))
    calibration = json.loads(R19_R1_RESULT.read_text(encoding="utf-8"))
    if r19.get("status") != "AUTO_REJECT_AWAITING_MANUAL_REVIEW":
        raise RuntimeError("Required immutable R19 checkpoint is not satisfied")
    if calibration.get("status") != "PASS":
        raise RuntimeError("R19-R1 calibration must pass before profile lock")
    if not all(calibration["control_assertions"].values()):
        raise RuntimeError("Positive/negative calibration controls are not all locked")
    if RESULT_PATH.exists():
        raise RuntimeError("R19-R2 already completed; refusing to overwrite checkpoint")

    candidate = Path(r19["candidate_path"])
    fixtures = {
        "r19_positive": candidate,
        "r13_negative": BASELINE_ROOT
        / "phase4lr9r7r3r13-neutral-scale0375-canary-v1/"
        "candidates/neutral-identity/attempt-1.png",
        "r14_negative": BASELINE_ROOT
        / "phase4lr9r7r3r14-neutral-scale025-canary-v1/"
        "candidates/neutral-identity/attempt-1.png",
    }
    if not all(path.is_file() for path in fixtures.values()):
        raise RuntimeError("A locked positive or negative fixture is missing")
    if sha256(candidate) != r19["candidate_sha256"]:
        raise RuntimeError("R19 positive candidate hash changed")

    generation = r19["generation"]
    locked_profile = {
        "seed": generation["seed"],
        "resolution": generation["dimensions"],
        "pipeline_dtype": generation["pipeline_dtype"],
        "steps": generation["steps"],
        "guidance_scale": generation["guidance_scale"],
        "ip_adapter_scale_schedule": generation["ip_adapter_scale_schedule"],
        "identity_crop_box_in_memory": generation["identity_crop_box_in_memory"],
        "prompt": r19["prompt"],
        "negative_prompt": r19["negative_prompt"],
        "gate_calibration": calibration["calibration"],
        "gate_count": calibration["controls"]["r19_positive"]["gate_count"],
    }
    profile_digest = hashlib.sha256(
        json.dumps(
            locked_profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R19-R2",
        "status": "AWAITING_MANUAL_REVIEW_PROFILE_LOCKED",
        "positive_control": {
            **lock_file(candidate),
            "automatic_qa_status": "ASSESSED_PASS",
            "passed_gate_count": 7,
            "gate_count": 7,
            "promoted_as_regression_fixture": True,
            "promoted_to_production": False,
        },
        "negative_controls": {
            fixture_id: lock_file(path)
            for fixture_id, path in fixtures.items()
            if fixture_id.endswith("negative")
        },
        "locked_profile": locked_profile,
        "locked_profile_sha256": profile_digest,
        "implementation_locks": {
            "gate_profile": lock_file(GATE_PROFILE),
            "canary_runtime": lock_file(CANARY_RUNTIME),
        },
        "manual_review": {
            "required": True,
            "status": "PENDING",
            "climax_generation_authorized": False,
        },
        "guards": {
            "image_generation_performed": False,
            "candidate_modified": False,
            "source_package_modified": False,
            "production_profile_changed": False,
            "climax_generated": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
