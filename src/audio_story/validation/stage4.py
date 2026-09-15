"""M9 Stage 4 source-package and canonical video-prompt validation."""

from __future__ import annotations

import json
import re
import zipfile
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn, cast

from audio_story.domain.stage1 import resolve_profile
from audio_story.domain.stage3 import InheritedByteAuthority
from audio_story.domain.stage4 import Stage4Error, Stage4PackageInput
from audio_story.validation.archives import inspect_zip
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.images import validate_png
from audio_story.validation.stage1 import (
    MANIFEST_FILE_ROOT,
    MANIFEST_ROOT,
    validate_anchor_bytes,
    validate_character_assets,
    validate_report_bytes,
    validate_story_bytes,
)
from audio_story.validation.stage2 import validate_visual_bible_bytes, validate_visual_plan_bytes
from audio_story.validation.stage3 import validate_package_quality_report_bytes
from audio_story.validation.strict_json import OrderedObject, parse_json_bytes, validate_field_order

VIDEO_ROOT_NATIVE = (
    "schema_version",
    "generator_target",
    "source_binding",
    "project",
    "voice_strategy",
    "global_continuity_lock",
    "clips",
    "validation",
)
VIDEO_ROOT_NO_VOICE = (
    "schema_version",
    "generator_target",
    "source_binding",
    "project",
    "global_continuity_lock",
    "clips",
    "validation",
)
CLIP_ROOT_NATIVE = (
    "clip_id",
    "sequence_index",
    "zone",
    "derived_scene_id",
    "continuity_take_id",
    "utterance_segmentation",
    "source_script",
    "generation_variants",
    "duration_seconds",
    "usable_span_seconds",
    "aspect_ratio",
    "reference_inputs",
    "continuity_in",
    "primary_action",
    "visual_delta",
    "terminal_handoff",
    "prompt",
    "voice_plan",
    "audio_prompt",
    "avoid",
    "continuity_out",
    "state_change_records",
    "transition_type",
)
CLIP_ROOT_NO_VOICE = tuple(key for key in CLIP_ROOT_NATIVE if key != "voice_plan")
VALIDATION_ROOT = (
    "schema_status",
    "source_binding_status",
    "timeline_derivation_status",
    "scene_derivation_status",
    "reference_router_status",
    "character_only_reference_status",
    "coverage_status",
    "continuity_status",
    "identity_reference_status",
    "voice_selection_status",
    "long_utterance_status",
    "prompt_budget_status",
    "prompt_atomicity_status",
    "no_invented_event_status",
    "anti_repeat_status",
    "safety_status",
    "fixture_status",
    "output_digest_sha256",
    "status",
)
_HEX = re.compile(r"^[0-9a-f]{64}$")


