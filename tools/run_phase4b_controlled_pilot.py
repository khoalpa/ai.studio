from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageFilter

from ai_story.archive import PackageVerifier, extract_inherited
from ai_story.models import Profile
from ai_story.providers import landscape_provider, portrait_provider
from ai_story.serial import validate_anchor
from ai_story.stage2.planning import create_visual_bible, create_visual_plan
from ai_story.stage2.transactions import LandscapeTransactionManager
from ai_story.stage3.transactions import PortraitTransactionManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE3R = (
    PROJECT_ROOT
    / "artifacts/baselines/real-v1/story/phase3/phase3r-locked-recovery-baseline/manifest.json"
)
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4b-pilot-v1"
CANARY_IDS = (
    "youth-torn-paper-boat",
    "adult-five-characters",
    "serial-locked-room",
)
SELECTED_ROLES = {"COVER", "CLIMAX", "ENDING"}
SELECTED_BASENAMES = {"cover.png", "climax.png", "ending.png"}


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the controlled Phase 4B visual pilot.")
    parser.add_argument("--case-id", action="append", choices=CANARY_IDS)
    parser.add_argument("--quality-preset", choices=("fast", "balanced", "quality"), default="quality")
    parser.add_argument(
        "--phase4c", action="store_true",
        help="Run the single-canary visual-fidelity calibration in an isolated output root.",
    )
    parser.add_argument(
        "--phase4d", action="store_true",
        help="Run landscape-only identity-aware scene conditioning for the canary.",
    )
    parser.add_argument(
        "--phase4e", action="store_true",
        help="Run pose-aware latent scene conditioning and prop-scale control for the canary.",
    )
    parser.add_argument(
        "--phase4g", action="store_true",
        help="Run prop-free latent guides with regional identity assessment for the canary.",
    )
    parser.add_argument(
        "--phase4h", action="store_true",
        help="Generate a prop-free base and insert the paper boat through a bounded mask.",
    )
    parser.add_argument(
        "--phase4i", action="store_true",
        help="Localize the hands and build a dynamic bounded prop mask for the cover.",
    )
    parser.add_argument(
        "--phase4j", action="store_true",
        help="Composite a controlled paper-boat silhouette before low-strength contact refinement.",
    )
    parser.add_argument(
        "--phase4l", action="store_true",
        help="Run the two-character climax canary from the locked Phase 4K checkpoint.",
    )
    return parser.parse_args()


