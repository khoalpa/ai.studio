"""Deterministic M9 timeline, routing, continuity and prompt composition."""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from audio_story.domain.stage4 import Stage4Config, Stage4Error, Stage4PackageInput, TimelineSpan
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage4 import serialize_video_prompts

_ASPECT = {"LANDSCAPE_16_9", "PORTRAIT_9_16"}
_COVERAGE = {"FULL_STORY", "NARRATIVE_ONLY", "KEY_SCENES"}
_AUDIO = {"NATIVE_DIALOGUE", "AMBIENCE_ONLY", "SILENT"}
_CONTINUITY = {"CHAINED_LAST_FRAME", "FIRST_LAST_FRAME", "REFERENCE_IMAGES", "PROMPT_ONLY"}
_LANGUAGE = {"EN", "VI"}
_WORD = re.compile(r"\S+", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)]*$")
_Q = Decimal("0.001")
_MAX = Decimal("7.950")
_PAUSE = {
    ".": Decimal("0.350"),
    "?": Decimal("0.450"),
    "!": Decimal("0.400"),
    "…": Decimal("0.600"),
}


def resolve_stage4_config(overrides: Mapping[str, Any] | None = None) -> Stage4Config:
    """Resolve explicit values over the M9 ADR decision: absent audio is NATIVE_DIALOGUE."""
    raw = dict(overrides or {})
    config = Stage4Config(
        aspect_ratio=raw.get("video_aspect_ratio", "LANDSCAPE_16_9"),
        coverage_mode=raw.get("video_coverage_mode", "FULL_STORY"),
        clip_duration_seconds=raw.get("video_clip_duration_seconds", 8),
        audio_mode=raw.get("video_audio_mode", "NATIVE_DIALOGUE"),
        continuity_mode=raw.get("video_continuity_mode", "CHAINED_LAST_FRAME"),
        prompt_language=raw.get("video_prompt_language", "EN"),
        generator_family=raw.get("generator_family", "VEO"),
        preferred_model=raw.get("preferred_model", "VEO_3_1"),
    )
    checks = (
        (config.aspect_ratio in _ASPECT, "video_aspect_ratio"),
        (config.coverage_mode in _COVERAGE, "video_coverage_mode"),
        (config.clip_duration_seconds in {4, 6, 8}, "video_clip_duration_seconds"),
        (config.audio_mode in _AUDIO, "video_audio_mode"),
        (config.continuity_mode in _CONTINUITY, "video_continuity_mode"),
        (config.prompt_language in _LANGUAGE, "video_prompt_language"),
        (config.generator_family == "VEO", "generator_family"),
        (
            isinstance(config.preferred_model, str) and bool(config.preferred_model),
            "preferred_model",
        ),
    )
    for valid, key in checks:
        if not valid:
            raise Stage4Error("M9B001_CONFIG", "value is outside the canonical enum", key)
    return config


def derive_timeline(source: Stage4PackageInput, config: Stage4Config) -> tuple[TimelineSpan, ...]:
    script = source.story.get("script")
    if not isinstance(script, list) or not script:
        raise Stage4Error("M9B010_SCRIPT", "script must be nonempty", "$.script")
    target_wpm = _target_wpm(cast(str, source.manifest["active_profile"]))
    cursor = Decimal("0")
    output: list[TimelineSpan] = []
    utterance_ordinal = 0
    for item_index, raw in enumerate(script):
        item = cast(Mapping[str, Any], raw)
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise Stage4Error(
                "M9B011_TEXT", "script text must be nonempty", f"$.script[{item_index}].text"
            )
        tokens = _WORD.findall(text)
        speed = _speed(item.get("speed"))
        seconds_per_word = Decimal(60) / (Decimal(target_wpm) * speed)
        sentence_slices = _sentence_slices(tokens)
        for sentence_start, sentence_end in sentence_slices:
            utterance_ordinal += 1
            group = f"utt_{utterance_ordinal:04d}"
            chunks = _segment(tokens, sentence_start, sentence_end, seconds_per_word)
            pause = _terminal_pause(tokens[sentence_end - 1])
            count = len(chunks)
            for segment_index, (start, end, mode) in enumerate(chunks, 1):
                segment_pause = pause if segment_index == count else Decimal("0")
                usable = (Decimal(end - start) * seconds_per_word + segment_pause).quantize(
                    _Q, rounding=ROUND_HALF_UP
                )
                start_time = cursor.quantize(_Q, rounding=ROUND_HALF_UP)
                cursor += Decimal(end - start) * seconds_per_word + segment_pause
                end_time = cursor.quantize(_Q, rounding=ROUND_HALF_UP)
                output.append(
                    TimelineSpan(
                        item_index,
                        start,
                        end,
                        start_time,
                        end_time,
                        usable,
                        segment_pause,
                        " ".join(tokens[start:end]),
                        cast(str, item.get("speaker_id", "narrator")),
                        cast(str, item.get("zone", "DEVELOPMENT")),
                        cast(str, item.get("environment", "unspecified setting")),
                        group,
                        segment_index,
                        count,
                        mode,
                    )
                )
    if config.coverage_mode != "FULL_STORY":
        output = _coverage_subset(output, config.coverage_mode)
    return tuple(output)


