from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import WorkflowError
from ..hashing import sha256_file
from .config import stage4_config
from .production import PRODUCTION_FIELDS, production_digest
from .shot_design import NEGATIVE_PROMPT


def validate_production_plan(document: dict[str, Any], root: Path, clip_count: int) -> None:
    if list(document) != PRODUCTION_FIELDS:
        raise WorkflowError("Production plan root shape is invalid")
    if document["schema_version"] != "1.0":
        raise WorkflowError("Unsupported production plan schema")
    if document["validation"]["production_digest_sha256"] != production_digest(document):
        raise WorkflowError("Production plan digest mismatch")
    if document["validation"]["status"] != "PASS":
        raise WorkflowError("Production plan validation is not PASS")
    video_prompts_path = root / "video_prompts.json"
    video_prompts = json.loads(video_prompts_path.read_text(encoding="utf-8"))
    shots = document["shot_registry"]
    if len(shots) != clip_count or [item["sequence_index"] for item in shots] != list(
        range(1, clip_count + 1)
    ):
        raise WorkflowError("Production shot registry does not match video clips")
    config = stage4_config()
    vocabulary = document["camera_vocabulary"]
    if vocabulary != config["camera_vocabulary"]:
        raise WorkflowError("Production camera vocabulary is not canonical")
    allowed = {
        "shot_size": set(vocabulary["shot_sizes"]),
        "camera_angle": set(vocabulary["angles"]),
        "camera_movement": set(vocabulary["movements"]),
    }
    for shot, clip in zip(shots, video_prompts["clips"]):
        for key, values in allowed.items():
            if shot["camera"][key] not in values:
                raise WorkflowError(f"Shot uses unknown camera term: {shot['shot_id']} {key}")
        if clip["avoid"][: len(NEGATIVE_PROMPT)] != NEGATIVE_PROMPT:
            raise WorkflowError(f"Clip omits the global negative prompt: {shot['shot_id']}")
        if shot["negative_prompt"] != ", ".join(clip["avoid"]):
            raise WorkflowError(f"Shot negative prompt is not canonical: {shot['shot_id']}")
    negative_policy = document["negative_prompt_policy"]
    if negative_policy["global_terms"] != NEGATIVE_PROMPT or negative_policy[
        "per_shot_override_allowed"
    ]:
        raise WorkflowError("Production negative prompt policy is not canonical")
    graph = document["continuity_graph"]
    if (
        graph["node_count"] != clip_count
        or graph["edge_count"] != max(0, clip_count - 1)
        or len(graph["edges"]) != graph["edge_count"]
    ):
        raise WorkflowError("Production continuity graph is incomplete")
    for index, edge in enumerate(graph["edges"]):
        if (
            edge["from_clip_id"] != shots[index]["clip_id"]
            or edge["to_clip_id"] != shots[index + 1]["clip_id"]
            or edge["required_state_digest_sha256"]
            != shots[index + 1]["continuity_in_digest_sha256"]
        ):
            raise WorkflowError("Production continuity edge does not match shot order")
    binding = document["source_binding"]
    if binding["video_prompts_sha256"] != sha256_file(video_prompts_path):
        raise WorkflowError("Production plan does not bind video prompts")
    subtitles = document["subtitle_delivery"]
    if subtitles["entry_count"] != clip_count or len(subtitles["entries"]) != clip_count:
        raise WorkflowError("Subtitle delivery must contain one entry per clip")
    if subtitles["formats"] != config["subtitle_formats"]:
        raise WorkflowError("Subtitle formats are not canonical")
    for path_key, hash_key in (("srt_path", "srt_sha256"), ("webvtt_path", "webvtt_sha256")):
        path = root / subtitles[path_key]
        if not path.is_file() or sha256_file(path) != subtitles[hash_key]:
            raise WorkflowError("Subtitle artifact binding mismatch")
    audio = document["audio_delivery"]
    if audio["status"] == "RENDERED":
        if len(audio["records"]) != clip_count:
            raise WorkflowError("Rendered audio set must contain one file per clip")
        for record in audio["records"]:
            path = root / record["path"]
            if not path.is_file() or sha256_file(path) != record["sha256"]:
                raise WorkflowError(f"Audio artifact binding mismatch: {record['clip_id']}")
        if [record["clip_id"] for record in audio["records"]] != [
            shot["clip_id"] for shot in shots
        ]:
            raise WorkflowError("Rendered audio order does not match shot order")
    elif audio["records"]:
        raise WorkflowError("Unrendered audio delivery cannot contain records")
    presets = document["export_presets"]
    selected_ratio = presets["selected_aspect_ratio"]
    if (
        presets["available"] != config["export_presets"]
        or selected_ratio not in presets["available"]
        or presets["selected"] != presets["available"][selected_ratio]
    ):
        raise WorkflowError("Production export preset is not canonical")
