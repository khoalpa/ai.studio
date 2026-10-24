from __future__ import annotations

import copy
from typing import Any

from ..hashing import canonical_json_bytes, sha256_bytes
from ..models import Profile
from .config import basenames, stage2_config

VISUAL_PLAN_FIELDS = [
    "schema_version", "story_sha256", "story_validation_sha256", "requested_mode",
    "resolved_mode", "scene_source_digest_sha256", "selected_scene_count", "assets",
    "selection_coverage", "visual_plan_digest_sha256",
]
VISUAL_BIBLE_FIELDS = [
    "schema_version", "story_sha256", "active_profile", "age_profile", "art_direction_id",
    "tonal_plan", "character_identity_locks", "wardrobe_state_map",
    "recurring_location_locks", "prop_color_anchors", "approved_story_symbols",
    "landscape_reference_map", "dependency_digest",
]


def digest_with_null(document: dict[str, Any], field: str) -> str:
    projected = copy.deepcopy(document)
    projected[field] = None
    return sha256_bytes(canonical_json_bytes(projected))


def create_visual_plan(
    story: dict[str, Any], report: dict[str, Any], story_sha256: str, report_sha256: str
) -> dict[str, Any]:
    config = stage2_config()
    focal = [item["character_id"] for item in story["characters"] if item["visual_story_importance"] == "PRIMARY"]
    if not focal:
        focal = [story["characters"][0]["character_id"]]
    zone_items = {item["zone"]: index for index, item in enumerate(story["script"])}
    assets = []
    for ordinal, basename in enumerate(basenames(), 1):
        zone = config["zone_by_basename"][basename]
        source_index = zone_items.get(zone) if zone else None
        role = config["asset_roles"][basename]
        asset_focal = focal if role in {"COVER", "ZONE"} else []
        assets.append(
            {
                "asset_id": f"asset_{ordinal:04d}",
                "basename": basename,
                "role": role,
                "ordinal": ordinal,
                "zone": zone,
                "scene_id": None,
                "script_item_start": source_index,
                "script_item_end": source_index,
                "focal_character_ids": asset_focal,
                "visual_moment": _visual_moment(story, basename, source_index),
                "shot_spec": _shot_spec(story, basename, role, zone, source_index, asset_focal),
                "state_delta_to_show": f"Thay đổi quan sát được tại {zone or role}",
                "selection_basis": "ZONE_CANONICAL_COVERAGE",
                "landscape_image": None,
                "portrait_image": None,
                "validation_status": "PENDING",
            }
        )
    scene_digest = sha256_bytes(canonical_json_bytes(report["scene_zone_map"]))
    document = {
        "schema_version": config["visual_plan_schema_version"],
        "story_sha256": story_sha256,
        "story_validation_sha256": report_sha256,
        "requested_mode": "ZONE",
        "resolved_mode": "ZONE",
        "scene_source_digest_sha256": scene_digest,
        "selected_scene_count": 0,
        "assets": assets,
        "selection_coverage": {
            "source_scene_count": len(report["scene_zone_map"]),
            "selected_scene_count": 0,
            "omitted_scene_count": 0,
            "covered_zones": ["GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT", "CLIMAX", "FALLING", "ENDING", "FAREWELL"],
            "required_zone_gap_count": 0,
            "climax_covered": True,
            "ending_covered": True,
            "max_count_applied": False,
        },
        "visual_plan_digest_sha256": None,
    }
    return document


def _visual_moment(story: dict[str, Any], basename: str, source_index: int | None) -> str:
    if basename == "cover.png":
        opening = next(
            (str(item.get("text", "")) for item in story["script"] if item.get("zone") == "OPENING"),
            "",
        )
        opening_moment = " ".join(opening.split(". ")[:2]).strip()[:180]
        return f"Key art cho {story['meta']['title']}: {opening_moment}"
    if basename == "outro.png":
        return "Khung hình kết yên tĩnh, có khoảng trống thị giác an toàn."
    if source_index is None:
        return f"Khoảnh khắc chuyển tiếp cho {basename}."
    text = story["script"][source_index]["text"]
    return text[:240].rstrip()


