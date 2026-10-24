from __future__ import annotations

import copy
import importlib.metadata
import json
import platform
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .archive import PackageVerifier
from .errors import PackageError, WorkflowError
from .hashing import canonical_json_bytes, sha256_bytes, sha256_file
from .model_operations import BenchmarkEvaluator

RELEASE_SCHEMA_VERSION = "1.0"
RELEASE_MEMBERS = {
    "story.zip",
    "release_report.json",
    "release_manifest.json",
    "checksums.sha256",
}


def _json_member(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(name).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"Invalid release member {name}: {exc}") from exc
    if not isinstance(value, dict):
        raise PackageError(f"Release member must be an object: {name}")
    return value


def release_report_digest(report: dict[str, Any]) -> str:
    projected = copy.deepcopy(report)
    projected["validation"]["report_digest_sha256"] = None
    return sha256_bytes(canonical_json_bytes(projected))


def _dependency_inventory() -> list[dict[str, str]]:
    records = [
        {"name": "ai-story-spec", "version": __version__},
        {"name": "python", "version": platform.python_version()},
    ]
    for name in ("torch", "diffusers", "transformers", "Pillow"):
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        records.append({"name": name, "version": version})
    return records


def _external_audit(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if path is None:
        return None, "External framework audit is required for production release"
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Cannot read external framework audit: {exc}"
    required = {"schema_version", "status", "auditor", "framework", "version", "evidence_sha256"}
    if not isinstance(audit, dict) or not required.issubset(audit):
        return None, "External framework audit shape is invalid"
    if audit["status"] != "PASS" or audit["schema_version"] != "1.0":
        return audit, "External framework audit did not pass"
    auditor = str(audit["auditor"]).strip()
    digest = str(audit["evidence_sha256"])
    if not auditor or auditor.startswith("ai_story") or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return audit, "External framework audit provenance is invalid"
    return audit, None


def _benchmark_evidence(
    embedded: Any, path: Path | None
) -> tuple[dict[str, Any] | None, list[str]]:
    if path is not None:
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, [f"cannot_read:{exc}"]
    else:
        evidence = embedded
    if not isinstance(evidence, dict) or not evidence:
        return None, ["missing"]
    return evidence, BenchmarkEvaluator().validate_promotion_evidence(evidence)


def _image_benchmark_evidence(path: Path | None) -> tuple[dict[str, Any] | None, list[str]]:
    if path is None:
        return None, ["missing"]
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"cannot_read:{exc}"]
    failures = []
    if evidence.get("report_kind") != "IMAGE_QUALITY_PROMOTION":
        failures.append("report_kind")
    if evidence.get("verdict") != "PROMOTE":
        failures.append("verdict")
    projected = dict(evidence)
    digest = projected.get("report_digest_sha256")
    projected["report_digest_sha256"] = None
    expected = sha256_bytes(json.dumps(
        projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode())
    if digest != expected:
        failures.append("digest")
    if any(item.get("status") != "PASS" for item in evidence.get("checks", [])):
        failures.append("checks")
    return evidence, failures


class ReleaseEvaluator:
    def evaluate(
        self,
        package_path: Path,
        *,
        channel: str = "development",
        framework_audit: Path | None = None,
        benchmark_evidence: Path | None = None,
        image_benchmark_evidence: Path | None = None,
    ) -> dict[str, Any]:
        if channel not in {"development", "production"}:
            raise WorkflowError("Release channel must be development or production")
        verified = PackageVerifier().verify(package_path)
        checks: list[dict[str, Any]] = []
        blockers: list[str] = []

        def check(identifier: str, passed: bool, evidence: Any, *, blocker: bool = True) -> None:
            status = "PASS" if passed else "FAIL"
            checks.append({"id": identifier, "status": status, "evidence": evidence})
            if blocker and not passed:
                blockers.append(identifier)

        with zipfile.ZipFile(package_path, "r") as archive:
            manifest = _json_member(archive, "workflow_manifest.json")
            validation_ledger = _json_member(archive, "validation_ledger.json")
            check("PACKAGE_INTEGRITY", True, {"archive_sha256": verified.archive_sha256})
            package_validation = manifest.get("validation", {})
            check(
                "RELEASABLE_ARTIFACT_CLASS",
                package_validation.get("artifact_class", "PRODUCTION_CANDIDATE")
                != "TEST_FIXTURE",
                package_validation.get("artifact_class", "PRODUCTION_CANDIDATE"),
            )
            check(
                "CONTENT_QUALITY_STATUS",
                package_validation.get("content_quality_status", "NOT_ASSESSED")
                != "BLOCKED",
                package_validation.get("content_quality_status", "NOT_ASSESSED"),
            )
            check("FINAL_STAGE", verified.package_stage == "STAGE4", verified.package_stage)

            story_validation = _json_member(archive, "story_validation.json")
            failing_gates = [
                gate.get("gate_id") or gate.get("id")
                for gate in story_validation.get("gates", [])
                if isinstance(gate, dict)
                and gate.get("status") in {"FAIL", "NOT_VERIFIED", "ASSESSED_FAIL"}
            ]
            check("STORY_GATES", not failing_gates, failing_gates)

            quality = _json_member(archive, "package_quality_report.json")
            quality_pass = (
                quality.get("summary", {}).get("publish_verdict") == "PASS"
                and not quality.get("blockers")
            )
            check("IMAGE_QUALITY", quality_pass, quality.get("summary", {}))

            story_quality = story_validation.get("quality", {})
            editorial_pass = (
                story_quality.get("editorial_status") == "ASSESSED_PASS"
                and int(story_quality.get("final_story_quality_score") or 0)
                >= int(story_quality.get("minimum_editorial_score", 80))
            )
            structured_qa = quality.get("image_evidence", {}).get("structured_visual_qa", [])
            structured_pass = bool(structured_qa) and all(
                isinstance(pair, dict)
                and isinstance(pair.get(orientation), dict)
                and pair[orientation].get("status") == "ASSESSED_PASS"
                for pair in structured_qa
                for orientation in ("landscape", "portrait")
            )
            check("EDITORIAL_EVIDENCE", editorial_pass, story_quality, blocker=channel == "production")
            check("STRUCTURED_VISUAL_QA", structured_pass, {"pair_count": len(structured_qa)}, blocker=channel == "production")

            assessments = [
                *quality.get("image_evidence", {}).get("landscape_assessments", []),
                *quality.get("image_evidence", {}).get("portrait_assessments", []),
            ]
            layered_pass = bool(assessments) and all(
                isinstance(item.get("qa_layers"), list)
                and item["qa_layers"]
                and all(layer.get("status") not in {"FAIL", "ASSESSED_FAIL"} for layer in item["qa_layers"])
                for item in assessments if isinstance(item, dict)
            )
            check(
                "LAYERED_IMAGE_QA", layered_pass,
                {"assessment_count": len(assessments)}, blocker=channel == "production",
            )
            upscale_modes = [
                item.get("upscale_postprocess", {}).get("mode")
                for item in assessments if isinstance(item, dict)
            ]
            upscale_pass = bool(upscale_modes) and all(
                mode in {"LATENT_X2_PLUS_RESIDUAL", "GPT_IMAGE_WEB_EXTERNAL"}
                for mode in upscale_modes
            )
            check(
                "UPSCALE_PROVENANCE", upscale_pass,
                {"modes": sorted(set(value for value in upscale_modes if value))},
                blocker=channel == "production",
            )
            repair_entries = [
                entry for item in assessments if isinstance(item, dict)
                for entry in item.get("repair_history", [])
            ]
            repair_audit_pass = all(
                isinstance(entry, dict)
                and entry.get("failure", {}).get("findings")
                and entry.get("repair_plan", {}).get("planner") == "RULE_BASED_LAYERED_IMAGE_REPAIR_V2"
                for entry in repair_entries
            )
            check(
                "IMAGE_REPAIR_AUDIT", repair_audit_pass,
                {"repair_attempt_count": len(repair_entries)}, blocker=channel == "production",
            )
            assisted = [
                item.get("assist_provenance") for item in assessments
                if isinstance(item, dict) and item.get("assist_provenance")
            ]
            assist_pass = all(
                item.get("workflow") == "MANUAL_OPTIONAL_NO_API"
                and item.get("human_review_confirmed") is True
                and bool(item.get("prompt_sha256")) and bool(item.get("result_sha256"))
                for item in assisted
            )
            check(
                "WEB_ASSIST_DISCLOSURE", assist_pass,
                {"assisted_image_count": len(assisted)}, blocker=channel == "production",
            )

            visual_review = _json_member(archive, "visual_review.json")
            required_reviews = {
                item.get("review_id")
                for item in quality.get("image_evidence", {}).get("visual_review_sample", [])
                if isinstance(item, dict)
            }
            approved_reviews = {
                item.get("review_id")
                for item in visual_review.get("items", [])
                if isinstance(item, dict) and item.get("decision") == "APPROVED"
            }
            human_review_pass = (
                visual_review.get("decision") == "APPROVED"
                and bool(required_reviews)
                and required_reviews <= approved_reviews
            )
            check(
                "HUMAN_VISUAL_REVIEW",
                human_review_pass,
                {"required": sorted(required_reviews), "approved": sorted(approved_reviews)},
                blocker=channel == "production",
            )

            production = _json_member(archive, "production_plan.json")
            check(
                "PRODUCTION_PLAN",
                production.get("validation", {}).get("status") == "PASS",
                production.get("validation", {}),
            )

            generation = manifest.get("generation", {})
            provider_mode = generation.get("provider_mode")
            provider_lineage = generation.get("provider_mode_lineage", [provider_mode])
            local_assessment = (
                quality.get("image_evidence", {}).get("assessment_method")
                == "LOCAL_TECHNICAL_OCR_CLIP"
            )
            providers = generation.get("providers", [])
            required_roles = {"story", "character_image", "safety", "landscape", "portrait"}
            provider_roles = {
                item.get("role") for item in providers if isinstance(item, dict)
            }
            provenance_pass = (
                required_roles <= provider_roles
                and bool(generation.get("prompt_template_version"))
                and bool(generation.get("runtime_metrics_lineage"))
                and bool(generation.get("operational_metrics_lineage"))
                and generation.get("peak_memory_bytes") is not None
                and all(
                    item.get("runtime") and item.get("provider_id")
                    for item in providers if isinstance(item, dict)
                )
            )
            check(
                "PROVENANCE_AND_TELEMETRY",
                provenance_pass,
                {"roles": sorted(role for role in provider_roles if role), "runtime_stage_count": len(generation.get("runtime_metrics_lineage", []))},
                blocker=channel == "production",
            )
            benchmark, benchmark_failures = _benchmark_evidence(
                generation.get("benchmark_evidence", {}), benchmark_evidence
            )
            check(
                "BENCHMARK_PROMOTION", not benchmark_failures,
                {"failures": benchmark_failures, "evidence": benchmark},
                blocker=channel == "production",
            )
            image_benchmark, image_benchmark_failures = _image_benchmark_evidence(
                image_benchmark_evidence
            )
            check(
                "IMAGE_BENCHMARK_PROMOTION", not image_benchmark_failures,
                {"failures": image_benchmark_failures, "evidence": image_benchmark},
                blocker=channel == "production",
            )
            if channel == "production":
                check(
                    "LOCAL_PROVIDER_MODE",
                    provider_mode == "local" and set(provider_lineage) == {"local"},
                    {"current": provider_mode, "lineage": provider_lineage},
                )
                check(
                    "PRODUCTION_IMAGE_ASSESSMENT",
                    local_assessment,
                    quality.get("image_evidence", {}).get("assessment_method"),
                )
                audit, audit_error = _external_audit(framework_audit)
                check("EXTERNAL_FRAMEWORK_AUDIT", audit_error is None, audit_error or audit)
            else:
                audit = None
                check(
                    "DEVELOPMENT_PROVIDER_DISCLOSURE",
                    True,
                    {"provider_mode": provider_mode, "production_equivalent": False},
                    blocker=False,
                )

        report = {
            "schema_version": RELEASE_SCHEMA_VERSION,
            "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
            "release_channel": channel.upper(),
            "release_label": "PRODUCTION" if channel == "production" else "LOCAL_DEVELOPMENT",
            "source_package": {
                "path_name": package_path.name,
                "archive_sha256": verified.archive_sha256,
                "package_digest_sha256": verified.package_digest_sha256,
                "package_stage": verified.package_stage,
                "file_count": verified.file_count,
            },
            "checks": checks,
            "blockers": blockers,
            "warnings": [
                *[
                    record for record in validation_ledger.get("records", [])
                    if record.get("resolution_status") == "OPEN"
                ],
                *[
                    {
                        "record_id": f"RELEASE:{item['id']}",
                        "stage": "RELEASE",
                        "category": "RELEASE_CHECK",
                        "severity": "PUBLISH_BLOCKER",
                        "status": item["status"],
                        "resolution_status": "OPEN",
                        "release_impact": "NOT_RECOMMENDED",
                        "evidence": item.get("evidence"),
                    }
                    for item in checks if item["status"] != "PASS"
                ],
            ],
            "validation_ledger": {
                "ledger_digest_sha256": validation_ledger.get("ledger_digest_sha256"),
                "current_stage": validation_ledger.get("current_stage"),
                "stage_history": validation_ledger.get("stage_history", []),
                "summary": validation_ledger.get("summary", {}),
            },
            "readiness": "READY" if not blockers else "BLOCKED",
            "model_inventory": manifest.get("generation", {}).get("providers", []),
            "dependency_inventory": _dependency_inventory(),
            "framework_audit": audit,
            "limitations": (
                []
                if channel == "production" and not blockers
                else ["Development release is not a production certification"]
            ),
            "validation": {"report_digest_sha256": None, "status": "PASS"},
        }
        report["validation"]["report_digest_sha256"] = release_report_digest(report)
        return report


class ReleaseBundleBuilder:
    def build(
        self,
        package_path: Path,
        output_path: Path,
        *,
        channel: str = "development",
        framework_audit: Path | None = None,
        benchmark_evidence: Path | None = None,
        image_benchmark_evidence: Path | None = None,
    ) -> dict[str, Any]:
        report = ReleaseEvaluator().evaluate(
            package_path, channel=channel, framework_audit=framework_audit,
            benchmark_evidence=benchmark_evidence,
            image_benchmark_evidence=image_benchmark_evidence,
        )
        story_bytes = package_path.read_bytes()
        report_bytes = canonical_json_bytes(report)
        checksums = {
            "story.zip": sha256_bytes(story_bytes),
            "release_report.json": sha256_bytes(report_bytes),
        }
        checksums_bytes = "".join(
            f"{digest}  {name}\n" for name, digest in sorted(checksums.items())
        ).encode("utf-8")
        manifest = {
            "schema_version": RELEASE_SCHEMA_VERSION,
            "release_id": f"release-{channel}-{checksums['story.zip'][:16]}",
            "application_version": __version__,
            "release_channel": report["release_channel"],
            "release_label": report["release_label"],
            "readiness": report["readiness"],
            "distribution_status": (
                "APPROVED" if report["readiness"] == "READY" else "NOT_APPROVED"
            ),
            "source_package_sha256": checksums["story.zip"],
            "release_report_sha256": checksums["release_report.json"],
            "checksums_sha256": sha256_bytes(checksums_bytes),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        members = {
            "story.zip": story_bytes,
            "release_report.json": report_bytes,
            "release_manifest.json": canonical_json_bytes(manifest),
            "checksums.sha256": checksums_bytes,
        }
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(members):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, members[name])
        return ReleaseBundleVerifier().verify(output_path)


class ReleaseBundleVerifier:
    def verify(self, bundle_path: Path) -> dict[str, Any]:
        if not bundle_path.is_file():
            raise PackageError(f"Release bundle does not exist: {bundle_path}")
        with zipfile.ZipFile(bundle_path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != RELEASE_MEMBERS:
                raise PackageError("Release bundle member set is invalid")
            if archive.testzip() is not None:
                raise PackageError("Release bundle CRC validation failed")
            for info in infos:
                limit = 2 * 1024 * 1024 * 1024 if info.filename == "story.zip" else 10 * 1024 * 1024
                if info.file_size > limit:
                    raise PackageError(f"Release member exceeds size limit: {info.filename}")
            manifest = _json_member(archive, "release_manifest.json")
            report = _json_member(archive, "release_report.json")
            story_bytes = archive.read("story.zip")
            report_bytes = archive.read("release_report.json")
            checksums_bytes = archive.read("checksums.sha256")
            if manifest.get("schema_version") != RELEASE_SCHEMA_VERSION:
                raise PackageError("Unsupported release manifest schema")
            expected_distribution = (
                "APPROVED" if report.get("readiness") == "READY" else "NOT_APPROVED"
            )
            if manifest.get("distribution_status") != expected_distribution:
                raise PackageError("Release distribution status does not match its report")
            if manifest.get("source_package_sha256") != sha256_bytes(story_bytes):
                raise PackageError("Release source package hash mismatch")
            if manifest.get("release_report_sha256") != sha256_bytes(report_bytes):
                raise PackageError("Release report hash mismatch")
            if manifest.get("checksums_sha256") != sha256_bytes(checksums_bytes):
                raise PackageError("Release checksum file hash mismatch")
            expected_checksums = "".join(
                f"{digest}  {name}\n"
                for name, digest in sorted(
                    {
                        "story.zip": sha256_bytes(story_bytes),
                        "release_report.json": sha256_bytes(report_bytes),
                    }.items()
                )
            ).encode("utf-8")
            if checksums_bytes != expected_checksums:
                raise PackageError("Release checksum file content mismatch")
            if report.get("validation", {}).get("report_digest_sha256") != release_report_digest(
                report
            ):
                raise PackageError("Release report digest mismatch")
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "story.zip"
            source.write_bytes(story_bytes)
            PackageVerifier().verify(source)
        return {
            "bundle_path": str(bundle_path.resolve()),
            "bundle_sha256": sha256_file(bundle_path),
            "release_id": manifest["release_id"],
            "release_channel": manifest["release_channel"],
            "release_label": manifest["release_label"],
            "readiness": manifest["readiness"],
            "distribution_status": manifest["distribution_status"],
            "source_package_sha256": manifest["source_package_sha256"],
        }
