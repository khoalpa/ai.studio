from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from ai_story.image_qa import ImageQualityError, LocalImageQualityAssessor
from ai_story.provider_config import load_provider_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE3R = (
    PROJECT_ROOT
    / "artifacts/baselines/real-v1/story/phase3/phase3r-locked-recovery-baseline/manifest.json"
)
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4a"
CANARY_IDS = {
    "youth-torn-paper-boat",
    "youth-lost-kite",
    "youth-lost-bird-rain",
    "youth-negative-storm-template-hijack",
    "adult-memory-choice",
    "adult-five-characters",
    "serial-locked-room",
    "serial-four-suspects",
}
EXPECTED_SCENE_ASSETS_PER_PACKAGE = 20


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prompt_for(character: dict[str, Any]) -> str:
    visual = character.get("visual_identity", {})
    return ", ".join(
        str(value)
        for value in (
            character.get("name"),
            character.get("role"),
            visual.get("presentation"),
            visual.get("hair"),
            visual.get("wardrobe"),
            visual.get("silhouette"),
            visual.get("cultural_context"),
        )
        if value
    )


def review_template(reviewer_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "report_kind": "PHASE4A_BLIND_VISUAL_REVIEW",
        "reviewer_id": reviewer_id,
        "rubric": {
            "score_min": 1,
            "score_max": 5,
            "dimensions": [
                "prompt_adherence",
                "character_consistency",
                "composition",
                "anatomy_and_artifacts",
                "aesthetic_quality",
            ],
            "blocker_codes": [
                "WRONG_CHARACTER_IDENTITY",
                "UNCONTROLLED_TEXT",
                "SEVERE_ANATOMY_DEFECT",
                "CULTURAL_CONTEXT_MISMATCH",
            ],
        },
        "items": [
            {
                **item,
                "scores": {
                    "prompt_adherence": None,
                    "character_consistency": None,
                    "composition": None,
                    "anatomy_and_artifacts": None,
                    "aesthetic_quality": None,
                },
                "blockers": [],
                "notes": "",
            }
            for item in items
        ],
    }


