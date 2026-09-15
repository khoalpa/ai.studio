"""Pure M8-B portrait adaptation planning and pre-call firewall."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from typing import Any, cast

from audio_story.domain.stage2 import ZONE_IMAGE_BASENAMES
from audio_story.domain.stage3 import (
    Stage2PackageInput,
    Stage3Error,
    Stage3Invocation,
    Stage3PortraitPlan,
)
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes

PORTRAIT_DIMENSIONS = (1080, 1920)
RISK_WEIGHTS = OrderedDict(
    MULTI_CHARACTER_INTERACTION=3,
    FULL_BODY_ANATOMY=2,
    COMPLEX_WARDROBE=2,
    COVER_TYPOGRAPHY=3,
    HIGH_CROP_RISK=2,
    EXPOSURE_SENSITIVE=2,
    IDENTITY_CRITICAL_ACCESSORY=1,
)
_PLAN_ROOT = (
    "basename",
    "semantic_moment",
    "keep_subjects",
    "crop_or_reposition",
    "headroom",
    "body_crop",
    "text_safe_area",
    "lens_adaptation",
    "background_simplification",
    "exposure_boundary",
    "identity_critical_features",
    "landscape_reference",
    "landscape_sha256",
    "character_references",
    "risk_factors",
    "risk_evidence_locators",
)
_PAYLOAD_ROOT = ("target", "scene", "visual_locks", "text_policy", "negative_constraints")
_FORBIDDEN = {
    "manifest",
    "package",
    "checkpoint",
    "progress",
    "batch_requests",
    "all_basenames",
    "future_basenames",
    "storyboard",
}


def build_stage3_portrait_plan(source: Stage2PackageInput) -> Stage3PortraitPlan:
    """Derive all portrait objectives and select the canonical high-risk pilot."""
    assets = cast(Sequence[Mapping[str, Any]], source.visual_plan["assets"])
    bible = source.visual_bible
    locks = cast(Sequence[Mapping[str, Any]], bible["character_identity_locks"])
    by_character = {str(item["character_id"]): item for item in locks}
    authority = {item.path: item for item in source.inherited_authority}
    plan: list[Mapping[str, Any]] = []
    for asset in assets:
        basename = cast(str, asset["basename"])
        focal = tuple(cast(Sequence[str], asset["focal_character_ids"]))
        character_refs = tuple(
            cast(str, by_character[item]["reference_image"])
            for item in focal
            if item in by_character
        )
        landscape_path = f"landscape/{basename}"
        factors: list[str] = ["HIGH_CROP_RISK"]
        locators: list[str] = [f"visual_plan.assets[{basename}].landscape_image"]
        if len(focal) > 1:
            factors.append("MULTI_CHARACTER_INTERACTION")
            locators.append(f"visual_plan.assets[{basename}].focal_character_ids")
        if basename == "introduction.png" and focal:
            factors.extend(("FULL_BODY_ANATOMY", "IDENTITY_CRITICAL_ACCESSORY"))
            locators.extend(
                (
                    f"visual_plan.assets[{basename}].role",
                    f"visual_bible.character_identity_locks[{focal[0]}]",
                )
            )
        wardrobe = cast(Mapping[str, Any], bible["wardrobe_state_map"]).get(basename)
        if wardrobe:
            factors.append("COMPLEX_WARDROBE")
            locators.append(f"visual_bible.wardrobe_state_map.{basename}")
        if basename == "cover.png":
            factors.append("COVER_TYPOGRAPHY")
            locators.append(f"visual_plan.assets[{basename}].role")
        if bible.get("active_profile") != "YOUTH_SAFE" and focal:
            factors.append("EXPOSURE_SENSITIVE")
            locators.append("visual_bible.active_profile")
        record = OrderedDict(
            basename=basename,
            semantic_moment=asset["visual_moment"],
            keep_subjects=list(focal),
            crop_or_reposition="RECOMPOSE_9_16_KEEP_NARRATIVE_FUNCTION",
            headroom="PRESERVE_FACE_AND_ACTION_SAFE_MARGIN",
            body_crop="AVOID_JOINT_AND_IDENTITY_ACCESSORY_CROPS",
            text_safe_area="COVER_RESERVED" if basename == "cover.png" else "NOT_APPLICABLE",
            lens_adaptation="PORTRAIT_DEPTH_WITH_SINGLE_FOCAL_PLANE",
            background_simplification="REMOVE_NONESSENTIAL_EDGE_DETAIL",
            exposure_boundary="PRESERVE_OR_REDUCE_FROM_LANDSCAPE",
            identity_critical_features=[
                by_character[item]["identity_lock"] for item in focal if item in by_character
            ],
            landscape_reference=landscape_path,
            landscape_sha256=authority[landscape_path].sha256,
            character_references=list(character_refs),
            risk_factors=factors,
            risk_evidence_locators=locators,
        )
        _require(tuple(record) == _PLAN_ROOT, "M8B001_PLAN_SHAPE", basename)
        plan.append(record)
    _require(
        tuple(item["basename"] for item in plan) == ZONE_IMAGE_BASENAMES,
        "M8B002_PLAN_SET",
        "adaptation_plan",
    )
    plan_digest = sha256_bytes(canonical_json_bytes(plan))
    scores = OrderedDict(
        (
            cast(str, item["basename"]),
            sum(RISK_WEIGHTS[factor] for factor in cast(Sequence[str], item["risk_factors"])),
        )
        for item in plan
    )
    maximum = max(scores.values())
    winners = [name for name, score in scores.items() if score == maximum]
    winner = "cover.png" if "cover.png" in winners else winners[0]
    tie_breaker = (
        "COVER_TYPOGRAPHY"
        if len(winners) > 1 and winner == "cover.png"
        else "BASENAME_ORDER"
        if len(winners) > 1
        else "NONE"
    )
    evidence_preimage = OrderedDict(
        scores_by_basename=scores,
        winning_basename=winner,
        winning_score=maximum,
        tie_breaker_used=tie_breaker,
        plan_digest_sha256=plan_digest,
    )
    pilot = OrderedDict(evidence_preimage)
    pilot["validation_digest_sha256"] = sha256_bytes(canonical_json_bytes(evidence_preimage))
    queue = (winner, *(name for name in ZONE_IMAGE_BASENAMES if name != winner))
    return Stage3PortraitPlan(tuple(plan), plan_digest, pilot, ZONE_IMAGE_BASENAMES, queue)


def compile_stage3_invocation(
    source: Stage2PackageInput,
    plan: Stage3PortraitPlan,
    basename: str,
    *,
    committed_basenames: Sequence[str] = (),
) -> Stage3Invocation:
    """Compile and independently inspect one basename-scoped portrait request."""
    expected = next(
        (name for name in plan.execution_queue if name not in committed_basenames), None
    )
    _require(basename == expected, "M8B100_QUEUE_ORDER", "$.target_basename")
    record = next(item for item in plan.adaptation_plan if item["basename"] == basename)
    references = (
        cast(str, record["landscape_reference"]),
        *cast(Sequence[str], record["character_references"]),
    )
    payload = OrderedDict(
        target=OrderedDict(
            basename=basename,
            orientation="PORTRAIT",
            dimensions=OrderedDict(width=1080, height=1920),
        ),
        scene=OrderedDict(
            objective=record["semantic_moment"],
            adaptation=record["crop_or_reposition"],
            keep_subjects=record["keep_subjects"],
        ),
        visual_locks=OrderedDict(
            art_direction_id=source.visual_bible["art_direction_id"],
            authoritative_references=references,
            exposure_boundary=record["exposure_boundary"],
        ),
        text_policy="COVER_TEXT_RESERVED" if basename == "cover.png" else "NO_TEXT",
        negative_constraints=[
            "single full-frame portrait scene",
            "no storyboard, contact sheet, collage, grid, UI, or multiple panels",
            "no unintended text, logo, watermark, border, or frame",
        ],
    )
    invocation = Stage3Invocation(
        "STAGE3", "PORTRAIT", basename, "FINAL_REQUIRED_ASSET", 1, 1080, 1920, references, payload
    )
    validate_stage3_invocation(source, plan, invocation)
    return invocation


def validate_stage3_invocation(
    source: Stage2PackageInput, plan: Stage3PortraitPlan, invocation: Stage3Invocation
) -> str:
    """Abort-before-call firewall for exact Stage 3 tool arguments."""
    _require(
        invocation.stage == "STAGE3" and invocation.orientation == "PORTRAIT",
        "M8B110_STAGE",
        "$.stage",
    )
    _require(
        invocation.generator_call_intent == "FINAL_REQUIRED_ASSET",
        "M8B111_INTENT",
        "$.generator_call_intent",
    )
    _require(
        invocation.target_basename in plan.execution_queue, "M8B112_BASENAME", "$.target_basename"
    )
    _require(
        invocation.requested_output_count == 1, "M8B113_CARDINALITY", "$.requested_output_count"
    )
    _require(
        (invocation.requested_width, invocation.requested_height) == PORTRAIT_DIMENSIONS,
        "M8B114_DIMENSIONS",
        "$.dimensions",
    )
    _require(tuple(invocation.payload) == _PAYLOAD_ROOT, "M8B115_PAYLOAD", "$.payload")
    target = cast(Mapping[str, Any], invocation.payload["target"])
    _require(
        target.get("basename") == invocation.target_basename
        and target.get("orientation") == "PORTRAIT",
        "M8B116_TARGET",
        "$.payload.target",
    )
    authority = {item.path: item for item in source.inherited_authority}
    _require(
        all(
            path in authority and sha256_bytes(source.members[path]) == authority[path].sha256
            for path in invocation.explicit_references
        ),
        "M8B117_REFERENCE_AUTHORITY",
        "$.explicit_references",
    )
    keys = _all_keys(invocation.payload)
    _require(not keys.intersection(_FORBIDDEN), "M8B118_GLOBAL_CONTEXT", "$.payload")
    serialized = canonical_json_bytes(invocation.payload).decode("utf-8")
    _require(
        not any(
            name != invocation.target_basename and name in serialized
            for name in plan.execution_queue
        ),
        "M8B119_FOREIGN_BASENAME",
        "$.payload",
    )
    return sha256_bytes(canonical_json_bytes(invocation.payload))


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
        raise Stage3Error(code, "Stage 3 portrait planning contract violation", locator)