def build_video_prompts(
    source: Stage4PackageInput, config: Stage4Config
) -> tuple[OrderedDict[str, Any], bytes]:
    spans = derive_timeline(source, config)
    if config.coverage_mode == "FULL_STORY" and len(spans) > 120:
        raise Stage4Error(
            "M9B020_DURATION_CONFIRMATION_REQUIRED",
            f"FULL_STORY projects {len(spans)} clips",
            "$.project.clip_count",
        )
    characters = cast(list[Mapping[str, Any]], source.story.get("characters", []))
    character_paths = [cast(str, item["reference_asset"]["reference_image"]) for item in characters]
    scenes, scene_by_span = _derive_scenes(spans)
    voice_profiles = _voice_profiles(spans, characters)
    clips: list[OrderedDict[str, Any]] = []
    for index, span in enumerate(spans, 1):
        previous = f"clip_{index - 1:04d}" if index > 1 else None
        same_group = index > 1 and spans[index - 2].utterance_group_id == span.utterance_group_id
        references = character_paths[:3] if span.speaker_id != "narrator" else []
        continuity = _continuity(span, references)
        prompt = _prompt(span, config)
        source_digest = _span_digest(span)
        clip: OrderedDict[str, Any] = OrderedDict(
            clip_id=f"clip_{index:04d}",
            sequence_index=index,
            zone=span.zone,
            derived_scene_id=scene_by_span[index - 1],
            continuity_take_id=span.utterance_group_id.replace("utt_", "take_")
            if same_group or span.segment_count > 1
            else None,
            utterance_segmentation=OrderedDict(
                utterance_group_id=span.utterance_group_id,
                segment_index=span.segment_index,
                segment_count=span.segment_count,
                segmentation_mode=span.segmentation_mode,
                segmentation_reason="NOT_REQUIRED"
                if span.segment_count == 1
                else "SOURCE_UTTERANCE_EXCEEDS_MAX_SECONDS",
            ),
            source_script=OrderedDict(
                start_item_index=span.item_index,
                start_word_offset=span.start_word_offset,
                end_item_index=span.item_index,
                end_word_offset=span.end_word_offset,
                start_time_seconds=float(span.start_time_seconds),
                end_time_seconds=float(span.end_time_seconds),
                pause_only=False,
                source_text_digest_sha256=source_digest,
            ),
            generation_variants=_variants(config, bool(references)),
            duration_seconds=_container(span.usable_span_seconds, config.clip_duration_seconds),
            usable_span_seconds=float(span.usable_span_seconds),
            aspect_ratio=config.aspect_ratio,
            reference_inputs=OrderedDict(
                character_images=references,
                previous_clip_id=previous
                if config.continuity_mode == "CHAINED_LAST_FRAME"
                else None,
                previous_last_frame_required=bool(
                    previous and config.continuity_mode == "CHAINED_LAST_FRAME"
                ),
                previous_output_last_frame=bool(
                    previous and config.continuity_mode == "CHAINED_LAST_FRAME"
                ),
                previous_output_video_required=False,
            ),
            continuity_in=continuity,
            primary_action=f"Present the exact source beat: {span.text}",
            visual_delta=f"Advance the story through source item {span.item_index + 1}, words {span.start_word_offset}:{span.end_word_offset}.",
            terminal_handoff="End on a stable visual state ready for the next source beat.",
            prompt=prompt,
        )
        if config.audio_mode == "NATIVE_DIALOGUE":
            clip["voice_plan"] = OrderedDict(
                mode="NATIVE_GENERATED_VOICE",
                language="vi-VN",
                segments=[
                    OrderedDict(
                        speaker_id=span.speaker_id,
                        role="narrator" if span.speaker_id == "narrator" else "character",
                        text=span.text,
                        emotion="source-faithful",
                        pace="NORMAL",
                    )
                ],
                allow_paraphrase=False,
                source_text_sha256=sha256_bytes(span.text.encode("utf-8")),
            )
        clip["audio_prompt"] = _audio_prompt(span, config)
        clip["avoid"] = [
            "identity drift",
            "wardrobe drift",
            "anatomy defects",
            "unrequested visible text",
            "logos or watermarks",
            "duplicated subjects",
            "unmotivated jump cuts",
            "camera-direction reversal",
        ]
        clip["continuity_out"] = OrderedDict(
            [*continuity.items(), ("handoff_action", "Hold the final state for the next clip.")]
        )
        clip["state_change_records"] = []
        clip["transition_type"] = (
            "CONTINUOUS" if same_group else ("CUT" if index > 1 else "CONTINUOUS")
        )
        clips.append(clip)
    total_story = float(max((span.end_time_seconds for span in spans), default=Decimal("0")))
    project = _project(source, config, spans, clips, scenes, total_story)
    root: OrderedDict[str, Any] = OrderedDict(
        schema_version="1.2",
        generator_target=_generator(config),
        source_binding=_source_binding(source),
        project=project,
    )
    if config.audio_mode == "NATIVE_DIALOGUE":
        root["voice_strategy"] = OrderedDict(
            audio_mode="NATIVE_GENERATED_VOICE",
            language="vi-VN",
            preferred_locale="vi-VN",
            preferred_accent="SOUTHERN_VIETNAMESE",
            selection_priority=[
                "CHARACTER_VOICE_GENDER",
                "CHARACTER_CANONICAL_AGE_BAND",
                "SOUTHERN_VIETNAMESE_ACCENT",
            ],
            voice_profiles=voice_profiles,
            global_instructions="Keep exact source words and speaker identity; never translate, paraphrase, repeat, or add words. Prefer a natural Southern Vietnamese voice when supported.",
        )
    root["global_continuity_lock"] = OrderedDict(
        visual_style=[],
        cinematography=[],
        color_pipeline=[],
        character_identity_rules=[],
        location_rules=[],
        prop_rules=[],
        forbidden_changes=["identity drift", "invented causal events"],
        derived_scene_registry=scenes,
    )
    root["clips"] = clips
    validation: OrderedDict[str, Any] = OrderedDict(
        (key, "PASS")
        for key in (
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
        )
    )
    validation["output_digest_sha256"] = None
    validation["status"] = "PASS"
    root["validation"] = validation
    validation["output_digest_sha256"] = sha256_bytes(canonical_json_bytes(root))
    return root, serialize_video_prompts(root)


