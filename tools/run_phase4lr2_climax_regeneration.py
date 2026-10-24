from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from ai_story.image_qa import ImageQualityError
from ai_story.models import Profile
from ai_story.providers import landscape_provider
from ai_story.stage2.planning import create_visual_bible, create_visual_plan

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE4L = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1"
PHASE4K = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4k-promoted-cover-v1"
SOURCE_WORK = PHASE4L / "youth-torn-paper-boat/work"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr2-climax-v1"
SEED_ATTEMPT = 1


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
    gpu = gpu_status()
    result_path = OUTPUT_ROOT / "phase4lr2-result.json"
    if not gpu["exclusive_enough"]:
        result = {
            "schema_version": "1.0", "phase": "4L-R2",
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
    bible = create_visual_bible(story, "phase4lr2", Profile.YOUTH_SAFE, None)
    asset = next(item for item in plan["assets"] if item.get("basename") == "climax.png")
    shot = asset["shot_spec"]
    shot["pose_aware_scene_conditioning"] = True
    shot["regional_identity_conditioning"] = True
    shot["latent_props_disabled"] = False
    shot["composition_strength"] = 0.74
    shot["persist_candidates"] = True
    shot.pop("masked_prop_inpaint", None)
    shot["prompt_core"] = (
        "Exactly two people: Vietnamese boy Bo at left and his mother at right, seated "
        "close on the floor in a furnished Hanoi bedroom. Their natural hands meet at "
        "center and gently hold one tiny torn folded paper boat. No cup, mug, glass, tray, "
        "pedestal, extra object, extra hand, text, or cutout panel. Storybook 16:9."
    )
    if not any(item.get("character_id") == "me" for item in shot["subjects"]):
        shot["subjects"].append({
            "character_id": "me",
            "position": {"x": 0.58, "y": 0.78},
            "scale": "medium seated",
            "pose": "seated facing inward with one forearm reaching naturally",
            "gaze": "toward Bo and the paper boat",
            "reference_priority": [
                "face_closeup", "three_quarter", "full_body_front"
            ],
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
    shot["fidelity_probes"] = [
        {
            "probe_id": "person_count",
            "expected": "exactly one Vietnamese boy and his mother, two people",
            "forbidden": ["one person", "three or more people"],
        },
        {
            "probe_id": "two_hand_boat_contact",
            "expected": "two natural hands jointly holding one small folded paper boat",
            "forbidden": ["floating boat", "malformed hands", "extra hands"],
            "crop_box_normalized": [0.32, 0.42, 0.68, 0.76],
        },
        {
            "probe_id": "cup_absence",
            "expected": "a paper boat between hands with no cup",
            "forbidden": ["a cup", "a mug", "a drinking glass", "a pedestal", "a tray"],
            "crop_box_normalized": [0.32, 0.42, 0.68, 0.76],
        },
        {
            "probe_id": "prop_scale",
            "expected": "one tiny palm-sized folded paper boat",
            "forbidden": ["oversized paper boat", "full-size ship"],
            "crop_box_normalized": [0.32, 0.42, 0.68, 0.76],
        },
    ]
    references = [
        {"character_id": "bo", "view_id": "face_closeup", "data": (SOURCE_WORK / "characters/bo.png").read_bytes()},
        {"character_id": "me", "view_id": "face_closeup", "data": (SOURCE_WORK / "characters/me.png").read_bytes()},
    ]
    landscape, registry = landscape_provider("local", quality_preset="quality")
    candidate_path = OUTPUT_ROOT / "candidates/climax/attempt-1.png"
    assessment_path = OUTPUT_ROOT / "candidates/climax/attempt-1-assessment.json"
    try:
        data = landscape.generate(
            basename="climax.png",
            story=story,
            visual_plan_asset=asset,
            visual_bible=bible,
            attempt=SEED_ATTEMPT,
            reference_inputs=references,
        )
        assessment = landscape.assessment("climax.png")
        automatic_status = "ASSESSED_PASS"
    except ImageQualityError as exc:
        data = landscape.attempt_output("climax.png", SEED_ATTEMPT)
        assessment = exc.assessment
        automatic_status = "ASSESSED_FAIL"
    finally:
        landscape.assessor.unload()
        if registry is not None:
            registry.close()
    if not data:
        raise RuntimeError("Phase 4L-R2 did not return a candidate image")
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_bytes(data)
    write_json(assessment_path, assessment)
    result = {
        "schema_version": "1.0",
        "phase": "4L-R2",
        "status": "AWAITING_MANUAL_REVIEW" if automatic_status == "ASSESSED_PASS" else "BLOCKED",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "attempt_count": 1,
        "attempt": 1,
        "candidate_path": str(candidate_path.resolve()),
        "candidate_sha256": hashlib.sha256(data).hexdigest(),
        "assessment_path": str(assessment_path.resolve()),
        "automatic_status": automatic_status,
        "full_scene_regeneration_performed": True,
        "cup_forbidden_at_base_generation": True,
        "pose_aware_scene_conditioning": True,
        "regional_identity_assessment": True,
        "single_controlled_prop": "paper boat",
        "next_attempt_started": False,
        "phase4n_opened": False,
        "source_package_modified": False,
        "phase4k_cover_digest_preserved": (
            json.loads((PHASE4K / "phase4k-result.json").read_text(encoding="utf-8"))
            ["promotion"]["approved_cover_sha256"]
        ),
    }
    write_json(result_path, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
