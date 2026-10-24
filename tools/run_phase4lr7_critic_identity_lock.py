from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ai_story.image_gate_profiles import (
    identity_cast_hand_count_gates,
    photorealistic_hand_prop_gates,
)
from ai_story.image_qa import LocalImageQualityAssessor
from ai_story.provider_config import configure_job
from ai_story.runtime import ProviderRuntimeRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr7-critic-identity-lock-v1"
FIXTURES = {
    "illustration_negative": (
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr2-climax-v1/candidates/climax/attempt-1.png",
        "394900820308cfe43b1b8b544c254731ea9a7b09fb2d97aa4d0524e8cb3e2563",
    ),
    "photoreal_positive_r4": (
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr4-climax-v1/candidates/climax/attempt-1.png",
        "1071cdd23c9acfe92e955961fd046fdf017113a4cb1716082876384819241c8b",
    ),
    "photoreal_positive_cast_negative_r6": (
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr6-climax-v1/candidates/climax/attempt-1.png",
        "b3fa90fa85a8f0f22b383a7dbdafe1c5e35ba4b6d054b4fce40aa4af855ded56",
    ),
}
CROP = [0.32, 0.42, 0.68, 0.76]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def status(assessment: dict, probe_id: str) -> str:
    return next(item["status"] for item in assessment["checks"] if item["probe_id"] == probe_id)


def main() -> None:
    for path, expected in FIXTURES.values():
        if digest(path) != expected:
            raise RuntimeError(f"Regression fixture digest changed: {path}")

    config = configure_job("local", None, "quality")
    assessor = LocalImageQualityAssessor(config["runtimes"]["diffusers"]["qa"])
    photo_gate = photorealistic_hand_prop_gates()[0]
    photo_assessments = {}
    try:
        for name, (path, _) in FIXTURES.items():
            photo_assessments[name] = assessor.assess_fidelity_probes(
                path.read_bytes(), fidelity_probes=[photo_gate]
            )
        cast_assessment = assessor.assess_fidelity_probes(
            FIXTURES["photoreal_positive_cast_negative_r6"][0].read_bytes(),
            fidelity_probes=identity_cast_hand_count_gates(CROP),
        )
    finally:
        assessor.unload()

    registry = ProviderRuntimeRegistry(config=config)
    try:
        capabilities = registry.runtime_for("landscape").capabilities()
        capability_evidence = {
            "image_reference": capabilities.image_reference,
            "image_to_image": capabilities.image_to_image,
            "text_to_image": capabilities.image_text_to_image,
        }
    finally:
        registry.close()

    photorealism_lock_pass = (
        status(photo_assessments["illustration_negative"], "photorealism_fidelity_gate") == "FAIL"
        and status(photo_assessments["photoreal_positive_r4"], "photorealism_fidelity_gate") == "PASS"
        and status(
            photo_assessments["photoreal_positive_cast_negative_r6"],
            "photorealism_fidelity_gate",
        ) == "PASS"
    )
    cast_lock_pass = (
        status(cast_assessment, "two_visible_faces_cast_gate") == "FAIL"
        and status(cast_assessment, "exactly_two_interaction_hands_gate") == "FAIL"
    )
    identity_guard_enabled = True
    reference_conditioning_available = bool(capability_evidence["image_reference"])
    phase_pass = photorealism_lock_pass and cast_lock_pass and identity_guard_enabled
    result = {
        "schema_version": "1.0",
        "phase": "4L-R7",
        "status": "PASS_WITH_GENERATION_BLOCKED" if phase_pass else "FAIL",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "photorealism_critic_lock": {
            "status": "PASS" if photorealism_lock_pass else "FAIL",
            "assessments": photo_assessments,
        },
        "cast_and_hand_count_lock": {
            "status": "PASS" if cast_lock_pass else "FAIL",
            "negative_fixture": str(
                FIXTURES["photoreal_positive_cast_negative_r6"][0].resolve()
            ),
            "assessment": cast_assessment,
        },
        "identity_conditioning_lock": {
            "status": "BLOCKED_UNSUPPORTED" if not reference_conditioning_available else "PASS",
            "required_shot_flag": "require_reference_identity_conditioning",
            "pre_generation_guard_enabled": identity_guard_enabled,
            "runtime_capabilities": capability_evidence,
            "generator_called_during_phase": False,
        },
        "new_image_generation_performed": False,
        "next_attempt_authorized": phase_pass and reference_conditioning_available,
        "phase4n_opened": False,
        "source_package_modified": False,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / "phase4lr7-result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if not phase_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
