from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageChops

from ai_story.image_promotion import promote_cover_in_bundle, sha256_bytes
from ai_story.image_qa import LocalImageQualityAssessor
from ai_story.provider_config import configure_job

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE4J = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4j-prop-first-canary-v1"
PHASE4K = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4k-promoted-cover-v1"
SOURCE_BUNDLE = (
    PROJECT_ROOT
    / "artifacts/baselines/real-v1/image/phase4c-fidelity-canary-v1"
    / "youth-torn-paper-boat/youth-torn-paper-boat-phase4c-fidelity-canary.zip"
)
CANDIDATE_ROOT = PHASE4J / "youth-torn-paper-boat/work/candidates/cover"
APPROVED = CANDIDATE_ROOT / "attempt-3-inpaint.png"


def main() -> None:
    prior = json.loads(
        (PHASE4J / "attempt-3-localized-reassessment.json").read_text(encoding="utf-8")
    )
    if prior["status"] != "ASSESSED_PASS" or prior["image_generation_performed"]:
        raise RuntimeError("Attempt 3 is not an approved, generation-free Phase 4J candidate")

    assessment_source = json.loads(
        (CANDIDATE_ROOT / "attempt-3-rejected.assessment.json").read_text(encoding="utf-8")
    )
    edit_evidence = assessment_source["masked_prop_inpaint"]
    crop_box = edit_evidence["crop_box_pixels"]
    candidate_data = APPROVED.read_bytes()
    bo_reference = (
        PHASE4J / "youth-torn-paper-boat/work/characters/bo.png"
    ).read_bytes()
    fidelity_probes = [
        {
            "probe_id": "person_count",
            "expected": "one Vietnamese boy",
            "forbidden": ["multiple children", "a group of people"],
        },
        {
            "probe_id": "setting",
            "expected": "inside a furnished contemporary bedroom",
            "forbidden": ["an outdoor landscape", "a river valley"],
        },
        {
            "probe_id": "controlled_prop_scale",
            "expected": "one small palm-sized folded paper boat held between two human hands",
            "forbidden": [
                "an oversized paper boat larger than the hands",
                "a person-sized paper boat dominating the scene",
            ],
            "crop_box_pixels": crop_box,
        },
    ]
    config = configure_job("local", None, "quality")
    assessor = LocalImageQualityAssessor(config["runtimes"]["diffusers"]["qa"])
    try:
        full_assessment = assessor.assess(
            candidate_data,
            prompt=(
                "One Vietnamese boy stands naturally in a furnished Hanoi bedroom and "
                "holds one small torn folded paper boat between both hands."
            ),
            expected_dimensions=(3840, 2160),
            asset_type="cover",
            identity_references=[bo_reference],
            required_elements=["character:bo", "prop:paper boat", "composition:title_safe_area"],
            forbidden_elements=["uncontrolled_text", "watermark"],
            fidelity_probes=fidelity_probes,
        )
    finally:
        assessor.unload()

    base = Image.open(CANDIDATE_ROOT / "attempt-3-base.png").convert("RGB")
    candidate_image = Image.open(io.BytesIO(candidate_data)).convert("RGB")
    persisted_mask = Image.open(CANDIDATE_ROOT / "attempt-3-mask.png").convert("L")
    effective_mask = persisted_mask.point(lambda value: 255 if value else 0)
    difference = ImageChops.difference(base, candidate_image)
    difference.paste((0, 0, 0), mask=effective_mask)
    outside_mask_status = "PASS" if difference.getbbox() is None else "FAIL"
    if outside_mask_status != "PASS":
        raise RuntimeError("Candidate differs from its base outside the hard prop mask")

    PHASE4K.mkdir(parents=True, exist_ok=True)
    output_bundle = PHASE4K / "youth-torn-paper-boat-phase4k-cover.zip"
    backup_cover = PHASE4K / "rollback/landscape/cover.png"
    with zipfile.ZipFile(SOURCE_BUNDLE, "r") as source:
        checkpoint = json.loads(source.read("checkpoint.json"))
    checkpoint["landscape"]["cover.png"].update({
        "path": "landscape/cover.png",
        "file_sha256": sha256_bytes(candidate_data),
        "dimensions": [3840, 2160],
        "transaction_id": "phase4k:controlled-promotion:cover",
        "quality_assessment": full_assessment,
        "validation_status": "PASS",
        "promotion_source": str(APPROVED.resolve()),
    })
    checkpoint["phase4k_promotion"] = {
        "case_id": "youth-torn-paper-boat",
        "role": "COVER",
        "image_generation_performed": False,
        "source_story_package_modified": False,
    }
    checkpoint_data = (json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    promotion = promote_cover_in_bundle(
        source_bundle=SOURCE_BUNDLE,
        approved_cover=APPROVED,
        output_bundle=output_bundle,
        backup_cover=backup_cover,
        metadata_updates={"checkpoint.json": checkpoint_data},
    )
    with zipfile.ZipFile(output_bundle, "r") as promoted:
        corrupt_entry = promoted.testzip()
        promoted_checkpoint = json.loads(promoted.read("checkpoint.json"))
        promoted_cover = promoted.read("landscape/cover.png")
        unchanged_images = {
            name: sha256_bytes(promoted.read(name))
            for name in ("landscape/climax.png", "landscape/ending.png")
        }
    if corrupt_entry is not None:
        raise RuntimeError(f"Promoted archive contains a corrupt entry: {corrupt_entry}")
    if promoted_checkpoint["landscape"]["cover.png"]["file_sha256"] != sha256_bytes(promoted_cover):
        raise RuntimeError("Promoted checkpoint cover digest does not match the archive")

    report = {
        "schema_version": "1.0",
        "phase": "4K",
        "status": "PASS",
        "case_id": "youth-torn-paper-boat",
        "role": "COVER",
        "promotion": promotion,
        "quality_assessment": full_assessment,
        "outside_hard_mask_pixel_invariance": outside_mask_status,
        "unchanged_landscape_images": unchanged_images,
        "archive_integrity": "PASS",
        "checkpoint_digest_binding": "PASS",
        "image_generation_performed": False,
        "source_story_package_modified": False,
        "output_bundle": str(output_bundle.resolve()),
        "rollback_cover": str(backup_cover.resolve()),
    }
    (PHASE4K / "phase4k-result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