def load_stage3_package(
    path: Path, *, expected_archive_sha256: str | None = None
) -> Stage4PackageInput:
    source = path.resolve(strict=True)
    archive_bytes = source.read_bytes()
    archive_sha = sha256_bytes(archive_bytes)
    if expected_archive_sha256 and archive_sha != expected_archive_sha256.lower():
        _fail("M9A001_ARCHIVE_AUTHORITY", "archive SHA-256 mismatch", str(source))
    names = [entry.path for entry in inspect_zip(source)]
    if not names or names[0] != "workflow_manifest.json":
        _fail("M9A002_MEMBER_ORDER", "manifest must be the first member", str(source))
    with zipfile.ZipFile(source) as archive:
        all_members = OrderedDict((name, archive.read(name)) for name in names)
    manifest_bytes = all_members.pop("workflow_manifest.json")
    manifest = _object(manifest_bytes, "workflow_manifest.json")
    validate_field_order(manifest, MANIFEST_ROOT, "workflow_manifest.json")
    if manifest.get("package_stage") != "STAGE3" or manifest.get("allowed_next_stage") != "STAGE4":
        _fail(
            "M9A010_STAGE",
            "CREATE requires an authoritative Stage 3 package",
            "workflow_manifest.json",
        )
    files = manifest.get("files")
    if not isinstance(files, list) or manifest.get("file_count") != len(files) + 1:
        _fail("M9A011_FILE_SET", "manifest file cardinality is invalid", "workflow_manifest.json")
    declared: list[str] = []
    projection: list[dict[str, object]] = []
    for index, raw in enumerate(files):
        validate_field_order(raw, MANIFEST_FILE_ROOT, "workflow_manifest.json", f"$.files[{index}]")
        item = cast(Mapping[str, Any], raw)
        member_path = item.get("path")
        if not isinstance(member_path, str) or member_path not in all_members:
            _fail("M9A011_FILE_SET", "declared member is missing", f"$.files[{index}].path")
        data = all_members[member_path]
        if item.get("sha256") != sha256_bytes(data) or item.get("size_bytes") != len(data):
            _fail("M9A012_MEMBER_DIGEST", "member digest or size mismatch", member_path)
        if item.get("mutation_status") not in {"READ_ONLY", "CREATED_CURRENT_STAGE"}:
            _fail("M9A013_MUTATION", "invalid mutation status", member_path)
        declared.append(member_path)
        projection.append(
            {key: item[key] for key in ("path", "sha256", "size_bytes", "owner_stage")}
        )
    if declared != list(all_members) or len(set(declared)) != len(declared):
        _fail("M9A011_FILE_SET", "archive and manifest order differ", str(source))
    package_digest = sha256_bytes(canonical_json_bytes(projection))
    if manifest.get("package_digest_sha256") != package_digest:
        _fail("M9A014_PACKAGE_DIGEST", "package digest mismatch", "workflow_manifest.json")
    required = {
        "story.json",
        "story_validation.json",
        "visual_plan.json",
        "visual_bible.json",
        "package_quality_report.json",
    }
    if not required.issubset(all_members):
        _fail("M9A011_FILE_SET", "required Stage 3 member missing", str(source))
    story = _object(all_members["story.json"], "story.json")
    report = _object(all_members["story_validation.json"], "story_validation.json")
    quality = _object(all_members["package_quality_report.json"], "package_quality_report.json")
    validate_package_quality_report_bytes(all_members["package_quality_report.json"])
    if quality.get("summary", {}).get("publish_verdict") != "PASS":
        _fail(
            "M9A020_QUALITY",
            "Stage 3 package quality verdict is not PASS",
            "package_quality_report.json",
        )
    story_sha = sha256_bytes(all_members["story.json"])
    if manifest.get("story_sha256") != story_sha or report.get("story_sha256") != story_sha:
        _fail("M9A021_STORY_BINDING", "story binding mismatch", "story.json")
    if quality.get("package_identity", {}).get("story_sha256") != story_sha:
        _fail(
            "M9A021_STORY_BINDING",
            "quality report story binding mismatch",
            "package_quality_report.json",
        )
    language = story.get("meta", {}).get("language")
    if not isinstance(language, str):
        _fail("M9A022_STORY", "story language is missing", "$.meta.language")
    contract = resolve_profile(cast(str, manifest["active_profile"]), language)
    validated_story = validate_story_bytes(all_members["story.json"], contract)
    validate_report_bytes(
        all_members["story_validation.json"], all_members["story.json"], validated_story
    )
    character_paths = tuple(
        cast(str, item["reference_asset"]["reference_image"])
        for item in cast(list[Mapping[str, Any]], validated_story["characters"])
    )
    validate_character_assets(
        validated_story,
        OrderedDict((name, all_members[name]) for name in character_paths),
        test_mode=False,
    )
    plan = validate_visual_plan_bytes(all_members["visual_plan.json"])
    bible = validate_visual_bible_bytes(all_members["visual_bible.json"])
    if plan.get("story_sha256") != story_sha or bible.get("story_sha256") != story_sha:
        _fail("M9A023_VISUAL_BINDING", "visual sidecar story binding mismatch", "visual_plan.json")
    landscapes = tuple(path for path in all_members if path.startswith("landscape/"))
    portraits = tuple(path for path in all_members if path.startswith("portrait/"))
    if len(landscapes) != 10 or len(portraits) != 10:
        _fail("M9A024_IMAGE_SET", "ten landscapes and ten portraits are required", "story.zip")
    for member_name in landscapes:
        validate_png(
            all_members[member_name],
            member_name,
            expected_dimensions=(3840, 2160),
            required_metadata_key="audio_story",
        )
    for member_name in portraits:
        validate_png(
            all_members[member_name],
            member_name,
            expected_dimensions=(1080, 1920),
            required_metadata_key="audio_story",
        )
    identity = cast(Mapping[str, Any], quality["package_identity"])
    if identity.get("character_set_digest_sha256") != _set_digest(character_paths, all_members):
        _fail("M9A025_SET_DIGEST", "character set digest mismatch", "package_quality_report.json")
    if identity.get("landscape_set_digest_sha256") != _set_digest(landscapes, all_members):
        _fail("M9A025_SET_DIGEST", "landscape set digest mismatch", "package_quality_report.json")
    if identity.get("portrait_set_digest_sha256") != _set_digest(portraits, all_members):
        _fail("M9A025_SET_DIGEST", "portrait set digest mismatch", "package_quality_report.json")
    if "series_anchor.json" in all_members:
        validate_anchor_bytes(all_members["series_anchor.json"], validated_story)
    return Stage4PackageInput(
        source,
        archive_sha,
        package_digest,
        manifest_bytes,
        all_members,
        manifest,
        story,
        report,
        quality,
    )


