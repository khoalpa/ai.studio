"""Pure deterministic M7-B ZONE planning and invocation firewall."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from typing import Any, cast

from audio_story.domain.stage2 import (
    ZONE_EXECUTION_QUEUE,
    ZONE_IMAGE_BASENAMES,
    Stage1PackageInput,
    Stage2Error,
    Stage2Invocation,
    Stage2ZonePlan,
)
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage2 import (
    serialize_visual_bible,
    serialize_visual_plan,
    validate_visual_bible_bytes,
    validate_visual_plan_bytes,
)

LANDSCAPE_DIMENSIONS = (3840, 2160)
_FIXED_ROLES = {
    "cover.png": "COVER",
    "greeting.png": "GREETING",
    "farewell.png": "FAREWELL",
    "outro.png": "OUTRO",
}
_BASENAME_ZONES = {
    "introduction.png": "INTRODUCTION",
    "opening.png": "OPENING",
    "development.png": "DEVELOPMENT",
    "climax.png": "CLIMAX",
    "falling.png": "FALLING",
    "ending.png": "ENDING",
    "greeting.png": "GREETING",
    "farewell.png": "FAREWELL",
}
_PAYLOAD_ROOT = (
    "target",
    "scene",
    "visual_locks",
    "text_policy",
    "negative_constraints",
)
_FORBIDDEN_CONTEXT_KEYS = {
    "manifest",
    "package",
    "checkpoint",
    "progress",
    "dashboard",
    "storyboard",
    "future_basenames",
    "all_basenames",
    "output_count",
}


def build_stage2_zone_plan(source: Stage1PackageInput) -> Stage2ZonePlan:
    """Build both Stage 2 sidecars and freeze the canonical ten-item queue."""
    story = source.story
    report = source.story_validation
    story_digest = sha256_bytes(source.story_bytes)
    report_digest = sha256_bytes(source.story_validation_bytes)
    scenes = _sequence(report.get("scene_zone_map"), "M7B001_SCENE_MAP", "$.scene_zone_map")
    scene_digest = sha256_bytes(canonical_json_bytes(scenes))
    characters = _sequence(story.get("characters"), "M7B002_CHARACTERS", "$.characters")
    script = _sequence(story.get("script"), "M7B003_SCRIPT", "$.script")
    visual_plan = _build_visual_plan(
        story_digest, report_digest, scene_digest, scenes, characters, script
    )
    bible = _build_visual_bible(source, story_digest, characters)
    plan_bytes = serialize_visual_plan(visual_plan)
    bible_bytes = serialize_visual_bible(bible)
    validate_stage2_plan_bindings(source, plan_bytes, bible_bytes)
    return Stage2ZonePlan(
        plan_bytes,
        bible_bytes,
        ZONE_IMAGE_BASENAMES,
        ZONE_EXECUTION_QUEUE,
        "introduction.png",
        "opening.png",
    )


def validate_stage2_plan_bindings(
    source: Stage1PackageInput, visual_plan_bytes: bytes, visual_bible_bytes: bytes
) -> None:
    plan = validate_visual_plan_bytes(visual_plan_bytes)
    bible = validate_visual_bible_bytes(visual_bible_bytes)
    story_digest = sha256_bytes(source.story_bytes)
    _require(plan["story_sha256"] == story_digest, "M7B010_PLAN_STORY_BINDING", "$.story_sha256")
    _require(
        plan["story_validation_sha256"] == sha256_bytes(source.story_validation_bytes),
        "M7B011_PLAN_REPORT_BINDING",
        "$.story_validation_sha256",
    )
    scenes = _sequence(
        source.story_validation.get("scene_zone_map"),
        "M7B001_SCENE_MAP",
        "$.scene_zone_map",
    )
    _require(
        plan["scene_source_digest_sha256"] == sha256_bytes(canonical_json_bytes(scenes)),
        "M7B014_SCENE_SOURCE_BINDING",
        "$.scene_source_digest_sha256",
    )
    _require(bible["story_sha256"] == story_digest, "M7B012_BIBLE_STORY_BINDING", "$.story_sha256")
    _require(
        bible["active_profile"] == source.manifest["active_profile"],
        "M7B013_BIBLE_PROFILE_BINDING",
        "$.active_profile",
    )
    dependency = OrderedDict(
        story_sha256=story_digest,
        character_reference_set_digest_sha256=source.story_validation[
            "character_reference_set_digest_sha256"
        ],
        character_identity_locks=bible["character_identity_locks"],
        wardrobe_state_map=bible["wardrobe_state_map"],
        landscape_reference_map=bible["landscape_reference_map"],
    )
    _require(
        bible["dependency_digest"] == sha256_bytes(canonical_json_bytes(dependency)),
        "M7B015_BIBLE_DEPENDENCY_BINDING",
        "$.dependency_digest",
    )


def compile_stage2_invocation(
    plan: Stage2ZonePlan, basename: str, *, committed_basenames: Sequence[str] = ()
) -> Stage2Invocation:
    """Compile one basename-scoped LANDSCAPE call without invoking a backend."""
    _require(basename in plan.execution_queue, "M7B100_UNKNOWN_BASENAME", "$.target_basename")
    expected_next = next(
        (item for item in plan.execution_queue if item not in committed_basenames), None
    )
    _require(basename == expected_next, "M7B101_QUEUE_ORDER", "$.target_basename")
    visual_plan = validate_visual_plan_bytes(plan.visual_plan_bytes)
    bible = validate_visual_bible_bytes(plan.visual_bible_bytes)
    asset = next(item for item in visual_plan["assets"] if item["basename"] == basename)
    identity_ids = set(asset["focal_character_ids"])
    identity_locks = [
        item for item in bible["character_identity_locks"] if item["character_id"] in identity_ids
    ]
    references = tuple(item["reference_image"] for item in identity_locks)
    wardrobe_map = cast(Mapping[str, Any], bible["wardrobe_state_map"])
    payload = OrderedDict(
        target=OrderedDict(
            basename=basename,
            orientation="LANDSCAPE",
            dimensions=OrderedDict(width=3840, height=2160),
        ),
        scene=OrderedDict(
            objective=asset["visual_moment"],
            characters=list(asset["focal_character_ids"]),
            action=asset["state_delta_to_show"],
            environment=asset["zone"],
        ),
        visual_locks=OrderedDict(
            art_direction_id=bible["art_direction_id"],
            identity_references=references,
            wardrobe_state=wardrobe_map[basename],
        ),
        text_policy="COVER_TEXT_RESERVED" if basename == "cover.png" else "NO_TEXT",
        negative_constraints=[
            "single full-frame scene",
            "no storyboard, contact sheet, dashboard, collage, grid, UI, or multiple panels",
            "no unintended text, logo, watermark, border, or frame",
        ],
    )
    invocation = Stage2Invocation(
        "STAGE2",
        "LANDSCAPE",
        basename,
        "FINAL_REQUIRED_ASSET",
        1,
        *LANDSCAPE_DIMENSIONS,
        references,
        payload,
    )
    validate_stage2_invocation(invocation, plan)
    return invocation


def validate_stage2_invocation(invocation: Stage2Invocation, plan: Stage2ZonePlan) -> str:
    """Fail closed on stage, target, cardinality, reference, and context scope."""
    _require(invocation.stage == "STAGE2", "M7B110_STAGE", "$.stage")
    _require(invocation.orientation == "LANDSCAPE", "M7B111_ORIENTATION", "$.orientation")
    _require(
        invocation.target_basename in plan.execution_queue, "M7B112_TARGET", "$.target_basename"
    )
    _require(
        invocation.generator_call_intent == "FINAL_REQUIRED_ASSET",
        "M7B113_INTENT",
        "$.generator_call_intent",
    )
    _require(
        invocation.requested_output_count == 1, "M7B114_CARDINALITY", "$.requested_output_count"
    )
    _require(
        (invocation.requested_width, invocation.requested_height) == LANDSCAPE_DIMENSIONS,
        "M7B115_DIMENSIONS",
        "$.dimensions",
    )
    _require(tuple(invocation.payload) == _PAYLOAD_ROOT, "M7B116_PAYLOAD_ROOT", "$.payload")
    target = _mapping(invocation.payload.get("target"), "M7B117_TARGET_SCOPE", "$.payload.target")
    _require(
        target.get("basename") == invocation.target_basename,
        "M7B117_TARGET_SCOPE",
        "$.payload.target.basename",
    )
    locks = _mapping(
        invocation.payload.get("visual_locks"), "M7B118_REFERENCE_SCOPE", "$.payload.visual_locks"
    )
    _require(
        tuple(locks.get("identity_references", ())) == invocation.explicit_references,
        "M7B118_REFERENCE_SCOPE",
        "$.explicit_references",
    )
    keys = _all_keys(invocation.payload)
    _require(not keys.intersection(_FORBIDDEN_CONTEXT_KEYS), "M7B119_GLOBAL_CONTEXT", "$.payload")
    serialized = canonical_json_bytes(invocation.payload).decode("utf-8")
    foreign = [
        name
        for name in plan.execution_queue
        if name != invocation.target_basename and name in serialized
    ]
    _require(not foreign, "M7B120_FUTURE_BASENAME", "$.payload")
    return sha256_bytes(canonical_json_bytes(invocation.payload))


def _build_visual_plan(
    story_digest: str,
    report_digest: str,
    scene_digest: str,
    scenes: Sequence[Any],
    characters: Sequence[Any],
    script: Sequence[Any],
) -> OrderedDict[str, Any]:
    focal = [item["character_id"] for item in characters if item.get("role") == "protagonist"]
    if not focal:
        focal = [characters[0]["character_id"]]
    assets = []
    for ordinal, basename in enumerate(ZONE_IMAGE_BASENAMES, 1):
        role = _FIXED_ROLES.get(basename, "ZONE")
        zone = _BASENAME_ZONES.get(basename)
        source_item = next((item for item in script if item.get("zone") == zone), None)
        moment = _moment_for(basename, source_item)
        assets.append(
            OrderedDict(
                asset_id=f"stage2:landscape:{basename.removesuffix('.png')}",
                basename=basename,
                role=role,
                ordinal=ordinal,
                zone=zone,
                scene_id=None,
                script_item_start=None,
                script_item_end=None,
                focal_character_ids=focal if role in {"ZONE", "COVER"} else [],
                visual_moment=moment,
                state_delta_to_show=_state_delta(zone),
                selection_basis="REPRESENTATIVE_ZONE" if role == "ZONE" else None,
                landscape_image=f"landscape/{basename}",
                portrait_image=f"portrait/{basename}",
                validation_status="NOT_VERIFIED",
            )
        )
    covered = list(dict.fromkeys(item["zone"] for item in assets if item["zone"] is not None))
    return OrderedDict(
        schema_version="1.0",
        story_sha256=story_digest,
        story_validation_sha256=report_digest,
        requested_mode="ZONE",
        resolved_mode="ZONE",
        scene_source_digest_sha256=scene_digest,
        selected_scene_count=0,
        assets=assets,
        selection_coverage=OrderedDict(
            source_scene_count=len(scenes),
            selected_scene_count=0,
            omitted_scene_count=0,
            covered_zones=covered,
            required_zone_gap_count=0,
            climax_covered="CLIMAX" in covered,
            ending_covered="ENDING" in covered,
            max_count_applied=False,
        ),
        visual_plan_digest_sha256=None,
    )


def _build_visual_bible(
    source: Stage1PackageInput, story_digest: str, characters: Sequence[Any]
) -> OrderedDict[str, Any]:
    profile = cast(str, source.manifest["active_profile"])
    locks = [
        OrderedDict(
            character_id=item["character_id"],
            name=item["name"],
            canonical_age=item["age"],
            apparent_age=item["age"],
            role=item["role"],
            identity_description=item["description"],
            identity_lock=item["reference_asset"]["identity_lock"],
            reference_image=item["reference_asset"]["reference_image"],
            reference_file_sha256=item["reference_asset"]["file_sha256"],
            base_outfit="profile-safe story-consistent outfit",
            signature_accessories=[],
            exposure_permission="NONE" if profile == "YOUTH_SAFE" else "PROFILE_DEFAULT",
        )
        for item in characters
    ]
    wardrobe: OrderedDict[str, list[Any]] = OrderedDict((name, []) for name in ZONE_IMAGE_BASENAMES)
    references: OrderedDict[str, None] = OrderedDict((name, None) for name in ZONE_IMAGE_BASENAMES)
    art_direction_id = (
        "art:"
        + sha256_bytes(
            canonical_json_bytes({"profile": profile, "tone": source.story["meta"]["tone"]})
        )[:16]
    )
    dependency = OrderedDict(
        story_sha256=story_digest,
        character_reference_set_digest_sha256=source.story_validation[
            "character_reference_set_digest_sha256"
        ],
        character_identity_locks=locks,
        wardrobe_state_map=wardrobe,
        landscape_reference_map=references,
    )
    return OrderedDict(
        schema_version="2.0",
        story_sha256=story_digest,
        active_profile=profile,
        age_profile="YOUTH" if profile == "YOUTH_SAFE" else "ADULT",
        art_direction_id=art_direction_id,
        tonal_plan=OrderedDict(
            tone=source.story["meta"]["tone"],
            palette_progression="open shadows, readable faces, clear focal contrast",
            lighting_grammar="bright grounded cinematic lighting",
            lens_grammar="single-scene perspective with natural depth",
        ),
        character_identity_locks=locks,
        wardrobe_state_map=wardrobe,
        recurring_location_locks=[],
        prop_color_anchors=[],
        approved_story_symbols=[],
        landscape_reference_map=references,
        dependency_digest=sha256_bytes(canonical_json_bytes(dependency)),
    )


def _moment_for(basename: str, source_item: Any) -> str:
    if source_item is not None:
        text = str(source_item.get("text", "")).strip()
        return text[:280]
    if basename == "cover.png":
        return "A single iconic story moment with the focal protagonist and clear title-safe space."
    if basename == "outro.png":
        return "A calm full-frame closing atmosphere with deliberate empty space and no text."
    return "A single full-frame story-consistent moment."


def _state_delta(zone: str | None) -> str:
    if zone is None:
        return ""
    return {
        "OPENING": "establish the central question",
        "INTRODUCTION": "make focal identity clearly observable",
        "DEVELOPMENT": "show rising consequence",
        "CLIMAX": "show the irreversible choice",
        "FALLING": "show immediate consequence",
        "ENDING": "show the final changed state",
    }.get(zone, "")


def _sequence(value: object, code: str, locator: str) -> Sequence[Any]:
    _require(isinstance(value, list) and bool(value), code, locator)
    return cast(Sequence[Any], value)


def _mapping(value: object, code: str, locator: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), code, locator)
    return cast(Mapping[str, Any], value)


def _all_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {str(key) for key in value} | set().union(
            *(_all_keys(item) for item in value.values()), set()
        )
    if isinstance(value, list | tuple):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def _require(condition: bool, code: str, locator: str) -> None:
    if not condition:
        raise Stage2Error(code, "Stage 2 planning contract violation", locator)
