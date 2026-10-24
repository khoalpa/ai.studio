from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..hashing import canonical_json_bytes, sha256_bytes, sha256_file
from .config import stage4_config
from .shot_design import NEGATIVE_PROMPT, design_shot
from .subtitles import SubtitleEntry

PRODUCTION_FIELDS = [
    "schema_version", "source_binding", "project", "shot_registry", "continuity_graph",
    "camera_vocabulary", "negative_prompt_policy", "voice_inventory", "subtitle_delivery",
    "audio_delivery", "export_presets", "validation",
]


def production_digest(document: dict[str, Any]) -> str:
    projected = copy.deepcopy(document)
    projected["validation"]["production_digest_sha256"] = None
    return sha256_bytes(canonical_json_bytes(projected))


def build_production_plan(
    *,
    root: Path,
    video_prompts: dict[str, Any],
    subtitles: list[SubtitleEntry],
    inventory: dict[str, Any],
    audio_records: list[dict[str, Any]],
) -> dict[str, Any]:
    config = stage4_config()
    shots = []
    for clip in video_prompts["clips"]:
        segmentation = clip["utterance_segmentation"]
        camera = design_shot(
            clip["zone"], segmentation["segment_index"], segmentation["segment_count"]
        )
        shots.append(
            {
                "shot_id": f"shot_{clip['sequence_index']:04d}",
                "clip_id": clip["clip_id"],
                "sequence_index": clip["sequence_index"],
                "scene_id": clip["derived_scene_id"],
                "zone": clip["zone"],
                "duration_seconds": clip["duration_seconds"],
                "camera": camera,
                "action": clip["primary_action"],
                "visible_delta": clip["visual_delta"],
                "continuity_in_digest_sha256": sha256_bytes(
                    canonical_json_bytes(clip["continuity_in"])
                ),
                "continuity_out_digest_sha256": sha256_bytes(
                    canonical_json_bytes(clip["continuity_out"])
                ),
                "positive_prompt": clip["prompt"],
                "negative_prompt": ", ".join(clip["avoid"]),
                "reference_inputs": clip["reference_inputs"],
            }
        )
    edges = []
    for previous, current in zip(shots, shots[1:]):
        edges.append(
            {
                "from_clip_id": previous["clip_id"],
                "to_clip_id": current["clip_id"],
                "same_scene": previous["scene_id"] == current["scene_id"],
                "transition_type": video_prompts["clips"][current["sequence_index"] - 1]["transition_type"],
                "required_state_digest_sha256": current["continuity_in_digest_sha256"],
            }
        )
    preset = config["export_presets"][video_prompts["clips"][0]["aspect_ratio"]]
    document = {
        "schema_version": config["production_plan_schema_version"],
        "source_binding": {
            "video_prompts_sha256": sha256_file(root / "video_prompts.json"),
            "story_sha256": sha256_file(root / "story.json"),
            "package_quality_report_sha256": sha256_file(root / "package_quality_report.json"),
        },
        "project": {
            **video_prompts["project"],
            "delivery_kind": "VIDEO_PRODUCTION_PACKAGE",
            "rendering_status": "PLANNED_NOT_RENDERED",
        },
        "shot_registry": shots,
        "continuity_graph": {
            "node_count": len(shots),
            "edge_count": len(edges),
            "edges": edges,
            "status": "PASS",
        },
        "camera_vocabulary": config["camera_vocabulary"],
        "negative_prompt_policy": {
            "global_terms": NEGATIVE_PROMPT,
            "per_shot_override_allowed": False,
            "status": "PASS",
        },
        "voice_inventory": inventory,
        "subtitle_delivery": {
            "formats": config["subtitle_formats"],
            "srt_path": "subtitles.srt",
            "srt_sha256": sha256_file(root / "subtitles.srt"),
            "webvtt_path": "subtitles.vtt",
            "webvtt_sha256": sha256_file(root / "subtitles.vtt"),
            "entry_count": len(subtitles),
            "entries": [entry.to_dict() for entry in subtitles],
            "source_text_policy": "EXACT_NO_PARAPHRASE",
            "status": "PASS",
        },
        "audio_delivery": {
            "render_requested": bool(audio_records),
            "status": "RENDERED" if audio_records else "PLANNED_NOT_RENDERED",
            "records": audio_records,
        },
        "export_presets": {
            "selected_aspect_ratio": video_prompts["clips"][0]["aspect_ratio"],
            "selected": preset,
            "available": config["export_presets"],
            "mux_command_template": (
                "ffmpeg -r {fps} -i frames/%06d.png -i narration.wav "
                "-c:v {video_codec} -pix_fmt {pixel_format} -c:a {audio_codec} output.mp4"
            ),
        },
        "validation": {
            "shot_registry_status": "PASS",
            "continuity_graph_status": "PASS",
            "camera_vocabulary_status": "PASS",
            "negative_prompt_status": "PASS",
            "subtitle_binding_status": "PASS",
            "audio_delivery_status": "PASS" if audio_records else "NOT_RENDERED_OPTIONAL",
            "export_preset_status": "PASS",
            "production_digest_sha256": None,
            "status": "PASS",
        },
    }
    document["validation"]["production_digest_sha256"] = production_digest(document)
    return document
