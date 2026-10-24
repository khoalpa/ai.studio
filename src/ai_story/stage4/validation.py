from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import WorkflowError
from ..hashing import sha256_file
from .builder import CLIP_FIELDS, ROOT_FIELDS, VALIDATION_FIELDS, output_digest
from .timeline import TimelineSegment


def validate_video_prompts(
    document: dict[str, Any], root: Path, segments: list[TimelineSegment]
) -> None:
    if list(document) != ROOT_FIELDS:
        raise WorkflowError("video_prompts.json root shape is invalid")
    if document["schema_version"] != "1.2":
        raise WorkflowError("Unsupported video prompt schema")
    if list(document["validation"]) != VALIDATION_FIELDS:
        raise WorkflowError("Video prompt validation shape is invalid")
    if document["validation"]["output_digest_sha256"] != output_digest(document):
        raise WorkflowError("Video prompt output digest mismatch")
    clips = document["clips"]
    if len(clips) != len(segments) or document["project"]["clip_count"] != len(clips):
        raise WorkflowError("Video prompt clip count mismatch")
    allowed_references = set()
    story = json.loads((root / "story.json").read_text(encoding="utf-8"))
    for character in story["characters"]:
        allowed_references.add(character["reference_asset"]["reference_image"])
    previous_by_scene: dict[str, str] = {}
    for index, (clip, segment) in enumerate(zip(clips, segments), 1):
        if list(clip) != CLIP_FIELDS or clip["sequence_index"] != index or clip["clip_id"] != f"clip_{index:04d}":
            raise WorkflowError(f"Clip shape or sequence invalid at {index}")
        source = clip["source_script"]
        expected = [segment.item_index, segment.start_word_offset, segment.end_word_offset, segment.source_text_digest_sha256]
        actual = [source["start_item_index"], source["start_word_offset"], source["end_word_offset"], source["source_text_digest_sha256"]]
        if actual != expected:
            raise WorkflowError(f"Clip source binding mismatch at {index}")
        references = clip["reference_inputs"]["character_images"]
        if not set(references).issubset(allowed_references) or len(references) > 3:
            raise WorkflowError(f"Invalid character reference at clip {index}")
        serialized = json.dumps(clip, ensure_ascii=False)
        if "landscape/" in serialized or "portrait/" in serialized:
            raise WorkflowError(f"Packaged narrative image referenced at clip {index}")
        scene = clip["derived_scene_id"]
        expected_previous = previous_by_scene.get(scene)
        if clip["reference_inputs"]["previous_clip_id"] != expected_previous:
            raise WorkflowError(f"Continuity chain mismatch at clip {index}")
        if expected_previous and clip["continuity_in"] != {
            key: value for key, value in clips[index - 2]["continuity_out"].items() if key != "handoff_action"
        }:
            raise WorkflowError(f"Continuity state mismatch at clip {index}")
        previous_by_scene[scene] = clip["clip_id"]
    binding = document["source_binding"]
    if binding["story_sha256"] != sha256_file(root / "story.json"):
        raise WorkflowError("Video prompt story binding mismatch")
    if binding["package_quality_report_sha256"] != sha256_file(root / "package_quality_report.json"):
        raise WorkflowError("Video prompt quality report binding mismatch")
