from __future__ import annotations

import hashlib
import json
from pathlib import Path

from transformers import CLIPTokenizer

from ai_story.image_gate_profiles import (
    PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
    PHOTOREALISTIC_INTERACTION_PROMPT,
    photorealistic_hand_prop_gates,
)
from ai_story.image_qa import LocalImageQualityAssessor
from ai_story.provider_config import configure_job

PROJECT_ROOT = Path(__file__).resolve().parents[1]
R2_CANDIDATE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr2-climax-v1/candidates/climax/attempt-1.png"
R4_CANDIDATE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr4-climax-v1/candidates/climax/attempt-1.png"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr5-critic-prompt-lock-v1"
R2_SHA256 = "394900820308cfe43b1b8b544c254731ea9a7b09fb2d97aa4d0524e8cb3e2563"
R4_SHA256 = "1071cdd23c9acfe92e955961fd046fdf017113a4cb1716082876384819241c8b"
CROP = [0.32, 0.42, 0.68, 0.76]
R4_OVERFLOW_PROMPT = (
    "Candid family photo in a furnished Hanoi bedroom. Exactly two people: Vietnamese "
    "boy Bo at left and his mother at right, seated close on the floor. Each extends one "
    "visible anatomically natural hand, touching opposite edges of one tiny torn folded "
    "paper boat at center. Real skin texture, distinct fingers, connected wrists, soft "
    "window light, shallow camera depth. No cup, mug, glass, tray, pedestal, extra object, "
    "extra hand, illustration, cartoon, ink outline, text, watermark. "
    "Photorealistic natural 16:9 editorial photograph."
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def token_evidence(tokenizer, text: str) -> dict[str, int | bool]:
    token_ids = tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"]
    limit = int(tokenizer.model_max_length)
    return {"count": len(token_ids), "limit": limit, "within_budget": len(token_ids) <= limit}


def check_status(assessment: dict, probe_id: str) -> str:
    return next(item["status"] for item in assessment["checks"] if item["probe_id"] == probe_id)


def main() -> None:
    if sha256(R2_CANDIDATE) != R2_SHA256 or sha256(R4_CANDIDATE) != R4_SHA256:
        raise RuntimeError("Phase 4L regression fixture digest changed")

    config = configure_job("local", None, "quality")
    assessor = LocalImageQualityAssessor(config["runtimes"]["diffusers"]["qa"])
    r2_gates = photorealistic_hand_prop_gates(crop_box_normalized=CROP)
    r4_gates = photorealistic_hand_prop_gates(
        crop_box_normalized=CROP, include_prop_shape_scale=True
    )
    try:
        r2 = assessor.assess_fidelity_probes(
            R2_CANDIDATE.read_bytes(), fidelity_probes=r2_gates
        )
        r4 = assessor.assess_fidelity_probes(
            R4_CANDIDATE.read_bytes(), fidelity_probes=r4_gates
        )
    finally:
        assessor.unload()

    selected = config["selected"]["landscape"]
    model_id = config["adapters"][selected]["model_id"]
    tokenizer = CLIPTokenizer.from_pretrained(
        model_id, subfolder="tokenizer", local_files_only=True
    )
    prompt_budget = token_evidence(tokenizer, PHOTOREALISTIC_INTERACTION_PROMPT)
    negative_budget = token_evidence(
        tokenizer, PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT
    )
    overflow_control = token_evidence(tokenizer, R4_OVERFLOW_PROMPT)

    calibration_pass = (
        check_status(r2, "photorealism_fidelity_gate") == "FAIL"
        and check_status(r4, "photorealism_fidelity_gate") == "PASS"
        and check_status(r4, "hand_anatomy_gate") == "FAIL"
        and check_status(r4, "hand_prop_contact_gate") == "FAIL"
        and check_status(r4, "paper_boat_shape_scale_gate") == "FAIL"
    )
    prompt_lock_pass = bool(
        prompt_budget["within_budget"]
        and negative_budget["within_budget"]
        and not overflow_control["within_budget"]
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R5",
        "status": "PASS" if calibration_pass and prompt_lock_pass else "FAIL",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "critic_calibration": {
            "status": "PASS" if calibration_pass else "FAIL",
            "illustration_negative_control": {
                "path": str(R2_CANDIDATE.resolve()), "sha256": R2_SHA256,
                "assessment": r2,
            },
            "photorealism_positive_hand_prop_negative_control": {
                "path": str(R4_CANDIDATE.resolve()), "sha256": R4_SHA256,
                "assessment": r4,
            },
        },
        "prompt_budget_lock": {
            "status": "PASS" if prompt_lock_pass else "FAIL",
            "prompt": PHOTOREALISTIC_INTERACTION_PROMPT,
            "prompt_tokens": prompt_budget,
            "negative_prompt": PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
            "negative_prompt_tokens": negative_budget,
            "overflow_negative_control": {
                "source": "4L-R4_GENERATION_PROMPT",
                "tokens": overflow_control,
                "runtime_guard_expected_outcome": "REJECT_BEFORE_INFERENCE",
            },
            "runtime_truncation_guard_enabled": True,
        },
        "new_image_generation_performed": False,
        "next_attempt_authorized": calibration_pass and prompt_lock_pass,
        "phase4n_opened": False,
        "source_package_modified": False,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / "phase4lr5-result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
