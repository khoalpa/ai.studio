from __future__ import annotations

import json
from collections import OrderedDict

import pytest

from audio_story.domain.stage2 import ZONE_IMAGE_BASENAMES, Stage2Error
from audio_story.validation.stage2 import (
    serialize_visual_bible,
    serialize_visual_plan,
    validate_visual_plan_bytes,
)

HASH = "a" * 64


def _plan() -> OrderedDict[str, object]:
    assets = []
    for index, basename in enumerate(ZONE_IMAGE_BASENAMES, 1):
        role = {
            "cover.png": "COVER",
            "greeting.png": "GREETING",
            "farewell.png": "FAREWELL",
            "outro.png": "OUTRO",
        }.get(basename, "ZONE")
        assets.append(
            OrderedDict(
                asset_id=f"asset:{index}",
                basename=basename,
                role=role,
                ordinal=index,
                zone=None if role != "ZONE" else basename.removesuffix(".png").upper(),
                scene_id=None,
                script_item_start=None,
                script_item_end=None,
                focal_character_ids=[],
                visual_moment=f"Moment {index}",
                state_delta_to_show="",
                selection_basis="REPRESENTATIVE_ZONE" if role == "ZONE" else None,
                landscape_image=f"landscape/{basename}",
                portrait_image=f"portrait/{basename}",
                validation_status="NOT_VERIFIED",
            )
        )
    return OrderedDict(
        schema_version="1.0",
        story_sha256=HASH,
        story_validation_sha256="b" * 64,
        requested_mode="ZONE",
        resolved_mode="ZONE",
        scene_source_digest_sha256="c" * 64,
        selected_scene_count=0,
        assets=assets,
        selection_coverage=OrderedDict(
            source_scene_count=0,
            selected_scene_count=0,
            omitted_scene_count=0,
            covered_zones=[],
            required_zone_gap_count=0,
            climax_covered=True,
            ending_covered=True,
            max_count_applied=False,
        ),
        visual_plan_digest_sha256=None,
    )


def _bible() -> OrderedDict[str, object]:
    return OrderedDict(
        schema_version="2.0",
        story_sha256=HASH,
        active_profile="YOUTH_SAFE",
        age_profile="CHILD",
        art_direction_id="art:test",
        tonal_plan={},
        character_identity_locks=[],
        wardrobe_state_map={},
        recurring_location_locks=[],
        prop_color_anchors=[],
        approved_story_symbols=[],
        landscape_reference_map={},
        dependency_digest="d" * 64,
    )


def test_current_stage2_sidecars_serialize_deterministically() -> None:
    plan = serialize_visual_plan(_plan())
    bible = serialize_visual_bible(_bible())
    assert plan == serialize_visual_plan(_plan())
    assert bible == serialize_visual_bible(_bible())
    assert json.loads(plan)["visual_plan_digest_sha256"] != HASH
    assert json.loads(bible)["schema_version"] == "2.0"


def test_visual_plan_rejects_wrong_zone_order() -> None:
    value = _plan()
    assets = value["assets"]
    assert isinstance(assets, list)
    assets[0], assets[1] = assets[1], assets[0]
    with pytest.raises(Stage2Error, match="M7A118_ORDINAL|M7A123_ZONE_SET"):
        serialize_visual_plan(value)


def test_visual_plan_rejects_tampered_digest() -> None:
    data = serialize_visual_plan(_plan()).replace(b"Moment 1", b"Moment X")
    with pytest.raises(Stage2Error, match="M7A125_PLAN_DIGEST"):
        validate_visual_plan_bytes(data)


def test_visual_bible_rejects_legacy_schema() -> None:
    value = _bible()
    value["schema_version"] = "1.0"
    with pytest.raises(Exception, match="DS004_SCHEMA_VERSION"):
        serialize_visual_bible(value)