def assert_stage3_members_unchanged(
    source: Stage4PackageInput, members: Mapping[str, bytes]
) -> None:
    if tuple(members) != tuple(source.members):
        _fail("M9A030_INHERITED_SET", "inherited member set/order changed", "story.zip")
    for path, data in source.members.items():
        if members[path] != data:
            _fail("M9A031_INHERITED_MUTATION", "Stage 3 member bytes changed", path)


def inherited_authority(source: Stage4PackageInput) -> tuple[InheritedByteAuthority, ...]:
    by_path = {
        cast(str, item["path"]): item
        for item in cast(list[Mapping[str, Any]], source.manifest["files"])
    }
    return tuple(
        InheritedByteAuthority(
            path, cast(str, by_path[path]["owner_stage"]), sha256_bytes(data), len(data)
        )
        for path, data in source.members.items()
    )


def serialize_video_prompts(value: Mapping[str, Any]) -> bytes:
    from audio_story.validation.stage1 import ordered_json_bytes

    data = ordered_json_bytes(value)
    validate_video_prompts_bytes(data)
    return data


def validate_video_prompts_bytes(data: bytes) -> Mapping[str, Any]:
    root = parse_json_bytes(data, "video_prompts.json", engine_generated=True).value
    if not isinstance(root, OrderedObject):
        _fail("M9D001_ROOT", "root must be an ordered object", "video_prompts.json")
    audio_mode = root.get("generator_target", {}).get("capability_profile", {}).get("audio_mode")
    native = audio_mode == "NATIVE_DIALOGUE"
    validate_field_order(
        root, VIDEO_ROOT_NATIVE if native else VIDEO_ROOT_NO_VOICE, "video_prompts.json"
    )
    if root.get("schema_version") != "1.2":
        _fail("M9D002_SCHEMA", "schema_version must be 1.2", "$.schema_version")
    clips = root.get("clips")
    if not isinstance(clips, list) or not clips:
        _fail("M9D003_CLIPS", "clips must be nonempty", "$.clips")
    for index, clip in enumerate(clips):
        validate_field_order(
            clip,
            CLIP_ROOT_NATIVE if native else CLIP_ROOT_NO_VOICE,
            "video_prompts.json",
            f"$.clips[{index}]",
        )
        if (
            clip.get("sequence_index") != index + 1
            or clip.get("clip_id") != f"clip_{index + 1:04d}"
        ):
            _fail("M9D004_SEQUENCE", "clip sequence is not contiguous", f"$.clips[{index}]")
        refs = clip.get("reference_inputs", {}).get("character_images", [])
        if any(not isinstance(ref, str) or not ref.startswith("characters/") for ref in refs):
            _fail(
                "M9D005_REFERENCE",
                "only character references are allowed",
                f"$.clips[{index}].reference_inputs",
            )
        prompt = clip.get("prompt")
        audio_prompt = clip.get("audio_prompt")
        avoid = clip.get("avoid")
        if not isinstance(prompt, str) or not 1 <= len(prompt.split()) <= 240:
            _fail(
                "M9D008_PROMPT_BUDGET",
                "prompt word budget failed",
                f"$.clips[{index}].prompt",
            )
        audio_limit = 240 if native else 60
        if not isinstance(audio_prompt, str) or not 1 <= len(audio_prompt.split()) <= audio_limit:
            _fail(
                "M9D008_PROMPT_BUDGET",
                "audio prompt word budget failed",
                f"$.clips[{index}].audio_prompt",
            )
        if (
            not isinstance(avoid, list)
            or not 1 <= len(avoid) <= 12
            or len({str(value).strip().casefold() for value in avoid}) != len(avoid)
        ):
            _fail(
                "M9D009_AVOID",
                "avoid list cardinality or uniqueness failed",
                f"$.clips[{index}].avoid",
            )
    prompts = [cast(str, clip["prompt"]).strip().casefold() for clip in clips]
    if len(set(prompts)) != len(prompts):
        _fail("M9D010_ANTI_REPEAT", "exact duplicate prompts are forbidden", "$.clips")
    validate_field_order(root["validation"], VALIDATION_ROOT, "video_prompts.json", "$.validation")
    digest = root["validation"].get("output_digest_sha256")
    if not isinstance(digest, str) or not _HEX.fullmatch(digest):
        _fail(
            "M9D006_OUTPUT_DIGEST", "output digest is invalid", "$.validation.output_digest_sha256"
        )
    projection = json.loads(data)
    projection["validation"]["output_digest_sha256"] = None
    if sha256_bytes(canonical_json_bytes(projection)) != digest:
        _fail("M9D006_OUTPUT_DIGEST", "output digest mismatch", "$.validation.output_digest_sha256")
    if any(
        value != "PASS"
        for key, value in root["validation"].items()
        if key not in {"output_digest_sha256"}
    ):
        _fail("M9D007_GATE", "all Stage 4 gates must PASS", "$.validation")
    return root


