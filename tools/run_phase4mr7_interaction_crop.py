from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from ai_story.image_qa import ImageQualityError
from ai_story.providers import landscape_provider
from ai_story.runtime import GenerationRequest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE4L = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1"
PHASE4K = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4k-promoted-cover-v1"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4m-surgical-climax-v1"
BASE = PHASE4L / "youth-torn-paper-boat/work/candidates/climax/attempt-2-base.png"
CHARACTERS = PHASE4L / "youth-torn-paper-boat/work/characters"
CROP_BOX = (1550, 1050, 2290, 1450)
SEED = int.from_bytes(hashlib.sha256(b"phase4m-r7:interaction-crop:1").digest()[:4], "big")


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


def clean_pose_canvas(size: tuple[int, int]) -> Image.Image:
    """Create a cup-free latent guide with two opposed forearms and one small boat."""
    width, height = size
    canvas = Image.new("RGB", size, (205, 177, 149))
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        ratio = y / max(1, height - 1)
        draw.line(
            (0, y, width, y),
            fill=(
                round(215 - 30 * ratio),
                round(194 - 42 * ratio),
                round(170 - 45 * ratio),
            ),
        )
    left_hand = (round(width * 0.40), round(height * 0.55))
    right_hand = (round(width * 0.60), round(height * 0.55))
    skin = (205, 155, 122)
    draw.line((0, round(height * 0.67), *left_hand), fill=skin, width=42)
    draw.line((width, round(height * 0.67), *right_hand), fill=skin, width=42)
    for x, y in (left_hand, right_hand):
        draw.ellipse((x - 34, y - 24, x + 34, y + 24), fill=skin)
    center_x, center_y = width // 2, round(height * 0.52)
    radius = round(width * 0.075)
    draw.polygon(
        [
            (center_x - radius, center_y),
            (center_x, center_y + radius // 2),
            (center_x + radius, center_y),
            (center_x + radius // 2, center_y + radius),
            (center_x - radius // 2, center_y + radius),
        ],
        fill=(235, 231, 215), outline=(77, 70, 61),
    )
    return canvas


def main() -> None:
    status = gpu_status()
    if not status["exclusive_enough"]:
        report = {
            "schema_version": "1.0", "phase": "4M-R7",
            "status": "WAITING_FOR_EXCLUSIVE_GPU", "gpu": status,
            "generation_performed": False, "phase4n_opened": False,
        }
        write_json(OUTPUT_ROOT / "phase4mr7-result.json", report)
        print(json.dumps(report, ensure_ascii=False))
        return

    base_data = BASE.read_bytes()
    base = Image.open(io.BytesIO(base_data)).convert("RGB")
    references = [
        {"character_id": "bo", "data": (CHARACTERS / "bo.png").read_bytes()},
        {"character_id": "me", "data": (CHARACTERS / "me.png").read_bytes()},
    ]
    prompt = (
        "Close interaction crop in a gentle Vietnamese storybook illustration. Only two "
        "natural forearms and two anatomically correct hands enter from opposite sides. "
        "The left hand is centered at 40 percent width and the right hand at 60 percent, "
        "both lightly holding one small torn folded paper boat at center. Warm floor behind. "
        "No faces, cup, mug, glass, pedestal, tray, extra hand, text, or watermark."
    )
    negative = (
        "cup, mug, glass, pedestal, tray, oversized boat, ship, extra fingers, extra hands, "
        "fused hands, malformed anatomy, face, person, text, watermark"
    )
    candidate_dir = OUTPUT_ROOT / "phase4mr7"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    landscape, registry = landscape_provider("local", quality_preset="quality")
    try:
        pose_canvas = clean_pose_canvas((768, 448))
        encoded_canvas = io.BytesIO()
        pose_canvas.save(encoded_canvas, format="PNG", optimize=True)
        pose_canvas.save(candidate_dir / "attempt-1-clean-pose-canvas.png", format="PNG")
        clean_crop = registry.generate_image(
            "landscape",
            GenerationRequest(
                prompt=prompt,
                model=landscape.model_id,
                parameters={
                    "negative_prompt": negative,
                    "seed": SEED,
                    "width": 768,
                    "height": 448,
                    "output_width": CROP_BOX[2] - CROP_BOX[0],
                    "output_height": CROP_BOX[3] - CROP_BOX[1],
                    "init_image": encoded_canvas.getvalue(),
                    "strength": 0.82,
                    "reference_inputs": [],
                    "control_inputs": [],
                    "steps": 32,
                    "guidance_scale": 7.0,
                },
                request_id="phase4mr7-clean-interaction-crop-1",
            ),
        )
        patch = Image.open(io.BytesIO(clean_crop)).convert("RGB").resize(
            (CROP_BOX[2] - CROP_BOX[0], CROP_BOX[3] - CROP_BOX[1])
        )
        generated_canvas = base.copy()
        generated_canvas.paste(patch, CROP_BOX[:2])
        hard_mask = Image.new("L", base.size, 0)
        ImageDraw.Draw(hard_mask).rounded_rectangle(CROP_BOX, radius=72, fill=255)
        mask = hard_mask.filter(ImageFilter.GaussianBlur(48))
        candidate = Image.composite(generated_canvas, base, mask)

        crop_path = candidate_dir / "attempt-1-clean-interaction-crop.png"
        candidate_path = candidate_dir / "attempt-1-candidate.png"
        mask_path = candidate_dir / "attempt-1-mask.png"
        patch.save(crop_path, format="PNG", optimize=True)
        candidate.save(candidate_path, format="PNG", optimize=True)
        mask.save(mask_path, format="PNG", optimize=True)

        difference = ImageChops.difference(candidate, base)
        outside = difference.copy()
        outside.paste((0, 0, 0), mask=mask.point(lambda value: 255 if value else 0))
        border = difference.crop((CROP_BOX[0], CROP_BOX[1], CROP_BOX[2], CROP_BOX[3]))
        border_mask = Image.new("L", border.size, 0)
        border_draw = ImageDraw.Draw(border_mask)
        border_draw.rectangle((0, 0, border.width - 1, border.height - 1), fill=255)
        border_draw.rectangle((32, 32, border.width - 33, border.height - 33), fill=0)
        border_mae = round(sum(ImageStat.Stat(border, border_mask).mean) / 3, 4)
        seam_status = "PASS" if border_mae <= 8.0 else "FAIL"

        probes = [
            {
                "probe_id": "cup_absence",
                "expected": "two hands holding a paper boat with no cup",
                "forbidden": ["a cup", "a mug", "a drinking glass", "a pedestal"],
                "crop_box_pixels": list(CROP_BOX),
            },
            {
                "probe_id": "two_hand_contact",
                "expected": "two natural hands from opposite sides touching one small paper boat",
                "forbidden": ["one hand", "floating object", "malformed hands"],
                "crop_box_pixels": list(CROP_BOX),
            },
            {
                "probe_id": "hand_anatomy",
                "expected": "two anatomically natural hands and forearms",
                "forbidden": ["extra hands", "fused hands", "deformed fingers"],
                "crop_box_pixels": list(CROP_BOX),
            },
        ]
        probe_assessment = landscape.assessor.assess_fidelity_probes(
            candidate_path.read_bytes(), fidelity_probes=probes
        )
        write_json(candidate_dir / "attempt-1-probe-assessment.json", probe_assessment)
        status_value = (
            "AWAITING_MANUAL_REVIEW"
            if probe_assessment["status"] == "ASSESSED_PASS" and seam_status == "PASS"
            else "BLOCKED"
        )
        report = {
            "schema_version": "1.0",
            "phase": "4M-R7",
            "status": status_value,
            "case_id": "youth-torn-paper-boat",
            "attempt": 1,
            "seed": SEED,
            "source_base": str(BASE.resolve()),
            "source_base_sha256": hashlib.sha256(base_data).hexdigest(),
            "clean_crop_generated_from_original_pixels": False,
            "reference_conditioning": {
                "requested_characters": [item["character_id"] for item in references],
                "runtime_direct_reference_support": False,
                "applied_fallback": "CUP_FREE_POSE_AWARE_COMPOSITION_CANVAS",
                "identity_regions_in_crop": "NOT_VISIBLE_HANDS_AND_FOREARMS_ONLY"
            },
            "pose_landmarks_normalized": {
                "left_hand": [0.4, 0.55], "right_hand": [0.6, 0.55],
                "prop_center": [0.5, 0.55],
            },
            "crop_box_pixels": list(CROP_BOX),
            "candidate_path": str(candidate_path.resolve()),
            "candidate_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
            "probe_assessment": probe_assessment,
            "seam_gate": {"status": seam_status, "border_mae": border_mae, "maximum": 8.0},
            "outside_mask_invariance": "PASS" if outside.getbbox() is None else "FAIL",
            "manual_review_required": status_value == "AWAITING_MANUAL_REVIEW",
            "next_attempt_started": False,
            "phase4n_opened": False,
            "source_package_modified": False,
            "phase4k_cover_digest_preserved": (
                json.loads((PHASE4K / "phase4k-result.json").read_text(encoding="utf-8"))
                ["promotion"]["approved_cover_sha256"]
            ),
        }
    except ImageQualityError as exc:
        report = {
            "schema_version": "1.0", "phase": "4M-R7", "status": "BLOCKED",
            "error": "ImageQualityError", "detail": str(exc),
            "assessment": exc.assessment, "next_attempt_started": False,
            "phase4n_opened": False, "source_package_modified": False,
        }
    finally:
        landscape.assessor.unload()
        if registry is not None:
            registry.close()
    write_json(OUTPUT_ROOT / "phase4mr7-result.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