def phase4c_assets(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    """Bind the canary to short, measurable scene facts instead of raw prose."""
    import copy

    result = copy.deepcopy(assets)
    by_name = {str(item["basename"]): item for item in result}
    scene_facts = {
        "cover.png": {
            "focal": ["bo"],
            "action": "Bo, one 12-year-old Vietnamese boy, holds one small torn folded paper boat.",
            "location": "a modest contemporary bedroom in Hanoi",
            "emotion": "quiet and worried",
            "props": ["small torn folded paper boat"],
            "subjects": [("bo", 0.56, 0.7)],
            "required": ["character:bo", "prop:paper boat", "composition:title_safe_area"],
            "probes": [
                ("person_count", "one boy", ["multiple children", "a group of people"]),
                ("paper_boat_scale", "a small folded paper boat toy", ["a full-size wooden boat", "a ship"]),
                ("setting", "inside a contemporary bedroom", ["an outdoor fantasy landscape", "a river valley"]),
            ],
            "prompt_core": "REQUIRED: one 12-year-old Vietnamese boy Bo matching reference, short black hair, white shirt, blue jeans; one small torn folded paper boat; indoor Hanoi bedroom; clear top title area. FORBIDDEN: extra people, full-size boat, ship, outdoor fantasy landscape, text.",
        },
        "climax.png": {
            "focal": ["bo", "me"],
            "action": "Bo sits on one blue fabric pillow and grips one small torn folded paper boat; his mother sits beside him and holds his hand.",
            "location": "inside a warm contemporary bedroom in Hanoi",
            "emotion": "intimate worry and reassurance",
            "props": ["small torn folded paper boat", "blue fabric pillow"],
            "subjects": [("bo", 0.42, 0.72), ("me", 0.64, 0.72)],
            "required": ["character:bo", "character:me", "prop:paper boat", "prop:blue pillow"],
            "probes": [
                ("person_count", "one boy and his mother, exactly two people", ["one person", "three or more people"]),
                ("paper_boat_scale", "a small torn folded paper boat toy", ["a full-size wooden boat", "a ship"]),
                ("setting", "inside a warm contemporary bedroom", ["an outdoor fantasy landscape", "a river valley"]),
            ],
            "prompt_core": "REQUIRED: Bo matching boy reference and his mother matching adult reference, exactly two people; mother holds Bo's hand; small torn folded paper boat; blue pillow; warm indoor Hanoi bedroom. FORBIDDEN: extra people, ship, outdoor fantasy landscape, text.",
        },
        "ending.png": {
            "focal": ["bo", "me"],
            "action": "Bo sits beside his mother holding an open book; one small torn folded paper boat and one duck-shaped fabric pillow rest nearby.",
            "location": "inside a warm contemporary bedroom in Hanoi",
            "emotion": "quiet hope",
            "props": ["small torn folded paper boat", "open book", "duck-shaped fabric pillow"],
            "subjects": [("bo", 0.42, 0.72), ("me", 0.64, 0.72)],
            "required": ["character:bo", "character:me", "prop:paper boat", "prop:book", "prop:duck pillow"],
            "probes": [
                ("person_count", "one boy and his mother, exactly two people", ["one person", "three or more people"]),
                ("paper_boat_scale", "a small torn folded paper boat toy", ["a full-size wooden boat", "a ship"]),
                ("duck_pillow", "a duck-shaped fabric pillow", ["a living duck", "a rubber duck toy"]),
                ("setting", "inside a warm contemporary bedroom", ["an outdoor fantasy landscape", "a river valley"]),
            ],
            "prompt_core": "REQUIRED: Bo matching boy reference and his mother matching adult reference, exactly two people; open book; small torn folded paper boat; duck-shaped fabric pillow; warm indoor Hanoi bedroom. FORBIDDEN: extra people, ship, living duck, outdoor fantasy landscape, text.",
        },
    }
    for basename, facts in scene_facts.items():
        asset = by_name[basename]
        asset["focal_character_ids"] = facts["focal"]
        asset["visual_moment"] = facts["action"]
        shot = asset["shot_spec"]
        shot["subject_character_ids"] = facts["focal"]
        shot["action"] = facts["action"]
        shot["location"] = facts["location"]
        shot["emotion"] = facts["emotion"]
        shot["props"] = facts["props"]
        shot["required_elements"] = facts["required"]
        shot["negative_terms"] = [
            "full-size boat", "wooden ship", "living duck", "outdoor fantasy valley",
            "extra child", "duplicate person",
        ]
        shot["subjects"] = [
            {
                "character_id": character_id,
                "position": {"x": x, "y": y},
                "scale": "medium_full",
                "pose": "seated story-action pose",
                "gaze": "toward the shared story action",
            }
            for character_id, x, y in facts["subjects"]
        ]
        shot["fidelity_probes"] = [
            {"probe_id": probe_id, "expected": expected, "forbidden": forbidden}
            for probe_id, expected, forbidden in facts["probes"]
        ]
        shot["prompt_core"] = facts["prompt_core"]
    return result


def phase4d_assets(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    result = phase4c_assets(assets)
    by_name = {str(item["basename"]): item for item in result}
    prop_positions = {
        "cover.png": [("paper boat", 0.48, 0.76)],
        "climax.png": [("paper boat", 0.49, 0.76), ("blue pillow", 0.40, 0.78)],
        "ending.png": [
            ("paper boat", 0.48, 0.77), ("book", 0.58, 0.74),
            ("duck pillow", 0.34, 0.77),
        ],
    }
    for basename, props in prop_positions.items():
        shot = by_name[basename]["shot_spec"]
        shot["composition_strength"] = 0.74
        shot["prop_layout"] = [
            {
                "name": name, "position": {"x": x, "y": y},
                "scale": "small story prop", "state": "damaged" if name == "paper boat" else "intact",
            }
            for name, x, y in props
        ]
        shot["fidelity_probes"].append({
            "probe_id": "integrated_scene",
            "expected": "people integrated naturally into a finished bedroom story scene",
            "forbidden": [
                "portrait cards with rectangular borders",
                "people isolated on studio reference panels",
            ],
        })
    return result


def phase4e_assets(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    result = phase4d_assets(assets)
    by_name = {str(item["basename"]): item for item in result}
    poses = {
        "cover.png": [
            ("bo", "standing naturally, both hands holding the small paper boat at waist level", 0.50, 0.67),
        ],
        "climax.png": [
            ("bo", "seated on the blue pillow, one hand holding the small paper boat", 0.49, 0.68),
            ("me", "seated close beside Bo, reaching to hold his hand", 0.51, 0.68),
        ],
        "ending.png": [
            ("bo", "seated beside his mother, hands supporting one shared open book", 0.50, 0.67),
            ("me", "seated beside Bo, one hand supporting the shared open book", 0.50, 0.67),
        ],
    }
    prop_widths = {
        "paper boat": 0.035,
        "book": 0.075,
        "blue pillow": 0.11,
        "duck pillow": 0.10,
    }
    prompt_cores = {
        "cover.png": "REQUIRED: one Vietnamese boy Bo matching face reference; natural standing pose; hands holding one palm-sized torn paper boat; furnished Hanoi bedroom; clear top title area. FORBIDDEN: extra people, oversized boat, ship, cutout, panel, text.",
        "climax.png": "REQUIRED: exactly Bo and mother matching face references, seated close; mother holds Bo's hand; Bo holds one palm-sized torn paper boat; blue pillow; furnished Hanoi bedroom. FORBIDDEN: extra people, oversized boat, ship, cutouts, panels, outdoors, text.",
        "ending.png": "REQUIRED: exactly Bo and mother matching face references, seated together sharing one open book; palm-sized torn paper boat; duck fabric pillow; furnished Hanoi bedroom. FORBIDDEN: extra people, oversized boats, ship, living duck, cutouts, panels, outdoors, text.",
    }
    for basename, pose_specs in poses.items():
        shot = by_name[basename]["shot_spec"]
        shot["pose_aware_scene_conditioning"] = True
        shot["composition_strength"] = 0.78
        shot["prompt_core"] = prompt_cores[basename]
        subjects = {item["character_id"]: item for item in shot["subjects"]}
        for character_id, pose, target_x, target_y in pose_specs:
            subjects[character_id]["pose"] = pose
            subjects[character_id]["interaction_target"] = {"x": target_x, "y": target_y}
        for prop in shot["prop_layout"]:
            prop["relative_width"] = prop_widths[str(prop["name"])]
        shot["fidelity_probes"].extend([
            {
                "probe_id": "natural_pose",
                "expected": "people naturally posed and physically interacting in the scene",
                "forbidden": ["stiff pasted cutout people", "isolated standing character sheet"],
            },
            {
                "probe_id": "controlled_prop_scale",
                "expected": "a palm-sized paper boat held or resting naturally near the people",
                "forbidden": ["an oversized paper boat dominating the room", "a person-sized paper boat"],
            },
        ])
    return result


def phase4g_assets(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    result = phase4e_assets(assets)
    prompts = {
        "cover.png": "REQUIRED: one Vietnamese boy Bo matching face reference; natural standing pose; both hands hold one tiny 12-centimeter torn paper boat; furnished Hanoi bedroom; clear title area. FORBIDDEN: extra people, large boat, ship, cutout, panel, text.",
        "climax.png": "REQUIRED: Bo at left and his mother at right matching their separate face references; seated close; mother holds Bo's hand; Bo holds one tiny 12-centimeter torn paper boat; blue pillow; furnished bedroom. FORBIDDEN: extra people, large boat, ship, cutouts, text.",
        "ending.png": "REQUIRED: Bo at left and mother at right matching separate face references; seated together sharing one normal-size open book; one tiny 12-centimeter torn paper boat and duck fabric pillow nearby; furnished bedroom. FORBIDDEN: extra people, large objects, ship, living duck, cutouts, text.",
    }
    for asset in result:
        basename = str(asset["basename"])
        shot = asset["shot_spec"]
        shot["latent_props_disabled"] = True
        shot["regional_identity_conditioning"] = True
        shot["persist_candidates"] = True
        shot["composition_strength"] = 0.84
        shot["prompt_core"] = prompts[basename]
        for subject in shot["subjects"]:
            subject["identity_region_width"] = 0.25
            subject["identity_region_height"] = 0.58
    return result


def phase4h_assets(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    result = phase4g_assets(assets)
    cover = next(item for item in result if item["basename"] == "cover.png")
    shot = cover["shot_spec"]
    shot["prompt_core"] = (
        "REQUIRED: one Vietnamese boy Bo matching face reference; natural standing pose; "
        "both hands gently cupped around a small empty space at waist level; furnished Hanoi "
        "bedroom; clear title area. Keep the floor and the space around his hands completely "
        "empty. No extra people, cutout, panel, or text."
    )
    shot["masked_prop_inpaint"] = {
        "base_prompt": shot["prompt_core"] + " Storybook 16:9.",
        "base_negative_prompt": (
            "text, letters, logo, watermark, signature, duplicate person, extra person, "
            "extra limbs, malformed hands, cropped face, low detail, blur, object on floor, "
            "object between hands"
        ),
        "prompt": (
            "Use case: precise-object-edit. Insert only one tiny torn folded paper boat, "
            "about 12 centimeters long, fitting completely between the boy's two hands. "
            "Keep the hands, boy, face, body, bedroom, lighting, camera, and composition "
            "unchanged. No ship, no large boat, no text, no extra object."
        ),
        "crop_box": [0.36, 0.43, 0.64, 0.78],
        "mask_box": [0.455, 0.595, 0.545, 0.685],
        "feather_pixels": 14,
        "strength": 0.58,
    }
    return [cover]


def phase4i_assets(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    result = phase4h_assets(assets)
    edit = result[0]["shot_spec"]["masked_prop_inpaint"]
    edit["dynamic_hand_mask"] = True
    edit["minimum_hand_confidence"] = 0.62
    return result


def phase4j_assets(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    result = phase4i_assets(assets)
    edit = result[0]["shot_spec"]["masked_prop_inpaint"]
    edit["prop_first_compositing"] = True
    edit["strength"] = 0.24
    edit["prompt"] = (
        "Use case: precise-object-edit. Preserve the existing small torn folded paper boat "
        "exactly between both hands. Refine only finger contact, paper texture, local shadow, "
        "and matching light. Keep its silhouette and scale unchanged. Keep the boy, face, "
        "body, room, camera, and composition unchanged. No extra object or text."
    )
    return result


def phase4l_assets(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    result = phase4g_assets(assets)
    climax = next(item for item in result if item["basename"] == "climax.png")
    shot = climax["shot_spec"]
    shot["prompt_core"] = (
        "REQUIRED: exactly two people, Vietnamese boy Bo at left and his mother at right, "
        "both matching their separate face references; seated close together in a furnished "
        "Hanoi bedroom; mother gently holds Bo's wrist while Bo cups both hands around a small "
        "empty space. Keep that hand space empty. No extra people, boat, ship, cutout, text."
    )
    shot["masked_prop_inpaint"] = {
        "base_prompt": shot["prompt_core"] + " Storybook 16:9.",
        "base_negative_prompt": (
            "text, letters, logo, watermark, signature, duplicate person, extra person, "
            "extra limbs, malformed hands, cropped faces, low detail, blur, boat, ship, "
            "object between hands"
        ),
        "prompt": (
            "Use case: precise-object-edit. Preserve the existing small torn folded paper boat "
            "exactly between Bo's hands. Refine only finger contact, paper texture, local shadow, "
            "and matching light. Keep Bo, his mother, both faces, bodies, room, camera, and "
            "composition unchanged. No extra object or text."
        ),
        "crop_box": [0.24, 0.43, 0.56, 0.82],
        "mask_box": [0.365, 0.61, 0.455, 0.70],
        "feather_pixels": 14,
        "strength": 0.24,
        "dynamic_hand_mask": True,
        "minimum_hand_confidence": 0.62,
        "target_subject_x": 0.42,
        "prop_first_compositing": True,
    }
    return [climax]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def portrait_source(
    *, basename: str, work: Path, checkpoint: dict[str, object]
) -> Path:
    """Return a text-free Stage 3 source without mutating the Stage 2 asset."""
    landscape = work / "landscape" / basename
    if basename != "cover.png":
        return landscape
    target = work / "pilot_sources" / "cover-no-typography-v2.png"
    if target.is_file():
        return target
    cover = checkpoint["landscape"][basename]  # type: ignore[index]
    typography = cover["quality_assessment"].get("controlled_typography", {})
    safe_region = typography.get("safe_region", [])
    if len(safe_region) != 4:
        raise RuntimeError("Controlled cover typography safe region is missing")
    image = Image.open(io.BytesIO(landscape.read_bytes())).convert("RGB")
    # The title is confined to this audited region.  Blur only that region so
    # OCR cannot leak into img2img while all identity-bearing pixels remain.
    box = tuple(int(value) for value in safe_region)
    cleaned = image.copy()
    patch = image.crop(box).filter(ImageFilter.GaussianBlur(radius=48))
    cleaned.paste(patch, box)
    target.parent.mkdir(parents=True, exist_ok=True)
    cleaned.save(target, format="PNG", optimize=True)
    return target


def main() -> None:
    options = args()
    phase_flags = (
        options.phase4c, options.phase4d, options.phase4e, options.phase4g,
        options.phase4h, options.phase4i, options.phase4j, options.phase4l,
    )
    if sum(phase_flags) > 1:
        raise RuntimeError("Choose only one phase calibration flag")
    calibrated = any(phase_flags)
    selected_cases = ["youth-torn-paper-boat"] if calibrated else (options.case_id or list(CANARY_IDS))
    output_root = (
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1"
        if options.phase4l else
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4j-prop-first-canary-v1"
        if options.phase4j else
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4i-hand-aware-canary-v1"
        if options.phase4i else
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4h-masked-prop-canary-v2"
        if options.phase4h else
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4g-regional-identity-canary-v1"
        if options.phase4g else
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4e-pose-prop-canary-v1"
        if options.phase4e else
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4d-identity-scene-canary-v1"
        if options.phase4d else
        PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4c-fidelity-canary-v1"
        if options.phase4c else OUTPUT_ROOT
    )
    phase4k_cover_digest = None
    if options.phase4l:
        phase4k_bundle = (
            PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4k-promoted-cover-v1"
            / "youth-torn-paper-boat-phase4k-cover.zip"
        )
        with zipfile.ZipFile(phase4k_bundle, "r") as archive:
            phase4k_cover_digest = hashlib.sha256(
                archive.read("landscape/cover.png")
            ).hexdigest()
        expected_digest = "412875dd1a06374b2c20bbbd6e722d1c538aa2e400d900bad636eb2dc01a4fad"
        if phase4k_cover_digest != expected_digest:
            raise RuntimeError("Phase 4K cover checkpoint digest mismatch")
    baseline = json.loads(PHASE3R.read_text(encoding="utf-8"))
    packages = {item["case_id"]: item for item in baseline["packages"]}
    results = []
    consecutive_failures = 0
    stop_reason = None

    for case_id in selected_cases:
        source = Path(packages[case_id]["locked_package"])
        verified = PackageVerifier().verify(source)
        case_root = output_root / case_id
        work = case_root / "work"
        checkpoint_path = case_root / "checkpoint.json"
        work.mkdir(parents=True, exist_ok=True)
        checkpoint = (
            json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if checkpoint_path.is_file()
            else {
                "schema_version": "1.0",
                "case_id": case_id,
                "source_package": str(source.resolve()),
                "source_package_digest_sha256": verified.package_digest_sha256,
                "quality_preset": options.quality_preset,
                "landscape": {},
                "portrait": {},
                "failures": [],
            }
        )
        if checkpoint["source_package_digest_sha256"] != verified.package_digest_sha256:
            raise RuntimeError(f"Checkpoint source mismatch: {case_id}")
        if not (work / "story.json").is_file():
            extract_inherited(source, work)
        story = json.loads((work / "story.json").read_text(encoding="utf-8"))
        report = json.loads((work / "story_validation.json").read_text(encoding="utf-8"))
        profile = Profile(packages[case_id]["profile"])
        plan = create_visual_plan(
            story,
            report,
            str(report.get("story_sha256", "")),
            str(report.get("story_sha256", "")),
        )
        series_anchor = None
        if profile is Profile.SERIAL_DETECTIVE:
            series_anchor = json.loads((work / "series_anchor.json").read_text(encoding="utf-8"))
            validate_anchor(series_anchor)
        bible = create_visual_bible(story, "phase4b-pilot", profile, series_anchor)
        selected_assets = [
            item for item in plan["assets"] if item.get("basename") in SELECTED_BASENAMES
        ]
        if options.phase4l:
            selected_assets = phase4l_assets(selected_assets)
        elif options.phase4j:
            selected_assets = phase4j_assets(selected_assets)
        elif options.phase4i:
            selected_assets = phase4i_assets(selected_assets)
        elif options.phase4h:
            selected_assets = phase4h_assets(selected_assets)
        elif options.phase4g:
            selected_assets = phase4g_assets(selected_assets)
        elif options.phase4e:
            selected_assets = phase4e_assets(selected_assets)
        elif options.phase4d:
            selected_assets = phase4d_assets(selected_assets)
        elif options.phase4c:
            selected_assets = phase4c_assets(selected_assets)
        expected_basenames = (
            {"climax.png"} if options.phase4l else
            {"cover.png"} if options.phase4h or options.phase4i or options.phase4j else
            SELECTED_BASENAMES
        )
        if {item.get("basename") for item in selected_assets} != expected_basenames:
            raise RuntimeError(f"Pilot role coverage mismatch: {case_id}")

        landscape, landscape_registry = landscape_provider(
            "local", quality_preset=options.quality_preset
        )
        try:
            manager = LandscapeTransactionManager(landscape)
            for asset in selected_assets:
                basename = str(asset["basename"])
                if basename in checkpoint["landscape"]:
                    continue
                try:
                    commit = manager.execute(
                        basename=basename,
                        output_root=work,
                        story=story,
                        visual_plan_asset=asset,
                        visual_bible=bible,
                    )
                    checkpoint["landscape"][basename] = commit.plan_binding()
                    matching = [
                        item for item in checkpoint["failures"]
                        if item.get("orientation") == "landscape"
                        and item.get("basename") == basename
                    ]
                    if matching:
                        checkpoint.setdefault("resolved_failures", []).extend(matching)
                        checkpoint["failures"] = [
                            item for item in checkpoint["failures"] if item not in matching
                        ]
                    consecutive_failures = 0
                except Exception as exc:
                    checkpoint["failures"].append({
                        "orientation": "landscape", "basename": basename,
                        "error": type(exc).__name__, "detail": str(exc),
                    })
                    consecutive_failures += 1
                write_json(checkpoint_path, checkpoint)
                failure_limit = 1 if options.phase4g or options.phase4h or options.phase4i or options.phase4j or options.phase4l else 3 if options.phase4e else 2
                if consecutive_failures >= failure_limit:
                    stop_reason = f"FAILURE_LIMIT_REACHED:{case_id}:landscape"
                    break
        finally:
            assessor = getattr(landscape, "assessor", None)
            if assessor is not None:
                assessor.unload()
            if landscape_registry is not None:
                landscape_registry.close()
        if stop_reason:
            break

        if options.phase4d or options.phase4e or options.phase4g or options.phase4h or options.phase4i or options.phase4j or options.phase4l:
            phase = "phase4l" if options.phase4l else "phase4j" if options.phase4j else "phase4i" if options.phase4i else "phase4h" if options.phase4h else "phase4g" if options.phase4g else "phase4e" if options.phase4e else "phase4d"
            bundle = case_root / f"{case_id}-{phase}-landscape-canary.zip"
            with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(checkpoint_path, "checkpoint.json")
                for basename in checkpoint["landscape"]:
                    path = work / "landscape" / basename
                    if path.is_file():
                        archive.write(path, f"landscape/{basename}")
            results.append({
                "case_id": case_id,
                "landscape_count": len(checkpoint["landscape"]),
                "portrait_count": 0,
                "failure_count": len(checkpoint["failures"]),
                "unresolved_asset_count": len({
                    (item.get("orientation"), item.get("basename"))
                    for item in checkpoint["failures"]
                }),
                "bundle": str(bundle.resolve()),
            })
            continue

        portrait, portrait_registry = portrait_provider(
            "local", quality_preset=options.quality_preset
        )
        try:
            manager = PortraitTransactionManager(portrait)
            for asset in selected_assets:
                basename = str(asset["basename"])
                if basename in checkpoint["portrait"]:
                    continue
                if basename not in checkpoint["landscape"]:
                    continue
                try:
                    commit = manager.execute(
                        basename=basename,
                        landscape_path=portrait_source(
                            basename=basename, work=work, checkpoint=checkpoint
                        ),
                        output_root=work,
                        visual_plan_asset=asset,
                        visual_bible=bible,
                    )
                    checkpoint["portrait"][basename] = commit.evidence()
                    matching = [
                        item for item in checkpoint["failures"]
                        if item.get("orientation") == "portrait"
                        and item.get("basename") == basename
                    ]
                    if matching:
                        checkpoint.setdefault("resolved_failures", []).extend(matching)
                        checkpoint["failures"] = [
                            item for item in checkpoint["failures"] if item not in matching
                        ]
                    consecutive_failures = 0
                except Exception as exc:
                    checkpoint["failures"].append({
                        "orientation": "portrait", "basename": basename,
                        "error": type(exc).__name__, "detail": str(exc),
                    })
                    consecutive_failures += 1
                write_json(checkpoint_path, checkpoint)
                if consecutive_failures >= 2:
                    stop_reason = f"TWO_CONSECUTIVE_FAILURES:{case_id}:portrait"
                    break
        finally:
            assessor = getattr(portrait, "assessor", None)
            if assessor is not None:
                assessor.unload()
            if portrait_registry is not None:
                portrait_registry.close()

        bundle = case_root / (
            f"{case_id}-phase4c-fidelity-canary.zip"
            if options.phase4c else f"{case_id}-phase4b-pilot.zip"
        )
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(checkpoint_path, "checkpoint.json")
            for orientation in ("landscape", "portrait"):
                for basename in checkpoint[orientation]:
                    path = work / orientation / basename
                    if path.is_file():
                        archive.write(path, f"{orientation}/{basename}")
        results.append({
            "case_id": case_id,
            "landscape_count": len(checkpoint["landscape"]),
            "portrait_count": len(checkpoint["portrait"]),
            "failure_count": len(checkpoint["failures"]),
            "unresolved_asset_count": len({
                (item.get("orientation"), item.get("basename"))
                for item in checkpoint["failures"]
            }),
            "bundle": str(bundle.resolve()),
        })
        if stop_reason:
            break

    report = {
        "schema_version": "1.0",
        "report_kind": (
            "PHASE4L_CLIMAX_CANARY" if options.phase4l else
            "PHASE4J_PROP_FIRST_CANARY" if options.phase4j else
            "PHASE4I_HAND_AWARE_CANARY" if options.phase4i else
            "PHASE4H_MASKED_PROP_CANARY" if options.phase4h else
            "PHASE4G_REGIONAL_IDENTITY_CANARY" if options.phase4g else
            "PHASE4E_POSE_PROP_CANARY" if options.phase4e else
            "PHASE4D_IDENTITY_AWARE_SCENE_CANARY" if options.phase4d else
            "PHASE4C_VISUAL_FIDELITY_CANARY" if options.phase4c else
            "PHASE4B_CONTROLLED_PILOT"
        ),
        "policy": {
            "case_ids": selected_cases,
            "roles": ["CLIMAX"] if options.phase4l else ["COVER"] if options.phase4h or options.phase4i or options.phase4j else sorted(SELECTED_ROLES),
            "landscape_before_portrait": True,
            "source_story_packages_modified": False,
            "bulk_generation_used": False,
            "single_canary_only": calibrated,
            "contrastive_fidelity_gates": calibrated,
            "composition_reference_img2img": calibrated,
            "identity_aware_soft_mask": options.phase4d or options.phase4e or options.phase4g or options.phase4h or options.phase4i or options.phase4j or options.phase4l,
            "pose_aware_latent_conditioning": options.phase4e or options.phase4g or options.phase4h or options.phase4i or options.phase4j or options.phase4l,
            "controlled_prop_scale": options.phase4e or options.phase4g or options.phase4h or options.phase4i or options.phase4j or options.phase4l,
            "latent_props_disabled": options.phase4g or options.phase4h or options.phase4i or options.phase4j or options.phase4l,
            "regional_identity_conditioning": options.phase4g or options.phase4h or options.phase4i or options.phase4j or options.phase4l,
            "candidate_assessment_sidecars": options.phase4g or options.phase4h or options.phase4i or options.phase4j or options.phase4l,
            "masked_prop_inpaint": options.phase4h or options.phase4i or options.phase4j or options.phase4l,
            "dynamic_hand_mask": options.phase4i or options.phase4j or options.phase4l,
            "prop_first_compositing": options.phase4j or options.phase4l,
            "controlled_prop_gates": options.phase4j or options.phase4l,
            "outside_mask_pixel_invariance": options.phase4h or options.phase4i or options.phase4j or options.phase4l,
            "phase4k_cover_digest_preserved": phase4k_cover_digest,
            "landscape_only_until_manual_pass": options.phase4d or options.phase4e or options.phase4g or options.phase4h or options.phase4i or options.phase4j or options.phase4l,
        },
        "quality_preset": options.quality_preset,
        "results": results,
        "stop_reason": stop_reason,
        "manual_visual_review": str((output_root / "manual-visual-review.json").resolve())
        if (output_root / "manual-visual-review.json").is_file() else None,
        "status": "HOLD" if options.phase4d or options.phase4e or options.phase4g or options.phase4h or options.phase4i or options.phase4j or options.phase4l else "PASS" if len(results) == (1 if options.phase4c else 3) and all(
            item["landscape_count"] == item["portrait_count"] == 3
            and item["failure_count"] == 0 for item in results
        ) else "HOLD",
    }
    write_json(output_root / "result.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