def main() -> None:
    baseline = json.loads(PHASE3R.read_text(encoding="utf-8"))
    production = [
        item for item in baseline["packages"]
        if item["classification"] == "PRODUCTION_READY"
    ]
    if len(production) != 24:
        raise RuntimeError(f"Expected 24 production-ready packages, got {len(production)}")

    qa_settings = load_provider_config("local")["runtimes"]["diffusers"]["qa"]
    assessor = LocalImageQualityAssessor(qa_settings)
    expected_dimensions = (1536, 2048)
    records_dir = OUTPUT_ROOT / "records"
    review_assets = OUTPUT_ROOT / "review_assets"
    records_dir.mkdir(parents=True, exist_ok=True)
    review_assets.mkdir(parents=True, exist_ok=True)
    package_records = []
    review_items = []
    counts: Counter[str] = Counter()
    technical_failures = semantic_failures = identity_failures = 0
    existing_images = missing_scene_images = 0

    try:
        for package_entry in production:
            case_id = str(package_entry["case_id"])
            package_path = Path(package_entry["locked_package"])
            assets = []
            package_classes: set[str] = set()
            with zipfile.ZipFile(package_path) as archive:
                story = json.loads(archive.read("story.json"))
                members = set(archive.namelist())
                for index, character in enumerate(story.get("characters", [])):
                    reference = character["reference_asset"]
                    member = str(reference["reference_image"])
                    locator = f"story.characters[{index}].reference_asset.reference_image"
                    if member not in members:
                        classification = "TECHNICAL_REPAIR_ONLY"
                        assessment = {"status": "FAIL", "findings": [{"error": "IMAGE_MISSING"}]}
                        identity = {"status": "NOT_ASSESSED", "findings": []}
                        data = b""
                    else:
                        data = archive.read(member)
                        try:
                            assessment = assessor.assess(
                                data,
                                prompt=prompt_for(character),
                                expected_dimensions=expected_dimensions,
                                asset_type="character",
                            )
                        except ImageQualityError as exc:
                            assessment = exc.assessment
                        try:
                            identity = assessor.assess_character_identity(
                                data, character=character,
                            )
                        except Exception as exc:
                            identity = {
                                "status": "NOT_ASSESSED",
                                "findings": [{"error": "IDENTITY_ASSESSOR_ERROR", "detail": str(exc)}],
                            }
                        layers = {
                            str(item.get("layer")): str(item.get("status"))
                            for item in assessment.get("qa_layers", [])
                        }
                        if assessment.get("status") != "ASSESSED_PASS" and layers.get("TECHNICAL") == "FAIL":
                            classification = "TECHNICAL_REPAIR_ONLY"
                            technical_failures += 1
                        elif identity.get("status") in {"ASSESSED_FAIL", "FAIL"}:
                            classification = "IDENTITY_REGEN_REQUIRED"
                            identity_failures += 1
                        elif assessment.get("status") != "ASSESSED_PASS":
                            classification = "SEMANTIC_REGEN_REQUIRED"
                            semantic_failures += 1
                        else:
                            classification = "VISUAL_READY"
                    package_classes.add(classification)
                    counts[classification] += 1
                    existing_images += bool(data)
                    asset = {
                        "asset_type": "CHARACTER_REFERENCE",
                        "character_id": character.get("character_id"),
                        "character_name": character.get("name"),
                        "locator": locator,
                        "archive_path": member,
                        "file_sha256": sha256(data) if data else None,
                        "declared_file_sha256": reference.get("file_sha256"),
                        "classification": classification,
                        "technical_semantic_assessment": assessment,
                        "identity_assessment": identity,
                    }
                    assets.append(asset)
                    if case_id in CANARY_IDS and data:
                        target_dir = review_assets / case_id
                        target_dir.mkdir(parents=True, exist_ok=True)
                        target = target_dir / Path(member).name
                        target.write_bytes(data)
                        review_items.append({
                            "case_id": case_id,
                            "character_id": character.get("character_id"),
                            "character_name": character.get("name"),
                            "image_path": str(target.resolve()),
                            "image_sha256": sha256(data),
                            "source_locator": locator,
                        })

            missing = [
                {
                    "asset_type": orientation,
                    "locator": (
                        f"visual_plan.assets[{asset_index}]."
                        f"{orientation.lower()}_image"
                    ),
                    "classification": "SEMANTIC_REGEN_REQUIRED",
                    "reason": "STAGE3_SCENE_ASSETS_NOT_GENERATED",
                }
                for orientation in ("LANDSCAPE", "PORTRAIT")
                for asset_index in range(EXPECTED_SCENE_ASSETS_PER_PACKAGE // 2)
            ]
            missing_scene_images += len(missing)
            package_classes.add("SEMANTIC_REGEN_REQUIRED")
            severity = [
                "VISUAL_READY", "TECHNICAL_REPAIR_ONLY",
                "SEMANTIC_REGEN_REQUIRED", "IDENTITY_REGEN_REQUIRED",
            ]
            package_class = max(package_classes, key=severity.index)
            record = {
                "schema_version": "1.0",
                "case_id": case_id,
                "profile": package_entry["profile"],
                "source_package": str(package_path.resolve()),
                "source_package_sha256": package_entry["file_sha256"],
                "package_classification": package_class,
                "existing_assets": assets,
                "missing_stage3_assets": missing,
            }
            (records_dir / f"{case_id}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            package_records.append(record)
    finally:
        assessor.unload()

    review_dir = OUTPUT_ROOT / "human_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    for reviewer_id in ("reviewer-a", "reviewer-b"):
        (review_dir / f"{reviewer_id}.json").write_text(
            json.dumps(review_template(reviewer_id, review_items), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    report = {
        "schema_version": "1.0",
        "report_kind": "PHASE4A_VISUAL_INVENTORY",
        "source_baseline": str(PHASE3R.resolve()),
        "policy": {
            "image_generation_used": False,
            "source_packages_modified": False,
            "semantic_assessment_rerun": True,
            "negative_fixtures_excluded": True,
        },
        "package_count": len(package_records),
        "canary_case_ids": sorted(CANARY_IDS),
        "metrics": {
            "existing_character_image_count": existing_images,
            "missing_stage3_image_count": missing_scene_images,
            "technical_failure_count": technical_failures,
            "semantic_failure_count": semantic_failures,
            "identity_failure_count": identity_failures,
            "existing_asset_classification_counts": dict(sorted(counts.items())),
            "human_review_item_count": len(review_items),
        },
        "package_classification_counts": dict(sorted(Counter(
            item["package_classification"] for item in package_records
        ).items())),
        "status": "COMPLETE_WITH_STAGE3_COVERAGE_GAP" if missing_scene_images else "COMPLETE",
        "next_action": (
            "Generate only the missing Stage 3 canary assets before expanding visual production."
            if missing_scene_images else "Review classified visual defects surgically."
        ),
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_ROOT / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"status": report["status"], **report["metrics"], "report": str(report_path.resolve())}))


if __name__ == "__main__":
    main()
