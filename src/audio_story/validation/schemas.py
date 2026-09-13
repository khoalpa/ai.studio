"""Versioned deterministic schema inventory for runtime artifacts."""

from __future__ import annotations

from dataclasses import dataclass

from audio_story.validation.errors import ValidationError, ValidationFinding
from audio_story.validation.strict_json import OrderedObject, validate_field_order


@dataclass(frozen=True, slots=True)
class SchemaSpec:
    identifier: str
    version: str
    phases: tuple[str, ...]
    root_order: tuple[str, ...] | None
    implementation_status: str


SCHEMAS = {
    spec.identifier: spec
    for spec in (
        SchemaSpec("story.json", "2.3", ("INPUT", "OUTPUT"), None, "NOT_VERIFIED"),
        SchemaSpec("story_validation.json", "1.2", ("INPUT", "OUTPUT"), None, "NOT_VERIFIED"),
        SchemaSpec("workflow_manifest.json", "1.0", ("INPUT", "OUTPUT"), None, "NOT_VERIFIED"),
        SchemaSpec(
            "visual_plan.json",
            "1.0",
            ("INPUT", "OUTPUT"),
            (
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
            ),
            "IMPLEMENTED",
        ),
        SchemaSpec(
            "visual_bible.json",
            "2.0",
            ("INPUT", "OUTPUT"),
            (
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
            ),
            "IMPLEMENTED",
        ),
        SchemaSpec(
            "stage_image_progress.json",
            "1.0",
            ("INPUT", "OUTPUT"),
            (
                "schema_version",
                "bundle_kind",
                "stage",
                "orientation",
                "original_operation_mode",
                "input_story_package_digest_sha256",
                "input_story_zip_sha256",
                "active_basename_set_digest_sha256",
                "visual_plan_digest_sha256",
                "visual_bible_availability",
                "visual_bible_digest_sha256",
                "required_count",
                "committed_count",
                "pending_count",
                "failed_count",
                "assets",
                "last_committed_basename",
                "next_pending_basename",
                "missing_assets",
                "status",
                "progress_digest_sha256",
            ),
            "IMPLEMENTED",
        ),
        SchemaSpec("package_quality_report.json", "1.0", ("INPUT", "OUTPUT"), None, "NOT_VERIFIED"),
        SchemaSpec("video_prompts.json", "1.2", ("INPUT", "OUTPUT"), None, "NOT_VERIFIED"),
        SchemaSpec(
            "deterministic_validation_result.json",
            "1.0",
            ("OUTPUT",),
            (
                "schema_version",
                "validator_name",
                "validator_version",
                "validator_source",
                "canonical_prompt_sha256",
                "invocation",
                "input_bindings",
                "overall_status",
                "checks",
                "findings",
                "evidence_digests",
                "result_digest",
                "result_self_reopen_status",
            ),
            "IMPLEMENTED",
        ),
    )
}


def validate_schema(value: object, artifact_name: str, phase: str, artifact_path: str) -> str:
    spec = SCHEMAS.get(artifact_name)
    if spec is None:
        raise ValidationError(
            ValidationFinding(
                "DS001_UNKNOWN_SCHEMA", "artifact schema is not registered", artifact_path
            )
        )
    if phase not in spec.phases:
        raise ValidationError(
            ValidationFinding(
                "DS002_UNSUPPORTED_PHASE", f"phase {phase} is unsupported", artifact_path
            )
        )
    if not isinstance(value, OrderedObject):
        raise ValidationError(
            ValidationFinding("DS003_ROOT_NOT_OBJECT", "root must be an object", artifact_path, "$")
        )
    if value.get("schema_version") != spec.version:
        raise ValidationError(
            ValidationFinding(
                "DS004_SCHEMA_VERSION",
                f"expected schema_version {spec.version}",
                artifact_path,
                "$.schema_version",
            )
        )
    if spec.root_order is not None:
        validate_field_order(value, spec.root_order, artifact_path)
    return spec.implementation_status
