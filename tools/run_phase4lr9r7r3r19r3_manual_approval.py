from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R19_R2_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r19r2-positive-profile-lock-v1/phase4lr9r7r3r19r2-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r19r3-manual-approval-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r19r3-result.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_lock(lock: dict[str, str], label: str) -> None:
    path = Path(lock["path"])
    if not path.is_file() or sha256(path) != lock["sha256"]:
        raise RuntimeError(f"Locked {label} is missing or changed")


def main() -> None:
    prior = json.loads(R19_R2_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "AWAITING_MANUAL_REVIEW_PROFILE_LOCKED":
        raise RuntimeError("Required R19-R2 checkpoint is not satisfied")
    if prior["manual_review"] != {
        "required": True,
        "status": "PENDING",
        "climax_generation_authorized": False,
    }:
        raise RuntimeError("R19-R2 manual-review guard is not intact")
    if RESULT_PATH.exists():
        raise RuntimeError("R19-R3 already completed; refusing to overwrite checkpoint")

    assert_lock(prior["positive_control"], "R19 positive control")
    for fixture_id, lock in prior["negative_controls"].items():
        assert_lock(lock, fixture_id)
    for implementation_id, lock in prior["implementation_locks"].items():
        assert_lock(lock, implementation_id)

    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R19-R3",
        "status": "MANUAL_APPROVE_ONE_CLIMAX_ATTEMPT_AUTHORIZED",
        "manual_review": {
            "status": "MANUAL_APPROVE",
            "basis": "DIRECT_VISUAL_INSPECTION_OF_LOCKED_R19_POSITIVE_CONTROL",
            "checklist": {
                "single_subject": "PASS",
                "identity_consistency": "PASS",
                "photorealism": "PASS",
                "face_neck_anatomy": "PASS",
                "horizontal_fragmentation_absent": "PASS",
                "text_artifact_absent": "PASS",
                "portrait_framing": "PASS",
            },
            "candidate_sha256": prior["positive_control"]["sha256"],
        },
        "locked_profile_sha256": prior["locked_profile_sha256"],
        "locked_profile": prior["locked_profile"],
        "fixture_locks": {
            "positive": prior["positive_control"],
            "negatives": prior["negative_controls"],
            "implementation": prior["implementation_locks"],
        },
        "authorization": {
            "target": "youth-torn-paper-boat/climax.png",
            "maximum_attempts": 1,
            "attempts_consumed": 0,
            "full_scene_only": True,
            "profile_override_allowed": False,
            "automatic_qa_required": True,
            "manual_review_after_generation_required": True,
            "authorized": True,
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