def _shot_spec(
    story: dict[str, Any], basename: str, role: str, zone: str | None,
    source_index: int | None, focal: list[str],
) -> dict[str, Any]:
    source = "" if source_index is None else str(story["script"][source_index]["text"])
    if basename == "cover.png":
        source = next(
            (str(item.get("text", "")) for item in story["script"] if item.get("zone") == "OPENING"),
            "",
        )
    combined = f"{story['meta']['title']} {story.get('outline', {}).get((zone or '').lower(), '')} {source[:600]}".casefold()
    props = []
    prop_terms = {
        "paper boat": ("thuyền", "boat"), "book": ("sách", "book"),
        "kite": ("diều", "kite"),
        "blue pillow": ("gối xanh", "blue pillow"), "duck pillow": ("gối vịt", "duck pillow"),
        "rain": ("mưa", "rain"),
    }
    for label, terms in prop_terms.items():
        if any(term in combined for term in terms):
            props.append(label)
    if basename == "cover.png" and "paper boat" not in props and any(term in combined for term in ("thuyền", "boat")):
        props.append("paper boat")
    location = "warm contemporary bedroom" if any(term in combined for term in ("phòng", "giường", "gối", "bedroom")) else "story-specific contemporary setting"
    emotion_by_zone = {
        "OPENING": "curious and concerned", "INTRODUCTION": "sad and seeking comfort",
        "DEVELOPMENT": "supported but still reflective", "CLIMAX": "emotionally honest and connected",
        "FALLING": "calm after tension", "ENDING": "quiet hope",
    }
    required = [f"character:{character_id}" for character_id in focal]
    required.extend(f"prop:{prop}" for prop in props)
    if role == "COVER":
        required.extend(["composition:title_safe_area", "composition:face_unobstructed"])
    subject_positions = _subject_positions(len(focal), role)
    subjects = [
        {
            "character_id": character_id,
            "position": subject_positions[index],
            "scale": "medium" if role != "COVER" else "medium_full",
            "pose": "story-action pose",
            "gaze": "toward scene partner" if len(focal) > 1 else "toward story action",
            "reference_priority": ["face_closeup", "three_quarter", "full_body_front"],
        }
        for index, character_id in enumerate(focal)
    ]
    prop_layout = [
        {
            "name": prop,
            "position": {"x": 0.5, "y": 0.72},
            "scale": "story-readable",
            "state": _prop_state(prop, combined),
        }
        for prop in props
    ]
    return {
        "subject_character_ids": list(focal),
        "subjects": subjects,
        "action": _visual_moment(story, basename, source_index),
        "emotion": emotion_by_zone.get(zone or "", "calm and age-appropriate"),
        "props": props,
        "prop_layout": prop_layout,
        "location": location,
        "time": "story-consistent",
        "required_elements": list(dict.fromkeys(required)),
        "forbidden_elements": ["uncontrolled_text", "watermark", "duplicate_character", "anachronistic_costume"],
        "composition": {
            "framing": "cinematic narrative medium-wide shot" if role != "COVER" else "key art with lower subject placement",
            "title_safe_area": "top 28 percent" if role == "COVER" else None,
            "face_unobstructed": True,
        },
        "control_guidance": {
            "priority": ["depth", "openpose", "canny", "segmentation"],
            "inputs": [],
            "fallback": "prompt_and_coordinate_layout",
        },
    }


def _subject_positions(count: int, role: str) -> list[dict[str, float]]:
    positions = {
        1: [0.5],
        2: [0.34, 0.66],
        3: [0.22, 0.5, 0.78],
    }.get(count, [(index + 1) / (count + 1) for index in range(count)])
    y = 0.64 if role == "COVER" else 0.55
    return [{"x": round(x, 3), "y": y} for x in positions]


def _prop_state(prop: str, text: str) -> str:
    if any(term in text for term in ("rách", "torn", "vỡ", "broken")):
        return "damaged"
    if prop == "rain":
        return "falling"
    return "story-consistent"


