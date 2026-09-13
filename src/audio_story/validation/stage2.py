"""Deterministic Stage 2 intake and CURRENT sidecar contracts."""

from __future__ import annotations

import json
import re
import zipfile
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from audio_story.domain.stage1 import Stage1Error, resolve_profile
from audio_story.domain.stage2 import ZONE_IMAGE_BASENAMES, Stage1PackageInput, Stage2Error
from audio_story.validation.archives import inspect_zip
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.schemas import validate_schema
from audio_story.validation.stage1 import (
    ordered_json_bytes,
    validate_anchor_bytes,
    validate_character_assets,
    validate_manifest_bytes,
    validate_report_bytes,
    validate_story_bytes,
)
from audio_story.validation.strict_json import OrderedObject, parse_json_bytes, validate_field_order

VISUAL_PLAN_ROOT = (
    "schema_version",
    "story_sha256",
    "story_validation_sha256",
    "requested_mode",
    "resolved_mode",
    "scene_source_digest_sha256",
    "selected_scene_count",
    "assets",
    "selection_coverage",
    "visual_plan_digest_sha256",
)
VISUAL_PLAN_ASSET_ROOT = (
    "asset_id",
    "basename",
    "role",
    "ordinal",
    "zone",
    "scene_id",
    "script_item_start",
    "script_item_end",
    "focal_character_ids",
    "visual_moment",
    "state_delta_to_show",
    "selection_basis",
    "landscape_image",
    "portrait_image",
    "validation_status",
)
SELECTION_COVERAGE_ROOT = (
    "source_scene_count",
    "selected_scene_count",
    "omitted_scene_count",
    "covered_zones",
    "required_zone_gap_count",
    "climax_covered",
    "ending_covered",
    "max_count_applied",
)
VISUAL_BIBLE_ROOT = (
    "schema_version",
    "story_sha256",
    "active_profile",
    "age_profile",
    "art_direction_id",
    "tonal_plan",
    "character_identity_locks",
    "wardrobe_state_map",
    "recurring_location_locks",
    "prop_color_anchors",
    "approved_story_symbols",
    "landscape_reference_map",
    "dependency_digest",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ROLES = {"COVER", "GREETING", "ZONE", "SCENE", "FAREWELL", "OUTRO"}
_MODES = {"ZONE", "SCENE"}
_REQUEST_MODES = {"AUTO", "ZONE", "SCENE"}
_STATUSES = {"PASS", "FAIL", "NOT_VERIFIED", "NOT_APPLICABLE"}


def load_stage1_package(path: Path, *, test_mode: bool = False) -> Stage1PackageInput:
    """Validate a Stage 1 ZIP without extracting or modifying its source bytes."""
    source = path.resolve(strict=True)
    before = source.read_bytes()
    inspected = inspect_zip(source)
    names = [item.path for item in inspected]
    if not names or names[0] != "workflow_manifest.json":
        _fail("M7A001_MEMBER_ORDER", "manifest must be the first member", str(source))
    try:
        with zipfile.ZipFile(source) as archive:
            payload = OrderedDict((name, archive.read(name)) for name in names)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        _fail("M7A002_PACKAGE_READ", f"cannot read package: {exc}", str(source))
    manifest_bytes = payload.pop("workflow_manifest.json")
    try:
        manifest = cast(
            OrderedObject,
            parse_json_bytes(manifest_bytes, "workflow_manifest.json", engine_generated=True).value,
        )
        profile_value = manifest.get("active_profile")
        profile = profile_value if isinstance(profile_value, str) else None
        language = json.loads(payload.get("story.json", b"{}")).get("meta", {}).get("language")
        contract = resolve_profile(profile if isinstance(profile, str) else None, language)
        story_bytes = payload["story.json"]
        report_bytes = payload["story_validation.json"]
        story = validate_story_bytes(story_bytes, contract)
        report = validate_report_bytes(report_bytes, story_bytes, story)
        character_paths = [
            item["reference_asset"]["reference_image"] for item in story["characters"]
        ]
        character_assets = OrderedDict((name, payload[name]) for name in character_paths)
        validate_character_assets(story, character_assets, test_mode=test_mode)
        assert profile is not None
        validate_manifest_bytes(manifest_bytes, payload, profile)
        anchor = payload.get("series_anchor.json")
        if anchor is not None:
            validate_anchor_bytes(anchor, story)
    except (KeyError, TypeError, json.JSONDecodeError, Stage1Error) as exc:
        if isinstance(exc, Stage1Error):
            _fail("M7A003_STAGE1_CONTRACT", str(exc), exc.locator)
        _fail("M7A003_STAGE1_CONTRACT", f"missing or malformed Stage 1 member: {exc}", str(source))
    if source.read_bytes() != before:
        _fail("M7A004_SOURCE_MUTATED", "source package changed during intake", str(source))
    return Stage1PackageInput(
        source,
        sha256_bytes(before),
        manifest_bytes,
        story_bytes,
        report_bytes,
        character_assets,
        anchor,
        manifest,
        story,
        report,
    )


def serialize_visual_plan(value: Mapping[str, Any]) -> bytes:
    """Serialize and reopen a strict CURRENT visual plan."""
    materialized = OrderedDict(value)
    materialized["visual_plan_digest_sha256"] = None
    materialized["visual_plan_digest_sha256"] = sha256_bytes(canonical_json_bytes(materialized))
    data = ordered_json_bytes(materialized)
    validate_visual_plan_bytes(data)
    return data


def validate_visual_plan_bytes(data: bytes) -> OrderedObject:
    parsed = _ordered(data, "visual_plan.json")
    validate_schema(parsed, "visual_plan.json", "INPUT", "visual_plan.json")
    _digest(parsed.get("story_sha256"), "M7A110_STORY_DIGEST", "$.story_sha256")
    _digest(
        parsed.get("story_validation_sha256"), "M7A111_REPORT_DIGEST", "$.story_validation_sha256"
    )
    _digest(
        parsed.get("scene_source_digest_sha256"),
        "M7A112_SCENE_DIGEST",
        "$.scene_source_digest_sha256",
    )
    _require(
        parsed.get("requested_mode") in _REQUEST_MODES, "M7A113_REQUEST_MODE", "$.requested_mode"
    )
    _require(parsed.get("resolved_mode") in _MODES, "M7A114_RESOLVED_MODE", "$.resolved_mode")
    assets = parsed.get("assets")
    _require(isinstance(assets, list), "M7A115_ASSETS", "$.assets")
    assert isinstance(assets, list)
    seen_ids: set[str] = set()
    basenames: list[str] = []
    for index, asset in enumerate(assets):
        validate_field_order(
            asset, VISUAL_PLAN_ASSET_ROOT, "visual_plan.json", f"$.assets[{index}]"
        )
        aid, basename = asset.get("asset_id"), asset.get("basename")
        _require(
            isinstance(aid, str) and bool(aid) and aid not in seen_ids,
            "M7A116_ASSET_ID",
            f"$.assets[{index}].asset_id",
        )
        _require(isinstance(basename, str), "M7A117_BASENAME", f"$.assets[{index}].basename")
        seen_ids.add(cast(str, aid))
        basenames.append(cast(str, basename))
        _require(asset.get("ordinal") == index + 1, "M7A118_ORDINAL", f"$.assets[{index}].ordinal")
        _require(asset.get("role") in _ROLES, "M7A119_ROLE", f"$.assets[{index}].role")
        _require(
            asset.get("validation_status") in _STATUSES,
            "M7A120_STATUS",
            f"$.assets[{index}].validation_status",
        )
    selected = parsed.get("selected_scene_count")
    _require(
        isinstance(selected, int) and selected >= 0,
        "M7A121_SELECTED_COUNT",
        "$.selected_scene_count",
    )
    coverage = parsed.get("selection_coverage")
    validate_field_order(
        coverage, SELECTION_COVERAGE_ROOT, "visual_plan.json", "$.selection_coverage"
    )
    assert isinstance(coverage, OrderedObject)
    _require(
        coverage.get("selected_scene_count") == selected,
        "M7A122_COVERAGE_COUNT",
        "$.selection_coverage.selected_scene_count",
    )
    if parsed.get("resolved_mode") == "ZONE":
        _require(tuple(basenames) == ZONE_IMAGE_BASENAMES, "M7A123_ZONE_SET", "$.assets")
        _require(selected == 0, "M7A121_SELECTED_COUNT", "$.selected_scene_count")
        _require(
            all(asset.get("role") != "SCENE" for asset in assets), "M7A124_MIXED_MODE", "$.assets"
        )
        fixed_roles = {
            "cover.png": "COVER",
            "greeting.png": "GREETING",
            "farewell.png": "FAREWELL",
            "outro.png": "OUTRO",
        }
        for index, asset in enumerate(assets):
            basename = asset["basename"]
            expected_role = fixed_roles.get(basename, "ZONE")
            _require(asset["role"] == expected_role, "M7A126_ZONE_ROLE", f"$.assets[{index}].role")
            _require(
                asset["landscape_image"] == f"landscape/{basename}"
                and asset["portrait_image"] == f"portrait/{basename}",
                "M7A127_IMAGE_PATH",
                f"$.assets[{index}]",
            )
            _require(
                asset["script_item_start"] is None and asset["script_item_end"] is None,
                "M7A128_ZONE_SPAN",
                f"$.assets[{index}]",
            )
    expected = parsed.get("visual_plan_digest_sha256")
    _digest(expected, "M7A125_PLAN_DIGEST", "$.visual_plan_digest_sha256")
    projection = OrderedDict(parsed)
    projection["visual_plan_digest_sha256"] = None
    _require(
        expected == sha256_bytes(canonical_json_bytes(projection)),
        "M7A125_PLAN_DIGEST",
        "$.visual_plan_digest_sha256",
    )
    return parsed


def serialize_visual_bible(value: Mapping[str, Any]) -> bytes:
    data = ordered_json_bytes(OrderedDict(value))
    validate_visual_bible_bytes(data)
    return data


def validate_visual_bible_bytes(data: bytes) -> OrderedObject:
    parsed = _ordered(data, "visual_bible.json")
    validate_schema(parsed, "visual_bible.json", "INPUT", "visual_bible.json")
    _digest(parsed.get("story_sha256"), "M7A210_STORY_DIGEST", "$.story_sha256")
    _digest(parsed.get("dependency_digest"), "M7A211_DEPENDENCY_DIGEST", "$.dependency_digest")
    _require(isinstance(parsed.get("active_profile"), str), "M7A212_PROFILE", "$.active_profile")
    _require(
        isinstance(parsed.get("art_direction_id"), str) and bool(parsed["art_direction_id"]),
        "M7A213_ART_DIRECTION",
        "$.art_direction_id",
    )
    wardrobe = parsed.get("wardrobe_state_map")
    references = parsed.get("landscape_reference_map")
    _require(isinstance(wardrobe, dict), "M7A214_WARDROBE_MAP", "$.wardrobe_state_map")
    _require(isinstance(references, dict), "M7A215_REFERENCE_MAP", "$.landscape_reference_map")
    assert isinstance(wardrobe, dict)
    assert isinstance(references, dict)
    _require(
        tuple(wardrobe) in {(), ZONE_IMAGE_BASENAMES}, "M7A216_WARDROBE_SET", "$.wardrobe_state_map"
    )
    _require(
        tuple(references) in {(), ZONE_IMAGE_BASENAMES},
        "M7A217_REFERENCE_SET",
        "$.landscape_reference_map",
    )
    return parsed


def _ordered(data: bytes, name: str) -> OrderedObject:
    value = parse_json_bytes(data, name, engine_generated=True).value
    _require(isinstance(value, OrderedObject), "M7A100_ROOT", "$")
    return cast(OrderedObject, value)


def _digest(value: object, code: str, locator: str) -> None:
    _require(isinstance(value, str) and bool(_HEX64.fullmatch(value)), code, locator)


def _require(condition: bool, code: str, locator: str) -> None:
    if not condition:
        raise Stage2Error(code, "Stage 2 contract violation", locator)


def _fail(code: str, message: str, locator: str) -> None:
    raise Stage2Error(code, message, locator)