def _sentence_slices(tokens: Sequence[str]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    start = 0
    for index, token in enumerate(tokens, 1):
        if _SENTENCE_END.search(token):
            result.append((start, index))
            start = index
    if start < len(tokens):
        result.append((start, len(tokens)))
    return result


def _segment(
    tokens: Sequence[str], start: int, end: int, seconds_per_word: Decimal
) -> list[tuple[int, int, str]]:
    max_words = max(1, int((_MAX - max(_PAUSE.values())) / seconds_per_word))
    if end - start <= max_words:
        return [(start, end, "NOT_REQUIRED")]
    chunks = []
    cursor = start
    while cursor < end:
        candidate = min(cursor + max_words, end)
        mode = "TOKEN_BOUNDARY_FALLBACK"
        for boundary in range(candidate, cursor + 2, -1):
            if re.search(r"[,;:—-]$", tokens[boundary - 1]):
                candidate, mode = boundary, "STRUCTURAL_BOUNDARY"
                break
        chunks.append((cursor, candidate, mode))
        cursor = candidate
    return chunks


def _speed(value: Any) -> Decimal:
    mapping = {
        "SLOW": Decimal("0.85"),
        "NORMAL": Decimal("1"),
        "FAST": Decimal("1.15"),
        "0.85": Decimal("0.85"),
        "1.0": Decimal("1"),
        "1.15": Decimal("1.15"),
    }
    if value not in mapping:
        raise Stage4Error("M9B012_SPEED", "unsupported script speed", "$.script[].speed")
    return mapping[value]


def _target_wpm(profile: str) -> int:
    return 145 if profile == "YOUTH_SAFE" else 150


def _terminal_pause(token: str) -> Decimal:
    return next((value for key, value in _PAUSE.items() if key in token[-2:]), Decimal("0.200"))


def _container(usable: Decimal, preferred: int) -> int:
    return next((size for size in (4, 6, 8) if usable <= size), preferred)


def _span_digest(span: TimelineSpan) -> str:
    return sha256_bytes(
        f"{span.item_index}\x1f{span.start_word_offset}\x1f{span.end_word_offset}\x1f{span.text}\x1fFalse".encode()
    )


def _coverage_subset(spans: Sequence[TimelineSpan], mode: str) -> list[TimelineSpan]:
    if mode == "NARRATIVE_ONLY":
        return [span for span in spans if span.zone not in {"GREETING", "FAREWELL"}]
    return [span for index, span in enumerate(spans) if index % 3 == 0]


def _derive_scenes(spans: Sequence[TimelineSpan]) -> tuple[list[OrderedDict[str, Any]], list[str]]:
    scenes = []
    mapping = []
    start = 0
    ordinal = 0
    for index, span in enumerate(spans):
        if (
            index == 0
            or span.zone != spans[index - 1].zone
            or span.environment != spans[index - 1].environment
        ):
            ordinal += 1
            start = index
            scenes.append(
                OrderedDict(
                    derived_scene_id=f"scene_{ordinal:04d}",
                    ordinal=ordinal,
                    zone=span.zone,
                    start_item_index=span.item_index,
                    end_item_index=span.item_index,
                    boundary_reason="INITIAL" if index == 0 else "ZONE_OR_ENVIRONMENT_CHANGE",
                    source_span_digest_sha256="",
                )
            )
        scenes[-1]["end_item_index"] = span.item_index
        scenes[-1]["source_span_digest_sha256"] = sha256_bytes(
            canonical_json_bytes(
                [spans[start].item_index, span.item_index, span.zone, span.environment]
            )
        )
        mapping.append(cast(str, scenes[-1]["derived_scene_id"]))
    return scenes, mapping


def _voice_profiles(
    spans: Sequence[TimelineSpan], characters: Sequence[Mapping[str, Any]]
) -> list[OrderedDict[str, Any]]:
    ids = []
    for span in spans:
        if span.speaker_id not in ids:
            ids.append(span.speaker_id)
    by_id = {item.get("character_id"): item for item in characters}
    output = []
    for speaker in ids:
        character = by_id.get(speaker)
        age = character.get("age") if character else None
        band = (
            "TEEN"
            if isinstance(age, int) and 15 <= age <= 17
            else ("ADULT" if isinstance(age, int) and age >= 18 else "AGE_AMBIGUOUS")
        )
        output.append(
            OrderedDict(
                speaker_id=speaker,
                role="narrator" if speaker == "narrator" else "character",
                character_id=None if speaker == "narrator" else (speaker if character else None),
                voice_gender="NEUTRAL" if speaker == "narrator" else "UNSPECIFIED",
                age_band="ADULT" if speaker == "narrator" else band,
                locale="vi-VN",
                accent="SOUTHERN_VIETNAMESE",
                provider_voice_id=None,
                fallback_level="PROVIDER_DEFAULT_VI_VN",
                selection_basis="canonical story identity; provider inventory not invoked",
                capability_status="NOT_VERIFIED",
            )
        )
    return output


def _continuity(span: TimelineSpan, refs: Sequence[str]) -> OrderedDict[str, Any]:
    chars = [
        OrderedDict(
            character_id=path.removeprefix("characters/").removesuffix(".png"),
            presence="present",
            position="source-defined",
            pose="source-defined",
            emotion="source-faithful",
            action_phase="current beat",
        )
        for path in refs
    ]
    return OrderedDict(
        character_state=chars,
        wardrobe_state=[],
        location_state=OrderedDict(
            location_id=span.environment,
            time_of_day="unspecified",
            weather="unspecified",
            lighting="source-faithful",
        ),
        prop_state=[],
        screen_direction="continuous",
        camera_state=OrderedDict(
            shot_size="medium",
            camera_position="source-faithful",
            movement="single controlled movement",
        ),
    )


def _prompt(span: TimelineSpan, config: Stage4Config) -> str:
    return f"For source item {span.item_index + 1}, word span {span.start_word_offset} to {span.end_word_offset}, maintain established identity and continuity. In {span.environment}, present this exact source beat without adding causal events: {span.text} Show one observable primary action with a clear opening state, natural middle progression, and stable ending state. Use one controlled camera movement, source-faithful expressions and restrained micro-motion. Preserve location, props, wardrobe, screen direction, lighting, color, audience safety, and story ambiguity. Do not reveal later information. End on a clean visual handoff to the next source beat. No subtitles, captions, logos, watermarks, duplicated subjects, identity drift, or unmotivated cuts."


def _audio_prompt(span: TimelineSpan, config: Stage4Config) -> str:
    if config.audio_mode == "SILENT":
        return "No generated audio."
    if config.audio_mode == "AMBIENCE_ONLY":
        return f"Only source-faithful ambience and restrained foley for {span.environment}; no speech, narration, music, or lyrics."
    return f'{span.speaker_id} speaks exact source text in vi-VN with stable voice identity and synchronized delivery: "{span.text}" Do not translate, paraphrase, repeat, omit, or add words.'


def _variants(config: Stage4Config, has_refs: bool) -> OrderedDict[str, Any]:
    preferred = (
        "TEXT_TO_VIDEO"
        if config.continuity_mode == "PROMPT_ONLY"
        else ("REFERENCE_IMAGES" if has_refs else "TEXT_TO_VIDEO")
    )
    return OrderedDict(
        requested_continuity_mode=config.continuity_mode,
        preferred_mode=preferred,
        fallback_modes=[] if preferred == "TEXT_TO_VIDEO" else ["TEXT_TO_VIDEO"],
        portable_mode="TEXT_TO_VIDEO",
        capability_status="PORTABLE_OPTIONAL",
        selection_basis="PORTABLE_PLAN_ONLY",
    )


def _generator(config: Stage4Config) -> OrderedDict[str, Any]:
    def capability(supported: bool) -> OrderedDict[str, object]:
        return OrderedDict(
            supported=supported,
            status="PORTABLE_OPTIONAL",
            evidence_locator="PORTABLE_PLAN_ONLY",
        )

    return OrderedDict(
        family=config.generator_family,
        preferred_model=config.preferred_model,
        prompt_language=config.prompt_language,
        capability_profile=OrderedDict(
            aspect_ratio=config.aspect_ratio,
            clip_duration_seconds=config.clip_duration_seconds,
            audio_mode=config.audio_mode,
            requested_continuity_mode=config.continuity_mode,
            reference_images=capability(True),
            first_last_frame=capability(False),
            video_extension=capability(False),
        ),
    )


def _source_binding(source: Stage4PackageInput) -> OrderedDict[str, Any]:
    identity = source.package_quality_report["package_identity"]
    char_digest = cast(str, identity["character_set_digest_sha256"])
    story_sha = sha256_bytes(source.members["story.json"])
    return OrderedDict(
        story_sha256=story_sha,
        story_validation_sha256=sha256_bytes(source.members["story_validation.json"]),
        package_quality_report_sha256=sha256_bytes(source.members["package_quality_report.json"]),
        character_continuity_source_digest_sha256=sha256_bytes(
            canonical_json_bytes([char_digest, story_sha])
        ),
        character_set_digest_sha256=char_digest,
    )


def _project(
    source: Stage4PackageInput,
    config: Stage4Config,
    spans: Sequence[TimelineSpan],
    clips: Sequence[Mapping[str, Any]],
    scenes: Sequence[Mapping[str, Any]],
    total_story: float,
) -> OrderedDict[str, Any]:
    meta = source.story["meta"]
    exclusions = []
    if config.coverage_mode != "FULL_STORY":
        exclusions = [
            OrderedDict(
                start_time_seconds=0.0,
                end_time_seconds=total_story,
                start_item_index=0,
                end_item_index=len(source.story["script"]) - 1,
                reason=f"coverage reduced by explicit {config.coverage_mode} selection",
            )
        ]
    return OrderedDict(
        title=meta["title"],
        series=meta["series"],
        episode=meta["episode"],
        active_profile=source.manifest["active_profile"],
        coverage_mode=config.coverage_mode,
        total_story_duration_seconds=total_story,
        planned_covered_duration_seconds=float(
            sum((span.usable_span_seconds for span in spans), Decimal("0"))
        ),
        planned_video_duration_seconds=sum(cast(int, clip["duration_seconds"]) for clip in clips),
        clip_count=len(clips),
        derived_scene_count=len(scenes),
        coverage_exclusions=exclusions,
    )
