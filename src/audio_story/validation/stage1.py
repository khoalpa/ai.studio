"""Executable deterministic contracts for M5 Stage 1 artifacts."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, cast

from audio_story.domain.stage1 import ProfileContract, Stage1Error
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.images import validate_png
from audio_story.validation.strict_json import OrderedObject, parse_json_bytes, validate_field_order

STORY_ROOT = ("schema_version", "meta", "characters", "outline", "script")
META_ROOT = (
    "title",
    "series",
    "episode",
    "author",
    "channel",
    "target",
    "length_min",
    "length_max",
    "language",
    "genre",
    "audience",
    "tone",
    "tags",
    "story_quality_commitment",
)
REFERENCE_ROOT = (
    "schema_version",
    "reference_image",
    "file_sha256",
    "pixel_sha256",
    "dimensions",
    "identity_lock",
    "validation_status",
)
REPORT_ROOT = (
    "schema_version",
    "prompt_version",
    "story_sha256",
    "story_content_digest_sha256",
    "character_reference_set_digest_sha256",
    "story_quality_commitment_digest_sha256",
    "active_profile",
    "summary",
    "scene_zone_map",
    "dialogue_audio",
    "quality",
    "engagement",
    "gates",
    "refinement",
    "evidence_graph",
)
MANIFEST_ROOT = (
    "schema_version",
    "package_stage",
    "package_purpose",
    "operation_mode",
    "created_by_prompt_version",
    "active_profile",
    "story_sha256",
    "parent_package_digest_sha256",
    "allowed_next_stage",
    "file_count",
    "files",
    "validation",
    "package_digest_sha256",
)
MANIFEST_FILE_ROOT = ("path", "sha256", "size_bytes", "owner_stage", "mutation_status")
ZONE_ORDER = (
    "GREETING",
    "OPENING",
    "INTRODUCTION",
    "DEVELOPMENT",
    "CLIMAX",
    "FALLING",
    "ENDING",
    "FAREWELL",
)
INTERNAL_TERMS = ("beat map", "repair hypothesis", "quality ledger", "system prompt")
ANCHOR_ROOT = (
    "schema_version",
    "series",
    "canon",
    "continuity",
    "episode_ledger",
    "canon_change_log",
)


def validate_serialized_dialogue(
    script: Sequence[Mapping[str, Any]], canonical_voices: Mapping[str, str]
) -> dict[str, Any]:
    """Validate dialogue using only voice, text and serialized item order."""
    ambiguities: list[str] = []
    switches = 0
    previous_owner: str | None = None
    previous_voice: str | None = None
    for index, item in enumerate(script):
        text = str(item.get("text", ""))
        voice = item.get("voice")
        direct = bool(re.search(r"[“\"]([^”\"]+)[”\"]", text)) and not text.casefold().startswith(
            ("người kể thuật lại", "the narrator reports")
        )
        if not direct:
            continue
        locator = f"$.script[{index}]"
        visible = text.casefold()
        named = [owner for owner in canonical_voices if owner.casefold() in visible]
        voice_candidates = [
            owner for owner, expected in canonical_voices.items() if expected == voice
        ]
        owner = (
            named[0]
            if len(named) == 1
            else voice_candidates[0]
            if len(voice_candidates) == 1
            else None
        )
        _require(
            voice != "NARRATOR" and bool(voice_candidates),
            "S134_DIALOGUE_VOICE",
            locator,
        )
        if owner is None:
            raise Stage1Error(
                "S135_DIALOGUE_AMBIGUITY",
                "serialized dialogue owner cannot be resolved from audible text",
                locator,
            )
        if previous_owner is not None and owner != previous_owner and voice == previous_voice:
            switches += 1
            disambiguated = owner.casefold() in visible or any(
                cue in visible for cue in ("gọi", "đáp", "trả lời", "quay sang", "said", "replied")
            )
            if not disambiguated:
                ambiguities.append(locator)
        previous_owner, previous_voice = owner, str(voice)
    if ambiguities:
        raise Stage1Error(
            "S135_DIALOGUE_AMBIGUITY",
            "serialized same-voice owner switch is ambiguous",
            ambiguities[0],
        )
    return {
        "serialized_audio_digest": sha256_bytes(
            canonical_json_bytes([[item.get("voice"), item.get("text")] for item in script])
        ),
        "same_voice_owner_switch_count": switches,
        "same_voice_owner_switch_ambiguity_count": 0,
    }


def validate_anchor_bytes(data: bytes, story: Mapping[str, Any]) -> OrderedObject:
    parsed = cast(
        OrderedObject, parse_json_bytes(data, "series_anchor.json", engine_generated=True).value
    )
    validate_field_order(parsed, ANCHOR_ROOT, "series_anchor.json")
    _require(parsed.get("schema_version") == "3.2.0", "S144_ANCHOR_SCHEMA", "$.schema_version")
    series = _object(parsed.get("series"), "S144_ANCHOR_SCHEMA", "$.series")
    continuity = _object(parsed.get("continuity"), "S144_ANCHOR_SCHEMA", "$.continuity")
    raw_meta = story.get("meta")
    _require(isinstance(raw_meta, Mapping), "S145_ANCHOR_BINDING", "$.meta")
    assert isinstance(raw_meta, Mapping)
    meta = raw_meta
    _require(series.get("title") == meta.get("series"), "S145_ANCHOR_BINDING", "$.series.title")
    _require(series.get("genre") == meta.get("genre"), "S145_ANCHOR_BINDING", "$.series.genre")
    _require(
        series.get("channel") == meta.get("channel"), "S145_ANCHOR_BINDING", "$.series.channel"
    )
    _require(
        str(continuity.get("latest_episode")) == str(meta.get("episode")),
        "S145_ANCHOR_BINDING",
        "$.continuity.latest_episode",
    )
    _require(
        isinstance(continuity.get("revision"), int)
        and isinstance(continuity.get("latest_episode"), int)
        and continuity["revision"] >= continuity["latest_episode"] >= 1,
        "S148_ANCHOR_CONTINUITY",
        "$.continuity",
    )
    arc = _object(
        continuity.get("active_case_arc"), "S148_ANCHOR_CONTINUITY", "$.continuity.active_case_arc"
    )
    _require(
        tuple(arc) == ("status", "part_index", "part_total", "local_progress")
        and arc.get("status") in {"active", "completed"}
        and isinstance(arc.get("part_index"), int)
        and isinstance(arc.get("part_total"), int)
        and 1 <= arc["part_index"] <= arc["part_total"],
        "S148_ANCHOR_CONTINUITY",
        "$.continuity.active_case_arc",
    )
    ids = {item.get("character_id") for item in story.get("characters", [])}
    recurring = _object(parsed.get("canon"), "S144_ANCHOR_SCHEMA", "$.canon").get(
        "recurring_characters"
    )
    _require(
        isinstance(recurring, list) and {item.get("character_id") for item in recurring} == ids,
        "S146_ANCHOR_CHARACTER",
        "$.canon.recurring_characters",
    )
    return parsed


def ordered_json_bytes(value: Mapping[str, Any]) -> bytes:
    normalized = _nfc(value)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def story_content_projection(story: Mapping[str, Any]) -> dict[str, Any]:
    characters = []
    for raw in story["characters"]:
        character = dict(raw)
        character.pop("reference_asset", None)
        characters.append(character)
    return {
        "schema_version": story["schema_version"],
        "meta": story["meta"],
        "characters": characters,
        "outline": story["outline"],
        "script": story["script"],
    }


def word_count(script: Sequence[Mapping[str, Any]]) -> int:
    return sum(len(re.findall(r"\w+", str(item["text"]), flags=re.UNICODE)) for item in script)


def final_script_digest(script: Sequence[Mapping[str, Any]]) -> str:
    return sha256_bytes(canonical_json_bytes([item["text"] for item in script]))


def validate_story_bytes(data: bytes, contract: ProfileContract) -> OrderedObject:
    parsed = cast(OrderedObject, parse_json_bytes(data, "story.json", engine_generated=True).value)
    validate_field_order(parsed, STORY_ROOT, "story.json")
    _require(parsed.get("schema_version") == "2.3", "S120_STORY_SCHEMA", "$.schema_version")
    meta = _object(parsed.get("meta"), "S120_STORY_SCHEMA", "$.meta")
    validate_field_order(meta, META_ROOT, "story.json", "$.meta")
    _require(meta.get("language") in {"vi", "en"}, "S120_STORY_SCHEMA", "$.meta.language")
    length_min = meta.get("length_min")
    length_max = meta.get("length_max")
    _require(
        isinstance(length_min, int) and isinstance(length_max, int) and length_min <= length_max,
        "S126_DURATION_WPM",
        "$.meta",
    )
    _require(meta.get("channel") == contract.channel, "S121_PROFILE_MISMATCH", "$.meta.channel")
    characters = parsed.get("characters")
    _require(isinstance(characters, list) and bool(characters), "S120_STORY_SCHEMA", "$.characters")
    assert isinstance(characters, list)
    seen: set[str] = set()
    for index, raw in enumerate(characters):
        character = _object(raw, "S120_STORY_SCHEMA", f"$.characters[{index}]")
        cid = character.get("character_id")
        _require(
            isinstance(cid, str) and cid not in seen,
            "S127_CHARACTER_BINDING",
            f"$.characters[{index}]",
        )
        assert isinstance(cid, str)
        seen.add(cid)
        reference = _object(
            character.get("reference_asset"),
            "S127_CHARACTER_BINDING",
            f"$.characters[{index}].reference_asset",
        )
        validate_field_order(
            reference, REFERENCE_ROOT, "story.json", f"$.characters[{index}].reference_asset"
        )
        _require(
            reference.get("reference_image") == f"characters/{cid}.png",
            "S127_CHARACTER_BINDING",
            f"$.characters[{index}].reference_asset.reference_image",
        )
    script = parsed.get("script")
    _require(
        isinstance(script, list) and len(script) >= contract.min_script_items,
        "S125_SCRIPT_COUNT",
        "$.script",
    )
    assert isinstance(script, list)
    ranks = []
    for index, raw in enumerate(script):
        item = _object(raw, "S120_STORY_SCHEMA", f"$.script[{index}]")
        zone = item.get("zone")
        _require(zone in ZONE_ORDER, "S124_ZONE_ORDER", f"$.script[{index}].zone")
        ranks.append(ZONE_ORDER.index(zone))
        text = item.get("text")
        _require(
            isinstance(text, str) and text.rstrip().endswith((".", "!", "?")),
            "S128_INCOMPLETE_SENTENCE",
            f"$.script[{index}].text",
        )
        assert isinstance(text, str)
        lowered = text.casefold()
        _require(
            not any(term in lowered for term in INTERNAL_TERMS),
            "S123_INTERNAL_FIELD_LEAK",
            f"$.script[{index}].text",
        )
    _require(
        ranks == sorted(ranks) and set(ZONE_ORDER) <= {raw["zone"] for raw in script},
        "S124_ZONE_ORDER",
        "$.script",
    )
    words = word_count(script)
    duration = words / contract.target_wpm
    _require(
        contract.min_minutes <= duration <= contract.max_minutes, "S126_DURATION_WPM", "$.script"
    )
    commitment = _object(
        meta.get("story_quality_commitment"), "S120_STORY_SCHEMA", "$.meta.story_quality_commitment"
    )
    _require(
        commitment.get("final_script_text_digest_sha256") == final_script_digest(script),
        "S129_PARSEBACK_DIGEST",
        "$.meta.story_quality_commitment.final_script_text_digest_sha256",
    )
    validate_serialized_dialogue(script, {})
    return parsed


def validate_report_bytes(
    data: bytes, story_bytes: bytes, story: Mapping[str, Any]
) -> OrderedObject:
    parsed = cast(
        OrderedObject,
        parse_json_bytes(data, "story_validation.json", engine_generated=True).value,
    )
    validate_field_order(parsed, REPORT_ROOT, "story_validation.json")
    _require(parsed.get("schema_version") == "2.3", "S130_REPORT_ROOT", "$.schema_version")
    _require(
        parsed.get("story_sha256") == sha256_bytes(story_bytes),
        "S131_REPORT_BINDING",
        "$.story_sha256",
    )
    content = sha256_bytes(canonical_json_bytes(story_content_projection(story)))
    _require(
        parsed.get("story_content_digest_sha256") == content,
        "S131_REPORT_BINDING",
        "$.story_content_digest_sha256",
    )
    gates = parsed.get("gates")
    _require(isinstance(gates, list) and bool(gates), "S132_REPORT_EVIDENCE", "$.gates")
    assert isinstance(gates, list)
    _require(all(g.get("status") == "PASS" for g in gates), "S133_REPORT_NOT_VERIFIED", "$.gates")
    return parsed


def validate_character_assets(
    story: Mapping[str, Any], assets: Mapping[str, bytes], *, test_mode: bool
) -> str:
    expected: list[str] = []
    tuples: list[list[str]] = []
    for index, character in enumerate(story["characters"]):
        reference = character["reference_asset"]
        path = reference["reference_image"]
        expected.append(path)
        _require(path in assets, "S127_CHARACTER_BINDING", f"$.characters[{index}]")
        info = validate_png(
            assets[path],
            path,
            expected_dimensions=(1536, 2048),
            required_metadata_key="audio_story",
        )
        _require(info.sha256 == reference["file_sha256"], "S127_CHARACTER_BINDING", path)
        provenance = info.metadata["audio_story"]
        _require(isinstance(provenance, dict), "S127_CHARACTER_BINDING", path)
        assert isinstance(provenance, dict)
        _require(
            provenance.get("character_id") == character["character_id"],
            "S127_CHARACTER_BINDING",
            path,
        )
        if provenance.get("provenance") == "TEST_ONLY_M5_MOCK" and not test_mode:
            raise Stage1Error(
                "S143_TEST_ASSET_PRODUCTION_PATH",
                "test-only character reference cannot enter production",
                path,
            )
        tuples.append([character["character_id"], path, info.sha256])
    _require(expected == list(assets), "S127_CHARACTER_BINDING", "$.characters")
    return sha256_bytes(canonical_json_bytes(tuples))


def validate_manifest_bytes(
    data: bytes, members: Mapping[str, bytes], profile: str
) -> OrderedObject:
    parsed = cast(
        OrderedObject,
        parse_json_bytes(data, "workflow_manifest.json", engine_generated=True).value,
    )
    validate_field_order(parsed, MANIFEST_ROOT, "workflow_manifest.json")
    _require(parsed.get("package_stage") == "STAGE1", "S140_MANIFEST_SCHEMA", "$.package_stage")
    _require(
        parsed.get("package_purpose") == "WORKFLOW_CHECKPOINT",
        "S140_MANIFEST_SCHEMA",
        "$.package_purpose",
    )
    _require(
        parsed.get("parent_package_digest_sha256") is None,
        "S140_MANIFEST_SCHEMA",
        "$.parent_package_digest_sha256",
    )
    _require(parsed.get("active_profile") == profile, "S140_MANIFEST_SCHEMA", "$.active_profile")
    has_anchor = "series_anchor.json" in members
    _require(
        has_anchor == (profile == "SERIAL_DETECTIVE"),
        "S147_ANCHOR_APPLICABILITY",
        "$.files",
    )
    if has_anchor:
        _require(list(members)[-1] == "series_anchor.json", "S147_ANCHOR_APPLICABILITY", "$.files")
    files = parsed.get("files")
    _require(isinstance(files, list), "S140_MANIFEST_SCHEMA", "$.files")
    assert isinstance(files, list)
    _require(parsed.get("file_count") == len(files) + 1, "S141_MANIFEST_FILE_SET", "$.file_count")
    declared = []
    for index, item in enumerate(files):
        validate_field_order(
            item, MANIFEST_FILE_ROOT, "workflow_manifest.json", f"$.files[{index}]"
        )
        path = item["path"]
        _require(
            path != "workflow_manifest.json" and path in members,
            "S141_MANIFEST_FILE_SET",
            f"$.files[{index}].path",
        )
        _require(
            item["sha256"] == sha256_bytes(members[path])
            and item["size_bytes"] == len(members[path]),
            "S142_MANIFEST_DIGEST",
            f"$.files[{index}]",
        )
        declared.append(path)
    _require(declared == list(members), "S141_MANIFEST_FILE_SET", "$.files")
    return parsed


def _object(value: Any, code: str, locator: str) -> OrderedObject:
    _require(isinstance(value, OrderedObject), code, locator)
    return cast(OrderedObject, value)


def _require(condition: bool, code: str, locator: str) -> None:
    if not condition:
        raise Stage1Error(code, "Stage 1 contract violation", locator)


def _nfc(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {unicodedata.normalize("NFC", str(k)): _nfc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_nfc(item) for item in value]
    return value