def create_visual_bible(
    story: dict[str, Any], story_sha256: str, profile: Profile,
    series_anchor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    character_locks = []
    for character in story["characters"]:
        visual_identity = character.get("visual_identity") or {
            "presentation": "UNSPECIFIED", "hair": "locked by reference image",
            "wardrobe": "contemporary age-appropriate clothing",
            "palette": ["story_blue", "warm_neutral"],
            "silhouette": "age-appropriate natural proportions",
            "cultural_context": "contemporary Vietnamese setting",
        }
        character_locks.append(
            {
                "character_id": character["character_id"],
                "name": character["name"],
                "canonical_age_range": [character["canonical_age_min"], character["canonical_age_max"]],
                "identity_traits": character["identity_traits"],
                "presentation": visual_identity["presentation"],
                "hair": visual_identity["hair"],
                "wardrobe": visual_identity["wardrobe"],
                "palette": visual_identity["palette"],
                "silhouette": visual_identity["silhouette"],
                "cultural_context": visual_identity["cultural_context"],
                "reference_image": character["reference_asset"]["reference_image"],
                "reference_sha256": character["reference_asset"]["file_sha256"],
                "master_reference_set": {
                    "strategy": "ROLE_BOUND_REFERENCE_SET_V1",
                    "views": [
                        {
                            "view_id": "full_body_front",
                            "source_image": character["reference_asset"]["reference_image"],
                            "source_sha256": character["reference_asset"]["file_sha256"],
                            "crop_box_normalized": [0.0, 0.0, 1.0, 1.0],
                            "availability": "PRIMARY_AVAILABLE",
                        },
                        {
                            "view_id": "face_closeup",
                            "source_image": character["reference_asset"]["reference_image"],
                            "source_sha256": character["reference_asset"]["file_sha256"],
                            "crop_box_normalized": [0.2, 0.0, 0.8, 0.46],
                            "availability": "CROP_HINT_AVAILABLE",
                        },
                        {
                            "view_id": "three_quarter",
                            "source_image": character["reference_asset"]["reference_image"],
                            "source_sha256": character["reference_asset"]["file_sha256"],
                            "crop_box_normalized": [0.08, 0.02, 0.92, 0.88],
                            "availability": "DERIVATION_PENDING",
                        },
                    ],
                    "default_outfit": visual_identity["wardrobe"],
                    "palette": visual_identity["palette"],
                },
                "adult_visual_status": character["adult_visual_eligibility"],
            }
        )
    return {
        "schema_version": stage2_config()["visual_bible_schema_version"],
        "story_sha256": story_sha256,
        "active_profile": profile.value,
        "age_profile": "KIDS_7_10" if profile is Profile.YOUTH_SAFE else None,
        "art_direction_id": "serial_modern_noir_v1" if series_anchor else "cinematic_storybook_v1",
        "tonal_plan": {
            "palette": ["deep_blue", "warm_amber", "rain_green"],
            "color_temperature": "balanced_warm_subject_cool_background",
            "lighting": "soft_key_with_clear_subject_separation",
            "target_median_luma_band": [72, 196],
        },
        "character_identity_locks": character_locks,
        "wardrobe_state_map": {basename: [] for basename in basenames()},
        "recurring_location_locks": (
            series_anchor["canon"]["visual_bible"]["recurring_locations"]
            if series_anchor else ["garden_after_rain", "quiet_library", "river_at_dusk"]
        ),
        "prop_color_anchors": [{"prop": "promise_token", "color": "warm_amber"}],
        "approved_story_symbols": [],
        "landscape_reference_map": {item["character_id"]: [] for item in story["characters"]},
        "dependency_digest": None,
    }


def finalize_documents(
    plan: dict[str, Any], bible: dict[str, Any], commits: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    for asset in plan["assets"]:
        commit = commits[asset["basename"]]
        asset["landscape_image"] = commit.plan_binding()
        asset["validation_status"] = "PASS"
        for character_id in asset["focal_character_ids"]:
            bible["landscape_reference_map"][character_id].append(asset["basename"])
        bible["wardrobe_state_map"][asset["basename"]] = [
            {
                "character_id": character_id,
                "wardrobe_state_id": "base_outfit",
                "sensuality_level": "NONE",
                "context_override": "NONE",
                "exposure_boundary": "SAFE",
                "accessory_ids": [],
                "source_reference_basename": asset["basename"],
                "landscape_pixel_sha256": commit.file_sha256,
            }
            for character_id in asset["focal_character_ids"]
        ]
    plan["visual_plan_digest_sha256"] = digest_with_null(plan, "visual_plan_digest_sha256")
    bible["dependency_digest"] = digest_with_null(bible, "dependency_digest")
    return plan, bible
