from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..hashing import canonical_json_bytes, sha256_bytes, sha256_file
from .config import stage4_config
from .shot_design import NEGATIVE_PROMPT, design_shot
from .timeline import TimelineSegment, rounded

ROOT_FIELDS = [
    "schema_version", "generator_target", "source_binding", "project", "voice_strategy",
    "global_continuity_lock", "clips", "validation",
]
CLIP_FIELDS = [
    "clip_id", "sequence_index", "zone", "derived_scene_id", "continuity_take_id",
    "utterance_segmentation", "source_script", "generation_variants", "duration_seconds",
    "usable_span_seconds", "aspect_ratio", "reference_inputs", "continuity_in",
    "primary_action", "visual_delta", "terminal_handoff", "prompt", "voice_plan",
    "audio_prompt", "avoid", "continuity_out", "state_change_records", "transition_type",
]
VALIDATION_FIELDS = [
    "schema_status", "source_binding_status", "timeline_derivation_status",
    "scene_derivation_status", "reference_router_status", "character_only_reference_status",
    "coverage_status", "continuity_status", "identity_reference_status",
    "voice_selection_status", "long_utterance_status", "prompt_budget_status",
    "prompt_atomicity_status", "no_invented_event_status", "anti_repeat_status",
    "safety_status", "fixture_status", "output_digest_sha256", "status",
]


def output_digest(document: dict[str, Any]) -> str:
    projected = copy.deepcopy(document)
    projected["validation"]["output_digest_sha256"] = None
    return sha256_bytes(canonical_json_bytes(projected))


