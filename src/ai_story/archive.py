from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import (
    artifact_owner,
    normalize_member_path,
    scan_artifacts,
    validate_stage_file_set,
)
from .config import registry
from .errors import PackageError
from .hashing import canonical_json_bytes, package_digest, sha256_bytes, sha256_file
from .manifest import MANIFEST_FIELDS, build_manifest
from .models import ArtifactRecord, Operation, PackageResult, Profile, Stage
from .state_machine import TransitionRequest, WorkflowStateMachine
from .validation_ledger import verify_ledger

MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PackageError(f"Duplicate JSON key in manifest: {key}")
        value[key] = item
    return value


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    name = registry()["workflow"]["manifest_name"]
    try:
        raw = archive.read(name)
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"Invalid workflow manifest: {exc}") from exc
    if list(value) != MANIFEST_FIELDS:
        raise PackageError("Manifest root fields or field order are invalid")
    return value


class PackageBuilder:
    def build(
        self,
        *,
        source_dir: Path,
        output_path: Path,
        stage: Stage,
        operation: Operation,
        profile: Profile,
        parent_package_digest_sha256: str | None = None,
        source_stage: Stage | None = None,
        generation: dict[str, Any] | None = None,
        allow_next_stage: bool = True,
        artifact_class: str = "PRODUCTION_CANDIDATE",
        content_quality_status: str = "NOT_ASSESSED",
    ) -> PackageResult:
        WorkflowStateMachine().validate(
            TransitionRequest(profile, stage, operation, source_stage=source_stage)
        )
        records = scan_artifacts(source_dir, stage)
        if not records:
            raise PackageError("Cannot build an empty package")
        if "story.json" not in {record.path for record in records}:
            raise PackageError("story.json is required in every package")
        validate_stage_file_set(records, stage)
        if operation is Operation.CREATE and stage is Stage.STAGE1 and parent_package_digest_sha256 is not None:
            raise PackageError("STAGE1 CREATE must not have a parent package digest")
        if (operation is Operation.REPAIR or stage is not Stage.STAGE1) and not parent_package_digest_sha256:
            raise PackageError("REPAIR and STAGE2-STAGE4 CREATE require a parent package digest")
        if parent_package_digest_sha256 and not SHA256_PATTERN.fullmatch(parent_package_digest_sha256):
            raise PackageError("Parent package digest must be lowercase SHA-256")
        try:
            validation_ledger = json.loads(
                (source_dir / "validation_ledger.json").read_text(encoding="utf-8")
            )
            verify_ledger(validation_ledger)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise PackageError(f"Invalid validation ledger: {exc}") from exc

        manifest = build_manifest(
            stage=stage,
            operation=operation,
            profile=profile,
            records=records,
            parent_package_digest_sha256=parent_package_digest_sha256,
            generation=generation,
            allow_next_stage=allow_next_stage,
            artifact_class=artifact_class,
            content_quality_status=content_quality_status,
            validation_ledger=validation_ledger,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for record in sorted(records, key=lambda item: item.path):
                archive.write(source_dir / PurePosixPath(record.path), record.path)
            manifest_bytes = json.dumps(
                manifest,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            archive.writestr(registry()["workflow"]["manifest_name"], manifest_bytes)

        result = PackageVerifier().verify(output_path)
        if result.package_stage != stage.value:
            raise PackageError("Reopened package stage differs from requested stage")
        return result


class PackageVerifier:
    def verify(self, archive_path: Path) -> PackageResult:
        if not archive_path.is_file():
            raise PackageError(f"Package does not exist: {archive_path}")
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            names = [normalize_member_path(info.filename) for info in infos]
            if len(names) != len(set(names)):
                raise PackageError("Duplicate ZIP member detected")
            if archive.testzip() is not None:
                raise PackageError("ZIP CRC validation failed")
            total = 0
            for info in infos:
                if info.is_dir():
                    raise PackageError("Directory entries are not allowed")
                unix_mode = (info.external_attr >> 16) & 0o170000
                if unix_mode == 0o120000:
                    raise PackageError(f"Symbolic links are not allowed: {info.filename}")
                if info.file_size > MAX_MEMBER_BYTES:
                    raise PackageError(f"ZIP member exceeds size limit: {info.filename}")
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise PackageError("ZIP exceeds total uncompressed size limit")

            manifest = _read_manifest(archive)
            self._verify_manifest(manifest, names, archive)

        return PackageResult(
            archive_path=str(archive_path.resolve()),
            archive_sha256=sha256_file(archive_path),
            package_digest_sha256=manifest["package_digest_sha256"],
            file_count=manifest["file_count"],
            package_stage=manifest["package_stage"],
        )

    @staticmethod
    def _verify_manifest(manifest: dict[str, Any], names: list[str], archive: zipfile.ZipFile) -> None:
        config = registry()
        try:
            stage = Stage(manifest["package_stage"])
            Profile(manifest["active_profile"])
            Operation(manifest["operation_mode"])
        except ValueError as exc:
            raise PackageError(f"Manifest contains an invalid enum: {exc}") from exc
        if manifest["schema_version"] != config["workflow"]["manifest_schema_version"]:
            raise PackageError("Unsupported manifest schema version")
        if manifest["package_purpose"] != config["workflow"]["purpose_by_stage"][stage.value]:
            raise PackageError("Package purpose does not match stage")
        parent_digest = manifest["parent_package_digest_sha256"]
        operation = Operation(manifest["operation_mode"])
        if operation is Operation.CREATE and stage is Stage.STAGE1 and parent_digest is not None:
            raise PackageError("STAGE1 CREATE parent digest must be null")
        if (operation is Operation.REPAIR or stage is not Stage.STAGE1) and not parent_digest:
            raise PackageError("REPAIR and STAGE2-STAGE4 CREATE require a parent package digest")
        if parent_digest and not SHA256_PATTERN.fullmatch(parent_digest):
            raise PackageError("Parent package digest must be lowercase SHA-256")
        expected_next = config["workflow"]["transitions"][stage.value]
        if manifest["allowed_next_stage"] not in {expected_next, None}:
            raise PackageError("allowed_next_stage does not match canonical transition")
        if manifest["file_count"] != len(names):
            raise PackageError("Manifest file_count does not match archive")

        manifest_name = config["workflow"]["manifest_name"]
        listed = manifest["files"]
        paths = [item["path"] for item in listed]
        if len(paths) != len(set(paths)):
            raise PackageError("Duplicate file record in manifest")
        if set(paths) | {manifest_name} != set(names):
            raise PackageError("Manifest file list does not match archive")

        records: list[ArtifactRecord] = []
        for item in listed:
            path = normalize_member_path(item["path"])
            owner = artifact_owner(path)
            if item["owner_stage"] != owner:
                raise PackageError(f"Owner mismatch for {path}")
            if owner != "CURRENT_STAGE":
                order = config["workflow"]["stage_order"]
                if order.index(owner) > order.index(stage.value):
                    raise PackageError(f"Future-stage artifact {path} is not allowed")
            data = archive.read(path)

            if item["size_bytes"] != len(data) or item["sha256"] != sha256_bytes(data):
                raise PackageError(f"Hash or size mismatch for {path}")
            records.append(ArtifactRecord(path, owner, len(data), item["sha256"]))
        if package_digest(records) != manifest["package_digest_sha256"]:
            raise PackageError("Package digest mismatch")
        try:
            contract = json.loads(archive.read("story_contract.json").decode("utf-8"))
            outline_evidence = json.loads(archive.read("outline_evidence.json").decode("utf-8"))
            quality_decision = json.loads(archive.read("quality_decision.json").decode("utf-8"))
            validation_ledger = json.loads(archive.read("validation_ledger.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackageError(f"Invalid Stage 1 quality sidecar: {exc}") from exc
        if outline_evidence.get("story_contract_digest_sha256") != sha256_bytes(
            canonical_json_bytes(contract)
        ):
            raise PackageError("Outline evidence is not bound to story contract")
        projected_decision = dict(quality_decision)
        projected_decision["decision_digest_sha256"] = None
        if quality_decision.get("decision_digest_sha256") != sha256_bytes(
            canonical_json_bytes(projected_decision)
        ):
            raise PackageError("Quality decision digest is invalid")
        story = next((item for item in records if item.path == "story.json"), None)
        if story is None or manifest["story_sha256"] != story.sha256:
            raise PackageError("story_sha256 mismatch")
        if manifest["validation"].get("status") != "PASS":
            raise PackageError("Package validation status is not PASS")
        validation = manifest["validation"]
        if validation.get("integrity_status", "PASS") != "PASS":
            raise PackageError("Package integrity status is not PASS")
        artifact_class = validation.get("artifact_class", "PRODUCTION_CANDIDATE")
        quality_status = validation.get("content_quality_status", "NOT_ASSESSED")
        if artifact_class not in {
            "PRODUCTION_CANDIDATE", "EDITORIAL_DRAFT", "TEST_FIXTURE"
        }:
            raise PackageError("Package artifact class is invalid")
        if quality_status not in {"PASS", "BLOCKED", "NOT_ASSESSED"}:
            raise PackageError("Package content quality status is invalid")
        if quality_decision.get("artifact_class") != artifact_class:
            raise PackageError("Quality decision artifact class does not match manifest")
        has_blocking_decision = bool(quality_decision.get("failed_gate_ids")) or any(
            quality_decision.get(key) == "FAIL"
            for key in ("technical_status", "safety_status", "editorial_status")
        )
        if has_blocking_decision and quality_decision.get("advancement_status") != "BLOCKED":
            raise PackageError("Failed quality decision must block advancement")
        if has_blocking_decision and quality_decision.get("workflow_status") != "COMPLETED_WITH_WARNINGS":
            raise PackageError("Failed quality decision must complete with warnings")
        try:
            verify_ledger(validation_ledger)
        except ValueError as exc:
            raise PackageError(str(exc)) from exc
        if validation.get("validation_ledger_digest_sha256") != validation_ledger.get(
            "ledger_digest_sha256"
        ):
            raise PackageError("Manifest validation ledger digest mismatch")
        if validation.get("open_warning_count") != validation_ledger.get("summary", {}).get(
            "open_warning_count"
        ):
            raise PackageError("Manifest validation warning count mismatch")
        ledger_stage = Stage(validation_ledger.get("current_stage"))
        if config["workflow"]["stage_order"].index(ledger_stage.value) > config["workflow"]["stage_order"].index(stage.value):
            raise PackageError("Validation ledger cannot reference a future package stage")
        continuation = validation.get("continuation_policy", "CONTINUE_WITH_WARNINGS")
        if continuation not in {"CONTINUE", "CONTINUE_WITH_WARNINGS", "BLOCKED"}:
            raise PackageError("Package continuation policy is invalid")
        expected_advancement = quality_decision.get("advancement_status") == "ALLOWED"
        if bool(manifest.get("allowed_next_stage")) != bool(expected_advancement and expected_next):
            raise PackageError("Manifest advancement does not match quality decision")
        if continuation == "BLOCKED" and manifest.get("allowed_next_stage") is not None:
            raise PackageError("Blocked package cannot declare an allowed next stage")
        generation = manifest["generation"]
        if not isinstance(generation, dict) or not isinstance(generation.get("providers"), list):
            raise PackageError("Manifest generation provenance is invalid")
        try:
            validate_stage_file_set(records, stage)
        except Exception as exc:
            raise PackageError(str(exc)) from exc


def extract_inherited(archive_path: Path, destination: Path) -> str:
    """Safely copy all non-manifest members for the next stage."""
    result = PackageVerifier().verify(archive_path)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise PackageError("Inheritance destination must be empty")
    manifest_name = registry()["workflow"]["manifest_name"]
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            normalized = normalize_member_path(info.filename)
            if normalized == manifest_name:
                continue
            target = destination / PurePosixPath(normalized)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    return result.package_digest_sha256
