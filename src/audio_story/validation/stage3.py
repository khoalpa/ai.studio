"""M8-A Stage 2 intake, inherited authority and quality-report 2.0 contracts."""

from __future__ import annotations

import re
import zipfile
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn, cast

from audio_story.domain.stage1 import Stage1Error, resolve_profile
from audio_story.domain.stage2 import ZONE_IMAGE_BASENAMES
from audio_story.domain.stage3 import InheritedByteAuthority, Stage2PackageInput, Stage3Error
from audio_story.validation.archives import inspect_zip
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.images import validate_png
from audio_story.validation.schemas import validate_schema
from audio_story.validation.stage1 import (
    MANIFEST_FILE_ROOT,
    MANIFEST_ROOT,
    ordered_json_bytes,
    validate_anchor_bytes,
    validate_character_assets,
    validate_report_bytes,
    validate_story_bytes,
)
from audio_story.validation.stage2 import validate_visual_bible_bytes, validate_visual_plan_bytes
from audio_story.validation.strict_json import OrderedObject, parse_json_bytes, validate_field_order
from audio_story.workflows.stage2_commitment import validate_stage2_commitments

PACKAGE_QUALITY_ROOT = (
    "schema_version",
    "report_id",
    "generated_at_utc",
    "package_identity",
    "registry_bindings",
    "summary",
    "dimensions",
    "measurement_ledger",
    "story_evidence",
    "image_evidence",
    "blockers",
    "recommendations",
    "validation",
)
PACKAGE_IDENTITY_ROOT = (
    "title",
    "active_profile",
    "story_sha256",
    "story_quality_commitment_digest_sha256",
    "character_set_digest_sha256",
    "landscape_set_digest_sha256",
    "portrait_set_digest_sha256",
    "ordered_asset_manifest_digest_sha256",
)
REGISTRY_BINDINGS_ROOT = (
    "quality_component_registry_schema_version",
    "quality_component_registry_digest_sha256",
    "finding_taxonomy_registry_digest_sha256",
    "penalty_profile_registry_digest_sha256",
    "compatibility_adapter_registry_schema_version",
    "compatibility_adapter_registry_digest_sha256",
    "applied_adapter_id",
    "applied_adapter_version",
    "compatibility_evidence_digest_sha256",
    "adapter_output_digest_sha256",
    "excluded_component_ids",
)
SUMMARY_ROOT = (
    "overall_score",
    "quality_rating",
    "publish_verdict",
    "scoring_coverage_ratio",
    "applicable_weight_sum",
    "excluded_weight_sum",
    "strengths",
    "weaknesses",
)
DIMENSION_ROOT = (
    "dimension_id",
    "score",
    "quality_rating",
    "status",
    "applicability_code",
    "coverage_ratio",
    "components",
    "evidence_ids",
    "findings",
    "recommendations",
)
COMPONENT_ROOT = (
    "component_id",
    "component_weight",
    "detector_output_key",
    "raw_score",
    "score",
    "status",
    "applicability_code",
    "measurement_digest_sha256",
    "finding_ids",
    "evidence_ids",
)
IMAGE_EVIDENCE_ROOT = (
    "asset_results",
    "set_results",
    "pair_results",
    "cover_results",
    "evidence_digest_sha256",
)
ASSET_RESULT_ROOT = (
    "path",
    "file_sha256",
    "pixel_sha256",
    "dimensions",
    "orientation",
    "gate_status",
    "quality_score",
    "finding_codes",
    "evidence_ids",
)
BLOCKER_ROOT = ("gate_id", "severity", "status", "artifact_paths", "evidence_ids", "repair_scope")
VALIDATION_ROOT = (
    "schema_status",
    "field_order_status",
    "artifact_binding_status",
    "score_recompute_status",
    "gate_reconciliation_status",
    "report_digest_sha256",
    "status",
)
QUALITY_DIMENSIONS = (
    "STORY_CONTENT",
    "NARRATIVE_ENGAGEMENT",
    "AUDIO_TTS_READABILITY",
    "PROFILE_FIDELITY",
    "CONTINUITY",
    "SAFETY",
    "LANDSCAPE_VISUALS",
    "PORTRAIT_VISUALS",
    "CROSS_ORIENTATION_PARITY",
    "COVER_TYPOGRAPHY",
    "VISUAL_CONSISTENCY",
    "PROVENANCE_INTEGRITY",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {"PASS", "FAIL", "NOT_VERIFIED", "NOT_APPLICABLE"}
_RATINGS = {"EXCELLENT", "GOOD", "ACCEPTABLE", "NEEDS_IMPROVEMENT"}
PROGRESS_ROOT = (
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
)
PROGRESS_ASSET_ROOT = (
    "basename",
    "execution_index",
    "packaging_index",
    "queue_status",
    "asset_source",
    "file_path",
    "file_sha256",
    "transaction_id",
    "postwrite_validation_status",
)


def load_stage2_package(
    path: Path, *, expected_archive_sha256: str | None = None, test_mode: bool = False
) -> Stage2PackageInput:
    """Fully validate and freeze a Stage 2 package without extracting or mutating it."""
    source = path.resolve(strict=True)
    archive_bytes = source.read_bytes()
    archive_digest = sha256_bytes(archive_bytes)
    if expected_archive_sha256 is not None and archive_digest != expected_archive_sha256.lower():
        _fail("M8A001_ARCHIVE_AUTHORITY", "archive SHA-256 does not match authority", str(source))
    names = [item.path for item in inspect_zip(source)]
    if not names or names[0] != "workflow_manifest.json":
        _fail("M8A002_MEMBER_ORDER", "manifest must be first", str(source))
    try:
        with zipfile.ZipFile(source) as archive:
            payload = OrderedDict((name, archive.read(name)) for name in names)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        _fail("M8A003_PACKAGE_READ", f"cannot read package: {exc}", str(source))
    manifest_bytes = payload.pop("workflow_manifest.json")
    try:
        manifest = _ordered(manifest_bytes, "workflow_manifest.json")
        validate_field_order(manifest, MANIFEST_ROOT, "workflow_manifest.json")
        _require(manifest.get("schema_version") == "1.0", "M8A010_MANIFEST", "$.schema_version")
        _require(manifest.get("package_stage") == "STAGE2", "M8A010_MANIFEST", "$.package_stage")
        _require(
            manifest.get("package_purpose") == "WORKFLOW_CHECKPOINT",
            "M8A010_MANIFEST",
            "$.package_purpose",
        )
        _require(
            manifest.get("allowed_next_stage") == "STAGE3",
            "M8A010_MANIFEST",
            "$.allowed_next_stage",
        )
        files = manifest.get("files")
        _require(isinstance(files, list), "M8A011_FILE_SET", "$.files")
        assert isinstance(files, list)
        _require(manifest.get("file_count") == len(files) + 1, "M8A011_FILE_SET", "$.file_count")
        declared_paths: list[str] = []
        authority: list[InheritedByteAuthority] = []
        projection: list[dict[str, object]] = []
        for index, raw in enumerate(files):
            validate_field_order(
                raw, MANIFEST_FILE_ROOT, "workflow_manifest.json", f"$.files[{index}]"
            )
            item = cast(Mapping[str, Any], raw)
            member_path = item.get("path")
            _require(
                isinstance(member_path, str) and member_path in payload,
                "M8A011_FILE_SET",
                f"$.files[{index}].path",
            )
            assert isinstance(member_path, str)
            expected_owner = _owner_for_stage2_path(member_path)
            _require(
                item.get("owner_stage") == expected_owner,
                "M8A012_OWNER",
                f"$.files[{index}].owner_stage",
            )
            expected_mutation = (
                "CREATED_CURRENT_STAGE" if expected_owner == "STAGE2" else "READ_ONLY"
            )
            _require(
                item.get("mutation_status") == expected_mutation,
                "M8A013_MUTATION",
                f"$.files[{index}].mutation_status",
            )
            data = payload[member_path]
            digest = sha256_bytes(data)
            _require(
                item.get("sha256") == digest and item.get("size_bytes") == len(data),
                "M8A014_MEMBER_DIGEST",
                member_path,
            )
            declared_paths.append(member_path)
            projection.append(
                {key: item[key] for key in ("path", "sha256", "size_bytes", "owner_stage")}
            )
            authority.append(InheritedByteAuthority(member_path, expected_owner, digest, len(data)))
        _require(declared_paths == list(payload), "M8A011_FILE_SET", "$.files")
        package_digest = sha256_bytes(canonical_json_bytes(projection))
        _require(
            manifest.get("package_digest_sha256") == package_digest,
            "M8A015_PACKAGE_DIGEST",
            "$.package_digest_sha256",
        )
        story_bytes, report_bytes = payload["story.json"], payload["story_validation.json"]
        profile = manifest.get("active_profile")
        language = cast(Mapping[str, Any], _ordered(story_bytes, "story.json").get("meta", {})).get(
            "language"
        )
        _require(isinstance(language, str), "M8A019_INPUT_CONTRACT", "$.meta.language")
        contract = resolve_profile(cast(str | None, profile), cast(str, language))
        story = validate_story_bytes(story_bytes, contract)
        report = validate_report_bytes(report_bytes, story_bytes, story)
        _require(
            manifest.get("story_sha256") == sha256_bytes(story_bytes),
            "M8A016_STORY_BINDING",
            "$.story_sha256",
        )
        character_paths = tuple(
            item["reference_asset"]["reference_image"] for item in story["characters"]
        )
        character_assets = OrderedDict((name, payload[name]) for name in character_paths)
        validate_character_assets(story, character_assets, test_mode=test_mode)
        plan = validate_visual_plan_bytes(payload["visual_plan.json"])
        bible = validate_visual_bible_bytes(payload["visual_bible.json"])
        _require(
            plan.get("story_sha256") == sha256_bytes(story_bytes),
            "M8A017_PLAN_BINDING",
            "visual_plan.json",
        )
        _require(
            plan.get("story_validation_sha256") == sha256_bytes(report_bytes),
            "M8A017_PLAN_BINDING",
            "visual_plan.json",
        )
        _require(
            bible.get("story_sha256") == sha256_bytes(story_bytes),
            "M8A018_BIBLE_BINDING",
            "visual_bible.json",
        )
        landscape_paths = tuple(f"landscape/{name}" for name in ZONE_IMAGE_BASENAMES)
        expected_paths = (
            "story.json",
            "story_validation.json",
            "visual_plan.json",
            "visual_bible.json",
            *character_paths,
            *landscape_paths,
        )
        if "series_anchor.json" in payload:
            expected_paths = (*expected_paths, "series_anchor.json")
            validate_anchor_bytes(payload["series_anchor.json"], story)
        _require(tuple(payload) == expected_paths, "M8A011_FILE_SET", "story.zip")
        for basename, member_path in zip(ZONE_IMAGE_BASENAMES, landscape_paths, strict=True):
            info = validate_png(
                payload[member_path],
                member_path,
                expected_dimensions=(3840, 2160),
                required_metadata_key="audio_story",
            )
            provenance = info.metadata.get("image_provenance_commitment")
            _require(isinstance(provenance, Mapping), "M8A021_LANDSCAPE_PROVENANCE", member_path)
            transaction_id = cast(Mapping[str, Any], provenance).get("transaction_id")
            _require(
                isinstance(transaction_id, str) and bool(transaction_id),
                "M8A021_LANDSCAPE_PROVENANCE",
                member_path,
            )
            validate_stage2_commitments(payload[member_path], basename, cast(str, transaction_id))
        portrait_paths = tuple(f"portrait/{name}" for name in ZONE_IMAGE_BASENAMES)
        final_set = (
            "workflow_manifest.json",
            *landscape_paths,
            *portrait_paths,
            "story.json",
            "story_validation.json",
            *character_paths,
            "visual_plan.json",
            "visual_bible.json",
            "package_quality_report.json",
        )
        if "series_anchor.json" in payload:
            final_set = (*final_set, "series_anchor.json")
    except (KeyError, TypeError, Stage1Error) as exc:
        if isinstance(exc, Stage3Error):
            raise
        _fail("M8A019_INPUT_CONTRACT", str(exc), str(source))
    if source.read_bytes() != archive_bytes:
        _fail("M8A020_SOURCE_MUTATED", "source changed during intake", str(source))
    return Stage2PackageInput(
        source,
        archive_digest,
        package_digest,
        manifest_bytes,
        payload,
        manifest,
        story,
        report,
        plan,
        bible,
        tuple(authority),
        portrait_paths,
        final_set,
    )


def assert_inherited_bytes(source: Stage2PackageInput, candidate: Mapping[str, bytes]) -> None:
    """Reject missing, extra or mutated inherited bytes before any Stage 3 call."""
    expected = {item.path: item for item in source.inherited_authority}
    _require(set(candidate) == set(expected), "M8A030_AUTHORITY_SET", "inherited_bytes")
    for path, authority in expected.items():
        data = candidate[path]
        _require(
            len(data) == authority.size_bytes and sha256_bytes(data) == authority.sha256,
            "M8A031_INHERITED_MUTATION",
            path,
        )


def serialize_stage3_progress(value: Mapping[str, Any]) -> bytes:
    """Serialize and reopen the CURRENT Stage 3 progress contract."""
    progress = OrderedDict(value)
    progress["progress_digest_sha256"] = None
    progress["progress_digest_sha256"] = sha256_bytes(canonical_json_bytes(progress))
    data = ordered_json_bytes(progress)
    validate_stage3_progress_bytes(data)
    return data


def validate_stage3_progress_bytes(data: bytes) -> OrderedObject:
    progress = _ordered(data, "stage_image_progress.json")
    validate_field_order(progress, PROGRESS_ROOT, "stage_image_progress.json")
    _require(
        progress.get("schema_version") == "1.0"
        and progress.get("bundle_kind") == "STAGE3"
        and progress.get("stage") == "STAGE3"
        and progress.get("orientation") == "PORTRAIT"
        and progress.get("original_operation_mode") in {"CREATE", "REPAIR"}
        and progress.get("visual_bible_availability") == "REQUIRED_PRESENT"
        and progress.get("required_count") == 10
        and progress.get("status") == "IN_PROGRESS",
        "M8B200_PROGRESS_HEADER",
        "$",
    )
    for key in (
        "input_story_package_digest_sha256",
        "input_story_zip_sha256",
        "active_basename_set_digest_sha256",
        "visual_plan_digest_sha256",
        "visual_bible_digest_sha256",
    ):
        _digest(progress.get(key), "M8B201_PROGRESS_DIGEST", f"$.{key}")
    assets = progress.get("assets")
    _require(isinstance(assets, list) and len(assets) == 10, "M8B202_PROGRESS_ASSETS", "$.assets")
    assert isinstance(assets, list)
    seen: set[str] = set()
    committed = pending = failed = 0
    for index, asset in enumerate(assets):
        validate_field_order(
            asset, PROGRESS_ASSET_ROOT, "stage_image_progress.json", f"$.assets[{index}]"
        )
        name = asset.get("basename")
        _require(
            isinstance(name, str) and name in ZONE_IMAGE_BASENAMES and name not in seen,
            "M8B202_PROGRESS_ASSETS",
            f"$.assets[{index}].basename",
        )
        seen.add(cast(str, name))
        _require(
            asset.get("execution_index") == index + 1,
            "M8B203_PROGRESS_ORDER",
            f"$.assets[{index}].execution_index",
        )
        _require(
            asset.get("packaging_index") == ZONE_IMAGE_BASENAMES.index(cast(str, name)) + 1,
            "M8B203_PROGRESS_ORDER",
            f"$.assets[{index}].packaging_index",
        )
        status = asset.get("queue_status")
        if status == "COMMITTED":
            committed += 1
            _require(
                asset.get("asset_source") in {"CURRENT_OPERATION", "EMBEDDED_INPUT"}
                and asset.get("file_path") == f"portrait/{name}",
                "M8B204_PROGRESS_COMMIT",
                f"$.assets[{index}]",
            )
            _digest(
                asset.get("file_sha256"), "M8B204_PROGRESS_COMMIT", f"$.assets[{index}].file_sha256"
            )
        elif status == "PENDING":
            pending += 1
            _require(
                all(
                    asset.get(key) is None
                    for key in (
                        "asset_source",
                        "file_path",
                        "file_sha256",
                        "transaction_id",
                        "postwrite_validation_status",
                    )
                ),
                "M8B205_PROGRESS_PENDING",
                f"$.assets[{index}]",
            )
        else:
            failed += 1
            _require(
                status in {"FAILED_RETRYABLE", "FAILED_BLOCKING"},
                "M8B206_PROGRESS_STATUS",
                f"$.assets[{index}].queue_status",
            )
    _require(
        progress.get("committed_count") == committed
        and progress.get("pending_count") == pending
        and progress.get("failed_count") == failed,
        "M8B207_PROGRESS_COUNTS",
        "$",
    )
    expected = progress.get("progress_digest_sha256")
    _digest(expected, "M8B208_PROGRESS_SELF_DIGEST", "$.progress_digest_sha256")
    projection = OrderedDict(progress)
    projection["progress_digest_sha256"] = None
    _require(
        expected == sha256_bytes(canonical_json_bytes(projection)),
        "M8B208_PROGRESS_SELF_DIGEST",
        "$.progress_digest_sha256",
    )
    return progress


def serialize_package_quality_report(value: Mapping[str, Any]) -> bytes:
    """Materialize schema 2.0 with a deterministic self-digest and parse-back."""
    report = OrderedDict(value)
    validation = report.get("validation")
    if not isinstance(validation, Mapping):
        _fail("M8A100_REPORT_VALIDATION", "validation must be an object", "$.validation")
    report["validation"] = OrderedDict(cast(Mapping[str, Any], validation))
    report["validation"]["report_digest_sha256"] = None
    report["validation"]["report_digest_sha256"] = sha256_bytes(canonical_json_bytes(report))
    data = ordered_json_bytes(report)
    validate_package_quality_report_bytes(data)
    return data


def validate_package_quality_report_bytes(data: bytes) -> OrderedObject:
    report = _ordered(data, "package_quality_report.json")
    validate_schema(report, "package_quality_report.json", "INPUT", "package_quality_report.json")
    validate_field_order(report, PACKAGE_QUALITY_ROOT, "package_quality_report.json")
    _fields(report.get("package_identity"), PACKAGE_IDENTITY_ROOT, "$.package_identity")
    bindings = _fields(
        report.get("registry_bindings"), REGISTRY_BINDINGS_ROOT, "$.registry_bindings"
    )
    summary = _fields(report.get("summary"), SUMMARY_ROOT, "$.summary")
    _require(
        bindings.get("quality_component_registry_schema_version") == "2.0",
        "M8A101_REGISTRY",
        "$.registry_bindings",
    )
    _require(
        bindings.get("compatibility_adapter_registry_schema_version") == "1.1",
        "M8A101_REGISTRY",
        "$.registry_bindings",
    )
    for key in (
        "quality_component_registry_digest_sha256",
        "finding_taxonomy_registry_digest_sha256",
        "penalty_profile_registry_digest_sha256",
        "compatibility_adapter_registry_digest_sha256",
    ):
        _digest(bindings.get(key), "M8A101_REGISTRY", f"$.registry_bindings.{key}")
    dimensions = report.get("dimensions")
    _require(
        isinstance(dimensions, list) and len(dimensions) == 12, "M8A102_DIMENSIONS", "$.dimensions"
    )
    assert isinstance(dimensions, list)
    for index, dimension in enumerate(dimensions):
        current = _fields(dimension, DIMENSION_ROOT, f"$.dimensions[{index}]")
        _require(
            current.get("dimension_id") == QUALITY_DIMENSIONS[index],
            "M8A102_DIMENSIONS",
            f"$.dimensions[{index}].dimension_id",
        )
        components = current.get("components")
        _require(
            isinstance(components, list) and bool(components),
            "M8A103_COMPONENTS",
            f"$.dimensions[{index}].components",
        )
        assert isinstance(components, list)
        weight = 0
        for child_index, component in enumerate(components):
            child = _fields(
                component, COMPONENT_ROOT, f"$.dimensions[{index}].components[{child_index}]"
            )
            child_weight = child.get("component_weight")
            _require(
                isinstance(child_weight, int) and child_weight > 0,
                "M8A103_COMPONENTS",
                f"$.dimensions[{index}].components[{child_index}].component_weight",
            )
            weight += cast(int, child_weight)
            _require(
                child.get("status") in _STATUSES,
                "M8A103_COMPONENTS",
                f"$.dimensions[{index}].components[{child_index}].status",
            )
            _require(
                isinstance(child.get("score"), int) and 0 <= cast(int, child.get("score")) <= 100,
                "M8A109_SCORE_RECOMPUTE",
                f"$.dimensions[{index}].components[{child_index}].score",
            )
            _digest(
                child.get("measurement_digest_sha256"),
                "M8A103_COMPONENTS",
                f"$.dimensions[{index}].components[{child_index}].measurement_digest_sha256",
            )
        _require(weight == 100, "M8A103_COMPONENTS", f"$.dimensions[{index}].components")
        scores = [cast(int, cast(Mapping[str, Any], item).get("score")) for item in components]
        weights = [
            cast(int, cast(Mapping[str, Any], item).get("component_weight")) for item in components
        ]
        expected_score = (
            sum(
                score * component_weight
                for score, component_weight in zip(scores, weights, strict=True)
            )
            // 100
        )
        _require(
            current.get("score") == expected_score
            and current.get("status") in _STATUSES
            and current.get("quality_rating") in _RATINGS,
            "M8A109_SCORE_RECOMPUTE",
            f"$.dimensions[{index}]",
        )
    dimension_scores = [cast(int, cast(Mapping[str, Any], item)["score"]) for item in dimensions]
    expected_overall = sum(dimension_scores) // len(dimension_scores)
    all_pass = all(cast(Mapping[str, Any], item).get("status") == "PASS" for item in dimensions)
    blockers_value = report.get("blockers")
    _require(
        summary.get("overall_score") == expected_overall
        and summary.get("scoring_coverage_ratio") == 1.0
        and summary.get("publish_verdict")
        == ("PASS" if all_pass and not blockers_value else "FAIL"),
        "M8A109_SCORE_RECOMPUTE",
        "$.summary",
    )
    image_evidence = _fields(report.get("image_evidence"), IMAGE_EVIDENCE_ROOT, "$.image_evidence")
    assets = image_evidence.get("asset_results")
    _require(isinstance(assets, list), "M8A104_IMAGE_EVIDENCE", "$.image_evidence.asset_results")
    assert isinstance(assets, list)
    for index, asset in enumerate(assets):
        _fields(asset, ASSET_RESULT_ROOT, f"$.image_evidence.asset_results[{index}]")
    blockers = report.get("blockers")
    _require(isinstance(blockers, list), "M8A105_BLOCKERS", "$.blockers")
    assert isinstance(blockers, list)
    for index, blocker in enumerate(blockers):
        _fields(blocker, BLOCKER_ROOT, f"$.blockers[{index}]")
    validation = _fields(report.get("validation"), VALIDATION_ROOT, "$.validation")
    expected_digest = validation.get("report_digest_sha256")
    _digest(expected_digest, "M8A106_REPORT_DIGEST", "$.validation.report_digest_sha256")
    projection = OrderedDict(report)
    projection["validation"] = OrderedDict(cast(Mapping[str, Any], validation))
    projection["validation"]["report_digest_sha256"] = None
    _require(
        expected_digest == sha256_bytes(canonical_json_bytes(projection)),
        "M8A106_REPORT_DIGEST",
        "$.validation.report_digest_sha256",
    )
    report_id = report.get("report_id")
    identity = cast(Mapping[str, Any], report["package_identity"])
    registry_digest = bindings["quality_component_registry_digest_sha256"]
    asset_manifest_digest = identity["ordered_asset_manifest_digest_sha256"]
    preimage = f"PACKAGE_QUALITY_REPORT|2.0|{registry_digest}|{asset_manifest_digest}"
    _require(
        report_id == "pqr_" + sha256_bytes(preimage.encode("utf-8"))[:24],
        "M8A107_REPORT_ID",
        "$.report_id",
    )
    timestamp = report.get("generated_at_utc")
    _require(
        isinstance(timestamp, str) and _valid_timestamp(timestamp),
        "M8A108_TIMESTAMP",
        "$.generated_at_utc",
    )
    return report


def _owner_for_stage2_path(path: str) -> str:
    if path in {"visual_plan.json", "visual_bible.json"} or path.startswith("landscape/"):
        return "STAGE2"
    if path in {"story.json", "story_validation.json", "series_anchor.json"} or path.startswith(
        "characters/"
    ):
        return "STAGE1"
    _fail("M8A012_OWNER", "path has no inherited owner", path)


def _ordered(data: bytes, name: str) -> OrderedObject:
    value = parse_json_bytes(data, name, engine_generated=True).value
    _require(isinstance(value, OrderedObject), "M8A090_ROOT", name)
    return cast(OrderedObject, value)


def _fields(value: object, order: Sequence[str], locator: str) -> OrderedObject:
    validate_field_order(value, tuple(order), "package_quality_report.json", locator)
    return cast(OrderedObject, value)


def _digest(value: object, code: str, locator: str) -> None:
    _require(isinstance(value, str) and bool(_HEX64.fullmatch(value)), code, locator)


def _valid_timestamp(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _require(condition: bool, code: str, locator: str) -> None:
    if not condition:
        raise Stage3Error(code, "Stage 3 contract violation", locator)


def _fail(code: str, message: str, locator: str) -> NoReturn:
    raise Stage3Error(code, message, locator)