def validate_video_prompts_for_source(data: bytes, source: Stage4PackageInput) -> Mapping[str, Any]:
    """Recompute source hashes, offsets, reference bindings and continuous state."""
    root = validate_video_prompts_bytes(data)
    binding = cast(Mapping[str, Any], root["source_binding"])
    expected = {
        "story_sha256": sha256_bytes(source.members["story.json"]),
        "story_validation_sha256": sha256_bytes(source.members["story_validation.json"]),
        "package_quality_report_sha256": sha256_bytes(
            source.members["package_quality_report.json"]
        ),
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            _fail("M9D020_SOURCE_BINDING", "source hash mismatch", f"$.source_binding.{key}")
    allowed = {
        cast(str, item["reference_asset"]["reference_image"])
        for item in cast(list[Mapping[str, Any]], source.story["characters"])
    }
    script = cast(list[Mapping[str, Any]], source.story["script"])
    clips = cast(list[Mapping[str, Any]], root["clips"])
    previous_end = -1.0
    for index, clip in enumerate(clips):
        span = cast(Mapping[str, Any], clip["source_script"])
        item_index = span.get("start_item_index")
        start = span.get("start_word_offset")
        end = span.get("end_word_offset")
        if (
            not isinstance(item_index, int)
            or not 0 <= item_index < len(script)
            or not isinstance(start, int)
            or not isinstance(end, int)
        ):
            _fail(
                "M9D021_SOURCE_SPAN",
                "source locator is invalid",
                f"$.clips[{index}].source_script",
            )
        tokens = re.findall(r"\S+", cast(str, script[item_index]["text"]))
        if not 0 <= start < end <= len(tokens):
            _fail(
                "M9D021_SOURCE_SPAN",
                "source word offsets are invalid",
                f"$.clips[{index}].source_script",
            )
        text = " ".join(tokens[start:end])
        digest = sha256_bytes(f"{item_index}\x1f{start}\x1f{end}\x1f{text}\x1fFalse".encode())
        if span.get("source_text_digest_sha256") != digest:
            _fail(
                "M9D022_SOURCE_DIGEST",
                "source span digest mismatch",
                f"$.clips[{index}].source_script",
            )
        start_time, end_time = span.get("start_time_seconds"), span.get("end_time_seconds")
        if (
            not isinstance(start_time, (int, float))
            or not isinstance(end_time, (int, float))
            or start_time < previous_end
            or end_time <= start_time
        ):
            _fail(
                "M9D023_TIMELINE",
                "timeline is non-monotonic",
                f"$.clips[{index}].source_script",
            )
        previous_end = float(end_time)
        refs = cast(
            list[str], cast(Mapping[str, Any], clip["reference_inputs"])["character_images"]
        )
        if not set(refs).issubset(allowed):
            _fail(
                "M9D024_REFERENCE_BINDING",
                "unbound character reference",
                f"$.clips[{index}].reference_inputs",
            )
        if index and clip["transition_type"] == "CONTINUOUS":
            previous = clips[index - 1]
            prior_out = dict(cast(Mapping[str, Any], previous["continuity_out"]))
            prior_out.pop("handoff_action", None)
            if prior_out != dict(cast(Mapping[str, Any], clip["continuity_in"])):
                _fail(
                    "M9D025_CONTINUITY",
                    "continuous clip state mismatch",
                    f"$.clips[{index}].continuity_in",
                )
    return root


def _object(data: bytes, path: str) -> OrderedObject:
    value = parse_json_bytes(data, path).value
    if not isinstance(value, OrderedObject):
        _fail("M9A040_JSON", "ordered JSON object required", path)
    return value


def _set_digest(paths: tuple[str, ...], members: Mapping[str, bytes]) -> str:
    return sha256_bytes(
        canonical_json_bytes([[path, sha256_bytes(members[path])] for path in paths])
    )


def _fail(code: str, message: str, locator: str) -> NoReturn:
    raise Stage4Error(code, message, locator)
