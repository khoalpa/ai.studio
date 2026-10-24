from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ai_story.image_gate_profiles import photorealistic_hand_prop_gates
from ai_story.image_qa import LocalImageQualityAssessor
from ai_story.provider_config import configure_job

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE4LR2 = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr2-climax-v1"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr3-critic-lock-v1"
CANDIDATE = PHASE4LR2 / "candidates/climax/attempt-1.png"
MANUAL_REVIEW = PHASE4LR2 / "candidates/climax/attempt-1-manual-review.json"
EXPECTED_NEGATIVE_SHA256 = "394900820308cfe43b1b8b544c254731ea9a7b09fb2d97aa4d0524e8cb3e2563"
INTERACTION_CROP = [1229, 907, 2611, 1642]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mandatory_gates() -> list[dict[str, object]]:
    return photorealistic_hand_prop_gates(crop_box_pixels=INTERACTION_CROP)


def main() -> None:
    data = CANDIDATE.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_NEGATIVE_SHA256:
        raise RuntimeError(f"Negative regression fixture digest changed: {digest}")
    manual_review = json.loads(MANUAL_REVIEW.read_text(encoding="utf-8"))
    if manual_review.get("status") != "MANUAL_REJECT":
        raise RuntimeError("Negative regression fixture is not backed by MANUAL_REJECT")

    config = configure_job("local", None, "quality")
    assessor = LocalImageQualityAssessor(config["runtimes"]["diffusers"]["qa"])
    try:
        assessment = assessor.assess_fidelity_probes(
            data, fidelity_probes=mandatory_gates()
        )
    finally:
        assessor.unload()

    failed = set(assessment["failed_probes"])
    required = {str(item["probe_id"]) for item in mandatory_gates()}
    regression_locked = assessment["status"] == "ASSESSED_FAIL" and failed == required
    result = {
        "schema_version": "1.0",
        "phase": "4L-R3",
        "status": "PASS" if regression_locked else "FAIL",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "purpose": "LOCK_FALSE_POSITIVE_BEFORE_ANY_NEW_GENERATION",
        "negative_fixture": str(CANDIDATE.resolve()),
        "negative_fixture_sha256": digest,
        "manual_review": str(MANUAL_REVIEW.resolve()),
        "manual_blockers": manual_review.get("blockers", []),
        "critic_assessment": assessment,
        "all_mandatory_gates_reject_negative": regression_locked,
        "new_image_generation_performed": False,
        "next_attempt_authorized": regression_locked,
        "phase4n_opened": False,
        "source_package_modified": False,
    }
    write_json(OUTPUT_ROOT / "phase4lr3-result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    if not regression_locked:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