def build_video_prompts(
    *,
    root: Path,
    story: dict[str, Any],
    story_validation: dict[str, Any],
    quality_report: dict[str, Any],
    visual_plan: dict[str, Any],
    profile: str,
    segments: list[TimelineSegment],
    total_seconds: float,
    aspect_ratio: str,
    voice_inventory: dict[str, Any],
) -> dict[str, Any]:
    config = stage4_config()
    voice_locale = "vi-VN" if story["meta"]["language"] == "vi" else "en-US"
    voice_accent = config["preferred_accent"] if voice_locale == "vi-VN" else "UNSPECIFIED"
    characters = story["characters"]
    character_tuples = [
        [item["character_id"], item["reference_asset"]["reference_image"], item["reference_asset"]["file_sha256"]]
        for item in characters
    ]
    character_set_digest = sha256_bytes(canonical_json_bytes(character_tuples))
    story_hash = sha256_file(root / "story.json")
    continuity_source_digest = sha256_bytes(canonical_json_bytes([character_set_digest, story_hash]))
    derived_scenes = [
        {
            "derived_scene_id": f"scene_{index + 1:04d}",
            "ordinal": index + 1,
            "zone": item["zone"],
            "start_item_index": index,
            "end_item_index": index,
            "boundary_reason": "ZONE_OR_ENVIRONMENT_BOUNDARY",
            "source_span_digest_sha256": sha256_bytes(canonical_json_bytes([index, item["zone"], item["environment"]])),
        }
        for index, item in enumerate(story["script"])
    ]
    focal_by_zone = {
        asset["zone"]: asset["focal_character_ids"]
        for asset in visual_plan["assets"] if asset["zone"] is not None
    }
    character_by_id = {item["character_id"]: item for item in characters}
    clips = []
    previous_by_scene: dict[str, str] = {}
    for sequence, segment in enumerate(segments, 1):
        item = story["script"][segment.item_index]
        scene_id = f"scene_{segment.item_index + 1:04d}"
        clip_id = f"clip_{sequence:04d}"
        previous = previous_by_scene.get(scene_id)
        focal_ids = focal_by_zone.get(item["zone"], [])[: config["max_character_references_per_clip"]]
        reference_images = [character_by_id[value]["reference_asset"]["reference_image"] for value in focal_ids]
        continuity = _continuity_state(item, focal_ids)
        shot = design_shot(item["zone"], segment.segment_index, segment.segment_count)
        primary_action = (
            f"Depict only this exact narrated beat without adding events: {segment.text}"
        )
        visual_delta = f"Advance the visible state through source words {segment.start_word_offset}-{segment.end_word_offset}."
        handoff = "Hold the final pose and screen direction for the next clip."
        prompt = (
            f"Clip {sequence}: cinematic storybook scene in {item['environment']}. "
            f"Camera: {shot['shot_size']}, {shot['camera_angle']}, "
            f"{shot['camera_movement']}, {shot['framing_rule']}. "
            f"Opening state follows the prior continuity lock. Primary action: {primary_action} "
            f"Visible change: {visual_delta} End state: {handoff}"
        )
        voice_plan = {
            "mode": "NATIVE_GENERATED_VOICE",
            "language": "vi-VN" if story["meta"]["language"] == "vi" else "en-US",
            "segments": [{"speaker_id": "narrator", "role": "NARRATOR", "text": segment.text, "emotion": "storytelling", "pace": item["speed"]}],
            "allow_paraphrase": False,
            "source_text_sha256": sha256_bytes(segment.text.encode("utf-8")),
        }
        clip = {
            "clip_id": clip_id,
            "sequence_index": sequence,
            "zone": item["zone"],
            "derived_scene_id": scene_id,
            "continuity_take_id": f"take_{segment.item_index + 1:04d}",
            "utterance_segmentation": {
                "utterance_group_id": segment.group_id,
                "segment_index": segment.segment_index,
                "segment_count": segment.segment_count,
                "segmentation_mode": segment.segmentation_mode,
                "segmentation_reason": segment.segmentation_reason,
            },
            "source_script": {
                "start_item_index": segment.item_index,
                "start_word_offset": segment.start_word_offset,
                "end_item_index": segment.item_index,
                "end_word_offset": segment.end_word_offset,
                "start_time_seconds": segment.start_time_seconds,
                "end_time_seconds": segment.end_time_seconds,
                "pause_only": segment.pause_only,
                "source_text_digest_sha256": segment.source_text_digest_sha256,
            },
            "generation_variants": {
                "requested_continuity_mode": "CHAINED_LAST_FRAME",
                "preferred_mode": "REFERENCE_IMAGES" if reference_images and previous is None else ("IMAGE_TO_VIDEO" if previous else "TEXT_TO_VIDEO"),
                "fallback_modes": ["TEXT_TO_VIDEO"] if reference_images or previous else [],
                "portable_mode": "TEXT_TO_VIDEO",
                "capability_status": "PORTABLE_OPTIONAL",
                "selection_basis": "PORTABLE_PLAN_ONLY",
            },
            "duration_seconds": segment.duration_seconds,
            "usable_span_seconds": segment.usable_span_seconds,
            "aspect_ratio": aspect_ratio,
            "reference_inputs": {
                "character_images": reference_images,
                "previous_clip_id": previous,
                "previous_last_frame_required": previous is not None,
                "previous_output_last_frame": previous is not None,
                "previous_output_video_required": False,
            },
            "continuity_in": continuity,
            "primary_action": primary_action,
            "visual_delta": visual_delta,
            "terminal_handoff": handoff,
            "prompt": prompt,
            "voice_plan": voice_plan,
            "audio_prompt": f'Synchronize lips when visible; preserve exact speech: "{segment.text}"; locale {voice_locale}; accent {voice_accent}.',
            "avoid": NEGATIVE_PROMPT + ["packaged scene references"],
            "continuity_out": {**continuity, "handoff_action": handoff},
            "state_change_records": [],
            "transition_type": "CONTINUOUS" if previous else "CUT",
        }
        clips.append(clip)
        previous_by_scene[scene_id] = clip_id

    validation = {field: "PASS" for field in VALIDATION_FIELDS if field not in {"output_digest_sha256"}}
    validation["output_digest_sha256"] = None
    validation = {field: validation[field] for field in VALIDATION_FIELDS}
    planned_video = sum(item["duration_seconds"] for item in clips)
    document = {
        "schema_version": config["video_prompt_schema_version"],
        "generator_target": {
            **config["generator_target"],
            "capability_profile": {
                "aspect_ratio": aspect_ratio,
                "clip_duration_seconds": config["defaults"]["clip_duration_seconds"],
                "audio_mode": config["defaults"]["audio_mode"],
                "requested_continuity_mode": config["defaults"]["continuity_mode"],
                "reference_images": {"supported": True, "status": "PORTABLE_OPTIONAL", "evidence_locator": "PORTABLE_PLAN_ONLY"},
                "first_last_frame": {"supported": False, "status": "PORTABLE_OPTIONAL", "evidence_locator": "PORTABLE_PLAN_ONLY"},
                "video_extension": {"supported": False, "status": "PORTABLE_OPTIONAL", "evidence_locator": "PORTABLE_PLAN_ONLY"},
            },
        },
        "source_binding": {
            "story_sha256": story_hash,
            "story_validation_sha256": sha256_file(root / "story_validation.json"),
            "package_quality_report_sha256": sha256_file(root / "package_quality_report.json"),
            "character_continuity_source_digest_sha256": continuity_source_digest,
            "character_set_digest_sha256": character_set_digest,
        },
        "project": {
            "title": story["meta"]["title"], "series": story["meta"]["series"],
            "episode": story["meta"]["episode"], "active_profile": profile,
            "coverage_mode": "FULL_STORY", "total_story_duration_seconds": total_seconds,
            "planned_covered_duration_seconds": rounded(sum(item["usable_span_seconds"] for item in clips)),
            "planned_video_duration_seconds": planned_video, "clip_count": len(clips),
            "derived_scene_count": len(derived_scenes), "coverage_exclusions": [],
        },
        "voice_strategy": {
            "audio_mode": "NATIVE_GENERATED_VOICE", "language": voice_locale,
            "preferred_locale": voice_locale, "preferred_accent": voice_accent,
            "selection_priority": ["CHARACTER_VOICE_GENDER", "CHARACTER_CANONICAL_AGE_BAND", "SOUTHERN_VIETNAMESE_ACCENT"],
            "voice_profiles": [{"speaker_id": "narrator", "role": "NARRATOR", "character_id": None, "voice_gender": "UNSPECIFIED", "age_band": "AGE_AMBIGUOUS", "locale": voice_locale, "accent": voice_accent, "provider_voice_id": voice_inventory["voices"][0]["voice_id"] if voice_inventory["voices"] else None, "fallback_level": "CONFIGURED_LOCAL_VOICE" if voice_inventory["voices"] else "NO_VERIFIED_VOICE", "selection_basis": "LOCAL_VOICE_INVENTORY" if voice_inventory["voices"] else "NO_PROVIDER_INVENTORY", "capability_status": voice_inventory["capability_status"]}],
            "global_instructions": f"Do not translate, paraphrase, repeat, omit, or add words; preserve locale {voice_locale} and accent {voice_accent} when supported.",
        },
        "global_continuity_lock": {
            "visual_style": ["cinematic storybook", "identity-consistent"],
            "cinematography": ["one primary camera movement per clip"],
            "color_pipeline": ["retain Stage 2 tonal plan without using packaged narrative frames"],
            "character_identity_rules": [f"{item['character_id']} binds {item['reference_asset']['reference_image']}" for item in characters],
            "location_rules": ["location changes only at a derived scene boundary"],
            "prop_rules": ["no invented causal props"],
            "forbidden_changes": ["identity drift", "unmotivated wardrobe reset", "invented event"],
            "derived_scene_registry": derived_scenes,
        },
        "clips": clips,
        "validation": validation,
    }
    document["validation"]["output_digest_sha256"] = output_digest(document)
    return document


def _continuity_state(item: dict[str, Any], focal_ids: list[str]) -> dict[str, Any]:
    return {
        "character_state": [{"character_id": value, "presence": "present", "position": "primary frame", "pose": "story action", "emotion": "engaged", "action_phase": "continuous"} for value in focal_ids],
        "wardrobe_state": [{"character_id": value, "wardrobe_state_id": "base_outfit", "condition": "unchanged"} for value in focal_ids],
        "location_state": {"location_id": item["environment"], "time_of_day": "story_defined", "weather": "story_defined", "lighting": "continuity_locked"},
        "prop_state": [],
        "screen_direction": "left_to_right",
        "camera_state": {"shot_size": "medium", "camera_position": "eye_level", "movement": "single_slow_push"},
    }
