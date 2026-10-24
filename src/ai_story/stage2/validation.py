from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import WorkflowError
from ..hashing import sha256_file
from ..stage1.config import stage1_config
from ..stage1.png import png_dimensions
from .config import basenames, stage2_config
from .planning import VISUAL_BIBLE_FIELDS, VISUAL_PLAN_FIELDS, digest_with_null


def validate_stage1_source(
    story: dict[str, Any], report: dict[str, Any], profile: str, story_path: Path
) -> None:
    actual_story_hash = sha256_file(story_path)
    if report.get("story_sha256") != actual_story_hash:
        raise WorkflowError("Stage 1 report does not bind the inherited story bytes")
    if report.get("active_profile") != profile:
        raise WorkflowError("Stage 1 report profile differs from package profile")
    config = stage1_config()
    if (
        story.get("schema_version") != config["story_schema_version"]
        or report.get("schema_version") != config["story_validation_schema_version"]
    ):
        raise WorkflowError("Stage 2 requires current Story and validation schemas")
    # Content gates are advisory. Hash, profile and schema checks above remain fatal
    # because a later stage cannot safely interpret structurally invalid input.


def validate_stage2_documents(plan: dict[str, Any], bible: dict[str, Any], root: Path) -> None:
    if list(plan) != VISUAL_PLAN_FIELDS:
        raise WorkflowError("visual_plan.json root shape is invalid")
    if list(bible) != VISUAL_BIBLE_FIELDS:
        raise WorkflowError("visual_bible.json root shape is invalid")
    if plan.get("schema_version") != stage2_config()["visual_plan_schema_version"]:
        raise WorkflowError("Visual Plan schema version is not current")
    if bible.get("schema_version") != stage2_config()["visual_bible_schema_version"]:
        raise WorkflowError("Visual Bible schema version is not current")
    if plan["resolved_mode"] != "ZONE" or plan["requested_mode"] != "ZONE":
        raise WorkflowError("Stage 2 MVP requires ZONE mode")
    if plan["visual_plan_digest_sha256"] != digest_with_null(plan, "visual_plan_digest_sha256"):
        raise WorkflowError("Visual plan digest mismatch")
    if bible["dependency_digest"] != digest_with_null(bible, "dependency_digest"):
        raise WorkflowError("Visual Bible dependency digest mismatch")
    required_identity_fields = {
        "character_id", "name", "canonical_age_range", "identity_traits", "presentation",
        "hair", "wardrobe", "palette", "silhouette", "cultural_context", "reference_image",
        "reference_sha256", "master_reference_set", "adult_visual_status",
    }
    for lock in bible.get("character_identity_locks", []):
        if not isinstance(lock, dict) or set(lock) != required_identity_fields:
            raise WorkflowError("Visual Bible character identity lock is incomplete")
        if lock["presentation"] not in {"MASCULINE", "FEMININE", "ANDROGYNOUS", "UNSPECIFIED"}:
            raise WorkflowError("Visual Bible character presentation is invalid")
        views = lock["master_reference_set"].get("views", [])
        if {item.get("view_id") for item in views} != {"full_body_front", "face_closeup", "three_quarter"}:
            raise WorkflowError("Visual Bible character master reference set is invalid")
    expected = basenames()
    if [item["basename"] for item in plan["assets"]] != expected:
        raise WorkflowError("Visual plan basename order mismatch")
    dimensions = [stage2_config()["landscape"]["width"], stage2_config()["landscape"]["height"]]
    for ordinal, item in enumerate(plan["assets"], 1):
        if item["ordinal"] != ordinal or item["validation_status"] != "PASS":
            raise WorkflowError(f"Visual plan asset status invalid: {item['basename']}")
        binding = item["landscape_image"]
        shot = item.get("shot_spec")
        required_shot_fields = {
            "subject_character_ids", "subjects", "action", "emotion", "props", "prop_layout",
            "location", "time", "required_elements", "forbidden_elements", "composition",
            "control_guidance",
        }
        if not isinstance(shot, dict) or set(shot) != required_shot_fields:
            raise WorkflowError(f"Shot specification invalid: {item['basename']}")
        if set(shot["subject_character_ids"]) != set(item["focal_character_ids"]):
            raise WorkflowError(f"Shot character binding mismatch: {item['basename']}")
        if [entry.get("character_id") for entry in shot["subjects"]] != shot["subject_character_ids"]:
            raise WorkflowError(f"Shot subject layout binding mismatch: {item['basename']}")
        for subject in shot["subjects"]:
            position = subject.get("position", {})
            if any(not isinstance(position.get(axis), (int, float)) or not 0 <= position[axis] <= 1 for axis in ("x", "y")):
                raise WorkflowError(f"Shot subject coordinates invalid: {item['basename']}")
        if [entry.get("name") for entry in shot["prop_layout"]] != shot["props"]:
            raise WorkflowError(f"Shot prop layout binding mismatch: {item['basename']}")
        control_inputs = shot["control_guidance"].get("inputs")
        if not isinstance(control_inputs, list):
            raise WorkflowError(f"Shot control guidance inputs invalid: {item['basename']}")
        for control in control_inputs:
            required_control_fields = {
                "schema_version", "control_type", "method", "model_id",
                "control_map_sha256", "width", "height", "conditioning_scale",
                "reference_count", "source",
            }
            if not isinstance(control, dict) or set(control) != required_control_fields:
                raise WorkflowError(f"Shot control guidance evidence invalid: {item['basename']}")
            if control["control_type"] != "depth" or not control["control_map_sha256"]:
                raise WorkflowError(f"Shot depth guidance binding invalid: {item['basename']}")
        structured = binding.get("quality_assessment", {}).get("structured_visual_qa")
        if not isinstance(structured, dict) or structured.get("status") not in {"ASSESSED_PASS", "PARTIALLY_ASSESSED", "NOT_ASSESSED"}:
            raise WorkflowError(f"Structured visual QA missing or failed: {item['basename']}")
        if binding.get("quality_assessment", {}).get("status") not in {"PASS", "ASSESSED_PASS"}:
            raise WorkflowError(f"Landscape quality assessment failed: {item['basename']}")
        assessment_control = binding.get("quality_assessment", {}).get("control_guidance")
        if control_inputs and assessment_control != control_inputs[0]:
            raise WorkflowError(f"Landscape control guidance provenance mismatch: {item['basename']}")
        upscale = binding.get("quality_assessment", {}).get("upscale_postprocess", {})
        if upscale.get("mode") not in {
            "LATENT_X2_PLUS_RESIDUAL", "LANCZOS_FALLBACK", "FIXTURE_DIRECT",
            "GPT_IMAGE_WEB_EXTERNAL",
        }:
            raise WorkflowError(f"Landscape upscale evidence invalid: {item['basename']}")
        if upscale.get("output_size") != dimensions:
            raise WorkflowError(f"Landscape upscale output binding invalid: {item['basename']}")
        layers = binding.get("quality_assessment", {}).get("qa_layers")
        if not isinstance(layers, list) or not layers:
            raise WorkflowError(f"Landscape layered QA evidence missing: {item['basename']}")
        path = root / binding["path"]
        if not path.is_file() or sha256_file(path) != binding["file_sha256"]:
            raise WorkflowError(f"Landscape binding mismatch: {item['basename']}")
        if list(png_dimensions(path.read_bytes())) != dimensions:
            raise WorkflowError(f"Landscape dimensions invalid: {item['basename']}")
