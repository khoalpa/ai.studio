from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def build_story_contract(brief: str, language: str = "vi") -> dict[str, Any]:
    """Extract fail-closed constraints that are explicit in a content brief.

    This first version deliberately handles only high-confidence deterministic facts.
    Model-assisted extraction can extend the contract later without weakening these rules.
    """
    text = _normalized(brief)
    protagonist_match = re.match(r"\s*([A-ZÀ-Ỹ][^,\s]*),", unicodedata.normalize("NFC", brief))
    protagonist = protagonist_match.group(1) if protagonist_match else None
    age_match = re.search(r"\b(\d{1,2})\s*tuổi\b", text)
    protagonist_age = int(age_match.group(1)) if age_match else None

    entities: list[dict[str, Any]] = []
    if protagonist:
        entities.append({
            "entity_id": "protagonist",
            "name": protagonist,
            "role": "PROTAGONIST",
            "age_min": protagonist_age,
            "age_max": protagonist_age,
            "evidence": protagonist_match.group(0).strip() if protagonist_match else protagonist,
        })
    relationships: list[dict[str, Any]] = []
    if re.search(r"\bmẹ\b", text):
        entities.append({
            "entity_id": "mother",
            "name": "Mẹ",
            "role": "PARENT",
            "age_min": 18,
            "age_max": 120,
            "evidence": "mẹ",
        })
        relationships.append({
            "subject": "mother",
            "predicate": "PARENT_OF",
            "object": "protagonist",
            "evidence": "mẹ",
        })

    scenario = "GENERAL"
    requirements: list[dict[str, Any]] = []
    invariants: list[dict[str, Any]] = []
    forbidden_outcomes: list[dict[str, Any]] = []
    if "bão" in text and any(term in text for term in ("sơ tán", "ngôi nhà", "an toàn")):
        scenario = "STORM_EVACUATION"
        requirements = [
            {
                "requirement_id": "storm_approaches",
                "kind": "SETUP",
                "anchors": ["bão", "gió", "mưa"],
                "allowed_zones": ["OPENING", "INTRODUCTION"],
            },
            {
                "requirement_id": "secure_home",
                "kind": "ACTION",
                "anchors": ["chằng", "đóng cửa", "khóa cửa", "gia cố", "bảo vệ ngôi nhà"],
                "allowed_zones": ["INTRODUCTION", "DEVELOPMENT", "CLIMAX"],
            },
            {
                "requirement_id": "move_valuables",
                "kind": "ACTION",
                "anchors": ["di chuyển", "cất", "giấy tờ", "vật dụng", "đồ đạc", "kỷ vật"],
                "allowed_zones": ["INTRODUCTION", "DEVELOPMENT", "CLIMAX"],
            },
            {
                "requirement_id": "evacuate_safely",
                "kind": "OUTCOME",
                "anchors": ["sơ tán", "rời nhà", "nơi trú", "đến nơi an toàn"],
                "allowed_zones": ["FALLING", "ENDING"],
            },
        ]
        invariants = [
            {"invariant_id": "storm_deadline_active", "initial_state": "STORM_APPROACHING", "required_final_state": "FAMILY_EVACUATED"},
            {"invariant_id": "child_safety", "initial_state": "ADULT_SUPERVISION_REQUIRED", "required_final_state": "ADULT_SUPERVISION_PRESERVED"},
        ]
        forbidden_outcomes = [
            {"outcome_id": "child_handles_storm_hazard_alone", "anchors": ["tự trèo", "một mình ra ngoài", "tự sửa điện", "tự lên mái"]},
        ]
    elif "thuyền" in text and any(term in text for term in ("rách", "vết rách")):
        scenario = "TORN_BOAT_GRIEF"
        requirements = [
            {
                "requirement_id": "boat_damaged",
                "kind": "SETUP",
                "anchors": ["thuyền", "rách", "vết rách"],
                "allowed_zones": ["OPENING", "INTRODUCTION"],
            },
            {
                "requirement_id": "reject_replacement",
                "kind": "ACTION",
                "anchors": ["từ chối thuyền thay thế", "không nhận thuyền mới"],
                "allowed_zones": ["DEVELOPMENT", "CLIMAX"],
            },
            {
                "requirement_id": "seek_mother_support",
                "kind": "ACTION",
                "anchors": ["xin mẹ ôm", "mẹ ngồi bên", "mẹ ôm"],
                "allowed_zones": ["INTRODUCTION", "DEVELOPMENT", "CLIMAX"],
            },
            {
                "requirement_id": "preserve_torn_boat",
                "kind": "OUTCOME",
                "anchors": ["giữ chiếc thuyền còn vết rách", "thuyền không lành lại", "giữ vết rách"],
                "allowed_zones": ["FALLING", "ENDING"],
            },
        ]
        invariants = [
            {
                "invariant_id": "boat_remains_torn",
                "initial_state": "BOAT_TORN",
                "required_final_state": "BOAT_TORN_AND_PRESERVED",
            },
        ]
        forbidden_outcomes = [
            {
                "outcome_id": "boat_restored",
                "anchors": ["thuyền lành lại", "vá xong chiếc thuyền", "chiếc thuyền như mới"],
            },
        ]
    elif "chim non" in text and "tổ" in text:
        scenario = "LOST_BIRD_RETURN"
        requirements = [
            {
                "requirement_id": "bird_found_lost",
                "kind": "SETUP",
                "anchors": ["chim non", "bị lạc"],
                "allowed_zones": ["OPENING", "INTRODUCTION"],
            },
            {
                "requirement_id": "seek_adult_help",
                "kind": "ACTION",
                "anchors": ["nhờ người lớn", "gọi người lớn", "nhờ mẹ", "nhờ bố"],
                "allowed_zones": ["INTRODUCTION", "DEVELOPMENT", "CLIMAX"],
            },
            {
                "requirement_id": "bird_returned_to_nest",
                "kind": "OUTCOME",
                "anchors": ["về tổ", "trở lại tổ", "đặt vào tổ"],
                "allowed_zones": ["CLIMAX", "FALLING", "ENDING"],
            },
        ]
        invariants = [
            {"invariant_id": "child_does_not_climb_in_rain", "initial_state": "ADULT_HELP_REQUIRED", "required_final_state": "ADULT_HELP_USED"},
        ]
        forbidden_outcomes = [
            {"outcome_id": "child_climbs_in_rain", "anchors": ["tự trèo cây", "trèo cây trong mưa", "một mình trèo cây"]},
        ]

    return {
        "schema_version": "1.0",
        "language": language,
        "scenario": scenario,
        "entities": entities,
        "relationships": relationships,
        "requirements": requirements,
        "invariants": invariants,
        "forbidden_outcomes": forbidden_outcomes,
    }


def build_outline_evidence(
    story: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    outline = {
        str(zone).upper(): _normalized(str(value))
        for zone, value in story.get("outline", {}).items()
    }
    bindings = []
    for requirement in contract.get("requirements", []):
        zones = []
        anchors = []
        for zone in requirement.get("allowed_zones", []):
            text = outline.get(str(zone).upper(), "")
            matched = [anchor for anchor in requirement.get("anchors", []) if anchor in text]
            if matched:
                zones.append(str(zone).upper())
                anchors.extend(matched)
        bindings.append({
            "requirement_id": requirement.get("requirement_id"),
            "zones": zones,
            "matched_anchors": list(dict.fromkeys(anchors)),
            "status": "BOUND" if zones else "UNBOUND",
        })
    digest = hashlib.sha256(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "1.0",
        "story_contract_digest_sha256": digest,
        "requirement_bindings": bindings,
        "unbound_requirement_count": sum(item["status"] == "UNBOUND" for item in bindings),
    }
