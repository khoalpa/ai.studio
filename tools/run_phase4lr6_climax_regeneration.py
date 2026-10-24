from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from ai_story.image_gate_profiles import (
    PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
    PHOTOREALISTIC_INTERACTION_PROMPT,
    photorealistic_hand_prop_gates,
)
from ai_story.image_qa import ImageQualityError
from ai_story.models import Profile
from ai_story.providers import landscape_provider
from ai_story.stage2.planning import create_visual_bible, create_visual_plan

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE4L = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1"
PHASE4LR5 = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr5-critic-prompt-lock-v1"
SOURCE_WORK = PHASE4L / "youth-torn-paper-boat/work"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr6-climax-v1"
ATTEMPT = 1


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def gpu_status() -> dict[str, int | bool]:
    completed = subprocess.run(
        [
            "nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True, capture_output=True, text=True,
    )
    utilization, used, total = [
        int(value.strip()) for value in completed.stdout.strip().split(",")
    ]
    return {
        "utilization_percent": utilization,
        "memory_used_mib": used,
        "memory_total_mib": total,
        "exclusive_enough": utilization <= 30 and used <= 4096,
    }


def main() -> None:
    lock_path = PHASE4LR5 / "phase4lr5-result.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if not (
        lock.get("status") == "PASS"
        and lock.get("critic_calibration", {}).get("status") == "PASS"
        and lock.get("prompt_budget_lock", {}).get("status") == "PASS"
        and lock.get("next_attempt_authorized") is True
    ):
        raise RuntimeError("Phase 4L-R5 critic and prompt locks are not valid")

    result_path = OUTPUT_ROOT / "phase4lr6-result.json"
    gpu = gpu_status()
    if not gpu["exclusive_enough"]:
        result = {
            "schema_version": "1.0", "phase": "4L-R6",
            "status": "WAITING_FOR_EXCLUSIVE_GPU", "gpu": gpu,
            "generation_performed": False, "phase4n_opened": False,
        }
        write_json(result_path, result)
        print(json.dumps(result, ensure_ascii=False))
        return

    story = json.loads((SOURCE_WORK / "story.json").read_text(encoding="utf-8"))
    validation = json.loads(
        (SOURCE_WORK / "story_validation.json").read_text(encoding="utf-8")
    )
    story_digest = str(validation.get("story_sha256", ""))
    plan = create_visual_plan(story, validation, story_digest, story_digest)
    bible = create_visual_bible(story, "phase4lr6", Profile.YOUTH_SAFE, None)
    bible["art_direction_id"] = "photorealistic-natural"
    bible["tonal_plan"]["palette"] = ["warm neutral", "natural skin", "soft daylight"]
    asset = next(item for item in plan["assets"] if item.get("basename") == "climax.png")
    shot = asset["shot_spec"]
    shot["disable_composition_canvas_fallback"] = True
    shot["pose_aware_scene_conditioning"] = False
    shot["regional_identity_conditioning"] = True
    shot["latent_props_disabled"] = False
    shot["persist_candidates"] = True
    shot.pop("masked_prop_inpaint", None)
    shot["prompt_core"] = PHOTOREALISTIC_INTERACTION_PROMPT
    shot["prompt_style_suffix"] = ""
    shot["negative_prompt_override"] = PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT
    if not any(item.get("character_id") == "me" for item in shot["subjects"]):
        shot["subjects"].append({
            "character_id": "me", "position": {"x": 0.58, "y": 0.78},
            "scale": "medium seated", "pose": "seated facing inward",
            "gaze": "toward Bo and the paper boat",
        })
    asset["focal_character_ids"] = ["bo", "me"]
    subjects = {item["character_id"]: item for item in shot["subjects"]}
    for character_id, x in (("bo", 0.42), ("me", 0.58)):
        subject = subjects[character_id]
        subject["position"] = {"x": x, "y": 0.78}
        subject["scale"] = "medium seated"
        subject["pose"] = "seated facing inward with one forearm reaching naturally"
        subject["interaction_target"] = {"x": 0.50, "y": 0.62}
        subject["identity_region_width"] = 0.24
        subject["identity_region_height"] = 0.60
    shot["prop_layout"] = [{
        "name": "paper boat", "position": {"x": 0.50, "y": 0.62},
        "relative_width": 0.035,
    }]
    shot["required_elements"] = ["character:bo", "character:me", "prop:paper boat"]
    shot["forbidden_elements"] = ["uncontrolled_text", "watermark"]
    interaction_crop = [0.32, 0.42, 0.68, 0.76]
    mandatory_gates = photorealistic_hand_prop_gates(
        crop_box_normalized=interaction_crop, include_prop_shape_scale=True
    )
    shot["fidelity_probes"] = mandatory_gates + [
        {
            "probe_id": "person_count",
            "expected": "exactly one Vietnamese boy and his mother, two people",
            "forbidden": ["one person", "three or more people"],
        },
        {
            "probe_id": "cup_absence",
            "expected": "a paper boat between hands with no cup",
            "forbidden": ["a cup", "a mug", "a drinking glass", "a pedestal", "a tray"],
            "crop_box_normalized": interaction_crop,
        },
    ]
    references = [
        {"character_id": "bo", "view_id": "face_closeup", "data": (SOURCE_WORK / "characters/bo.png").read_bytes()},
        {"character_id": "me", "view_id": "face_closeup", "data": (SOURCE_WORK / "characters/me.png").read_bytes()},
    ]
    landscape, registry = landscape_provider("local", quality_preset="quality")
    candidate_path = OUTPUT_ROOT / "candidates/climax/attempt-1.png"
    assessment_path = OUTPUT_ROOT / "candidates/climax/attempt-1-assessment.json"
    gates_path = OUTPUT_ROOT / "candidates/climax/attempt-1-mandatory-gates.json"
    try:
        data = landscape.generate(
            basename="climax.png", story=story, visual_plan_asset=asset,
            visual_bible=bible, attempt=ATTEMPT, reference_inputs=references,
        )
        assessment = landscape.assessment("climax.png")
        automatic_status = "ASSESSED_PASS"
        gate_assessment = assessment.get("visual_fidelity", {})
    except ImageQualityError as exc:
        data = landscape.attempt_output("climax.png", ATTEMPT)
        assessment = exc.assessment
        automatic_status = "ASSESSED_FAIL"
        gate_assessment = landscape.assessor.assess_fidelity_probes(
            data, fidelity_probes=mandatory_gates
        )
    finally:
        landscape.assessor.unload()
        if registry is not None:
            registry.close()
    if not data:
        raise RuntimeError("Phase 4L-R6 did not return a candidate image")
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_bytes(data)
    write_json(assessment_path, assessment)
    write_json(gates_path, gate_assessment)
    status = "AWAITING_MANUAL_REVIEW" if automatic_status == "ASSESSED_PASS" else "AUTO_REJECT"
    failed_gates = gate_assessment.get("failed_probes", [])
    result = {
        "schema_version": "1.0", "phase": "4L-R6", "status": status,
        "case_id": "youth-torn-paper-boat", "role": "CLIMAX",
        "attempt_count": 1, "attempt": ATTEMPT,
        "candidate_path": str(candidate_path.resolve()),
        "candidate_sha256": hashlib.sha256(data).hexdigest(),
        "assessment_path": str(assessment_path.resolve()),
        "mandatory_gate_assessment_path": str(gates_path.resolve()),
        "automatic_status": automatic_status,
        "critic_prompt_lock": str(lock_path.resolve()),
        "prompt": PHOTOREALISTIC_INTERACTION_PROMPT,
        "negative_prompt": PHOTOREALISTIC_INTERACTION_NEGATIVE_PROMPT,
        "mandatory_gate_ids": [item["probe_id"] for item in mandatory_gates],
        "failed_mandatory_gate_ids": failed_gates,
        "candidate_promotable": automatic_status == "ASSESSED_PASS",
        "manual_review_required": automatic_status == "ASSESSED_PASS",
        "full_scene_regeneration_performed": True,
        "composition_canvas_fallback_disabled": True,
        "prompt_truncation_guard_enabled": True,
        "art_direction": "photorealistic-natural",
        "next_attempt_started": False,
        "phase4n_opened": False,
        "source_package_modified": False,
    }
    write_json(result_path, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
