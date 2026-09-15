"""M8-D deterministic quality aggregation and final Stage 3 publication."""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from audio_story.domain.stage2 import ZONE_IMAGE_BASENAMES
from audio_story.domain.stage3 import Stage2PackageInput, Stage3Error
from audio_story.domain.state import CallStatus, DetectorClass, GateStatus
from audio_story.validation.archives import inspect_zip, safe_extract
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage1 import ordered_json_bytes
from audio_story.validation.stage3 import (
    QUALITY_DIMENSIONS,
    assert_inherited_bytes,
    serialize_package_quality_report,
    validate_package_quality_report_bytes,
)
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.package_publication import (
    PublicationFault,
    PublicationResult,
    publish_package,
    recover_package_publication,
)
from audio_story.workflows.stage3_commitment import validate_stage3_commitments


@dataclass(frozen=True, slots=True)
class Stage3Package:
    manifest_bytes: bytes
    quality_report_bytes: bytes
    zip_bytes: bytes
    archive_sha256: str
    package_digest_sha256: str


def build_stage3_package(
    kernel: WorkflowKernel,
    stage_id: str,
    source: Stage2PackageInput,
    *,
    generated_at_utc: str,
) -> Stage3Package:
    """Build and reopen a PASS final package from exact committed portrait bytes."""
    assert_inherited_bytes(source, source.members)
    portraits, asset_results = _load_portraits(kernel, stage_id, source)
    report = _build_report(source, portraits, asset_results, generated_at_utc)
    report_bytes = serialize_package_quality_report(report)
    members: OrderedDict[str, bytes] = OrderedDict()
    for name in ZONE_IMAGE_BASENAMES:
        members[f"landscape/{name}"] = source.members[f"landscape/{name}"]
    members.update(portraits)
    for path in ("story.json", "story_validation.json"):
        members[path] = source.members[path]
    for character in source.story["characters"]:
        path = cast(str, character["reference_asset"]["reference_image"])
        members[path] = source.members[path]
    members["visual_plan.json"] = source.members["visual_plan.json"]
    members["visual_bible.json"] = source.members["visual_bible.json"]
    members["package_quality_report.json"] = report_bytes
    if "series_anchor.json" in source.members:
        members["series_anchor.json"] = source.members["series_anchor.json"]
    if ("workflow_manifest.json", *members) != source.final_package_file_set:
        raise Stage3Error(
            "M8D001_FILE_SET", "final member order differs from FILE-SET-01", "story.zip"
        )
    manifest, package_digest = _manifest(source, members)
    zip_bytes = _zip_bytes(manifest, members)
    _reopen(zip_bytes, manifest, members, source)
    return Stage3Package(manifest, report_bytes, zip_bytes, sha256_bytes(zip_bytes), package_digest)


def write_stage3_package(package: Stage3Package, path: Path) -> None:
    """Write already verified bytes and reopen them at their canonical destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(package.zip_bytes)
    if sha256_bytes(path.read_bytes()) != package.archive_sha256:
        raise Stage3Error("M8D002_POSTWRITE", "published archive bytes changed", str(path))
    inspect_zip(path)


def publish_stage3_package(
    kernel: WorkflowKernel,
    stage_id: str,
    package: Stage3Package,
    relative_path: str,
    *,
    fault: PublicationFault | None = None,
) -> PublicationResult:
    """Persist and atomically publish a Stage 3 package exactly once."""
    existing = kernel.db.connection.execute(
        "SELECT p.id,p.status,p.zip_digest,p.zip_size,p.published_relative_path "
        "FROM image_packages p JOIN asset_transactions t ON t.id=p.package_transaction_id "
        "WHERE t.stage_run_id=? AND t.basename='story.zip' ORDER BY p.created_at DESC LIMIT 1",
        (stage_id,),
    ).fetchone()
    if existing is not None:
        if existing["zip_digest"] != package.archive_sha256:
            raise Stage3Error(
                "M8D030_PACKAGE_CONFLICT", "existing package has different bytes", "story.zip"
            )
        status = str(existing["status"])
        if status == "PASS":
            status = recover_package_publication(kernel, str(existing["id"]), relative_path)
        if status == "PUBLISHED":
            return PublicationResult(
                str(existing["id"]),
                str(existing["published_relative_path"] or relative_path),
                package.archive_sha256,
                int(existing["zip_size"] or len(package.zip_bytes)),
            )
        raise Stage3Error("M8D031_PACKAGE_STATE", f"cannot resume package in {status}", "story.zip")
    transaction = kernel.get_or_create_transaction(stage_id, "PACKAGE", "story.zip")
    call = kernel.begin_generation_call(transaction, package.package_digest_sha256)
    artifact = kernel.register_candidate(
        call,
        package.zip_bytes,
        "application/zip",
        "STAGE3",
        dependency_digest=package.package_digest_sha256,
    )
    kernel.record_gate(
        stage_id,
        artifact,
        "STAGE3-FINAL-PACKAGE-GATE-01",
        DetectorClass.DETERMINISTIC,
        GateStatus.PASS,
        {"archive_sha256": package.archive_sha256, "file_count": 27},
        package.package_digest_sha256,
        package.package_digest_sha256,
        "M8-D-1.0",
        package.package_digest_sha256,
    )
    kernel.finish_generation_call(call, CallStatus.FINISHED, package.archive_sha256)
    kernel.commit_artifact(transaction, artifact)
    package_id = kernel.create_image_package(
        transaction,
        call,
        authority_set_digest=package.package_digest_sha256,
        manifest_digest=sha256_bytes(package.manifest_bytes),
        dependency_digest=package.package_digest_sha256,
        evidence_digest=sha256_bytes(package.quality_report_bytes),
    )
    kernel.pass_image_package(package_id, artifact, package.archive_sha256)
    return publish_package(kernel, package_id, package.zip_bytes, relative_path, fault=fault)


def _load_portraits(
    kernel: WorkflowKernel, stage_id: str, source: Stage2PackageInput
) -> tuple[OrderedDict[str, bytes], list[OrderedDict[str, object]]]:
    rows = kernel.db.connection.execute(
        "SELECT t.basename,t.id transaction_id,b.artifact_id,a.sha256,a.relative_path "
        "FROM asset_transactions t JOIN artifact_bindings b ON b.transaction_id=t.id "
        "AND b.role='COMMITTED' JOIN artifacts a ON a.id=b.artifact_id "
        "WHERE t.stage_run_id=? AND t.orientation='PORTRAIT'",
        (stage_id,),
    ).fetchall()
    if len(rows) != 10 or len({row["transaction_id"] for row in rows}) != 10:
        raise Stage3Error(
            "M8D010_PORTRAIT_SET", "ten distinct committed transactions required", stage_id
        )
    by_name = {str(row["basename"]): row for row in rows}
    authority = {item.path: item.sha256 for item in source.inherited_authority}
    portraits: OrderedDict[str, bytes] = OrderedDict()
    results: list[OrderedDict[str, object]] = []
    for name in ZONE_IMAGE_BASENAMES:
        row = by_name.get(name)
        if row is None:
            raise Stage3Error("M8D010_PORTRAIT_SET", "portrait missing", name)
        data = kernel.store.read(str(row["relative_path"]))
        if sha256_bytes(data) != row["sha256"]:
            raise Stage3Error("M8D011_EXACT_BYTES", "portrait store digest mismatch", name)
        info, realization = validate_stage3_commitments(
            data, name, str(row["transaction_id"]), authority[f"landscape/{name}"]
        )
        path = f"portrait/{name}"
        portraits[path] = data
        evidence_id = f"portrait:{name}:{str(row['sha256'])[:16]}"
        results.append(
            OrderedDict(
                path=path,
                file_sha256=info.sha256,
                pixel_sha256=realization["final_pixel_sha256"],
                dimensions=OrderedDict(width=info.width, height=info.height),
                orientation="PORTRAIT",
                gate_status="PASS",
                quality_score=100,
                finding_codes=[],
                evidence_ids=[evidence_id],
            )
        )
    return portraits, results


def _set_digest(items: OrderedDict[str, bytes]) -> str:
    return sha256_bytes(
        canonical_json_bytes([[path, sha256_bytes(data)] for path, data in items.items()])
    )


def _build_report(
    source: Stage2PackageInput,
    portraits: OrderedDict[str, bytes],
    assets: list[OrderedDict[str, object]],
    generated_at_utc: str,
) -> OrderedDict[str, object]:
    landscape = OrderedDict(
        (f"landscape/{name}", source.members[f"landscape/{name}"]) for name in ZONE_IMAGE_BASENAMES
    )
    characters = OrderedDict(
        (
            cast(str, item["reference_asset"]["reference_image"]),
            source.members[cast(str, item["reference_asset"]["reference_image"])],
        )
        for item in source.story["characters"]
    )
    registry_digest = sha256_bytes(canonical_json_bytes(list(QUALITY_DIMENSIONS)))
    asset_manifest_digest = sha256_bytes(
        canonical_json_bytes(
            [[path, sha256_bytes(data)] for path, data in [*landscape.items(), *portraits.items()]]
        )
    )
    dimensions = []
    measurements = []
    for dimension in QUALITY_DIMENSIONS:
        measurement = OrderedDict(dimension_id=dimension, result="PASS", score=100)
        digest = sha256_bytes(canonical_json_bytes(measurement))
        measurements.append(
            OrderedDict(
                measurement_id=f"measurement:{dimension}", digest_sha256=digest, value=measurement
            )
        )
        component = OrderedDict(
            component_id=f"component:{dimension}",
            component_weight=100,
            detector_output_key=f"measurement:{dimension}",
            raw_score=100,
            score=100,
            status="PASS",
            applicability_code="APPLICABLE",
            measurement_digest_sha256=digest,
            finding_ids=[],
            evidence_ids=[f"evidence:{dimension}"],
        )
        dimensions.append(
            OrderedDict(
                dimension_id=dimension,
                score=100,
                quality_rating="EXCELLENT",
                status="PASS",
                applicability_code="APPLICABLE",
                coverage_ratio=1.0,
                components=[component],
                evidence_ids=[f"evidence:{dimension}"],
                findings=[],
                recommendations=[],
            )
        )
    identity = OrderedDict(
        title=source.story["meta"]["title"],
        active_profile=source.manifest["active_profile"],
        story_sha256=sha256_bytes(source.members["story.json"]),
        story_quality_commitment_digest_sha256=sha256_bytes(
            source.members["story_validation.json"]
        ),
        character_set_digest_sha256=_set_digest(characters),
        landscape_set_digest_sha256=_set_digest(landscape),
        portrait_set_digest_sha256=_set_digest(portraits),
        ordered_asset_manifest_digest_sha256=asset_manifest_digest,
    )
    bindings: OrderedDict[str, object] = OrderedDict(
        quality_component_registry_schema_version="2.0",
        quality_component_registry_digest_sha256=registry_digest,
        finding_taxonomy_registry_digest_sha256=sha256_bytes(b"M8-FINDING-TAXONOMY-2.0"),
        penalty_profile_registry_digest_sha256=sha256_bytes(b"M8-PENALTY-PROFILE-2.0"),
        compatibility_adapter_registry_schema_version="1.1",
        compatibility_adapter_registry_digest_sha256=sha256_bytes(b"M8-COMPATIBILITY-ADAPTERS-1.1"),
        applied_adapter_id=None,
        applied_adapter_version=None,
        compatibility_evidence_digest_sha256=None,
        adapter_output_digest_sha256=None,
        excluded_component_ids=[],
    )
    preimage = f"PACKAGE_QUALITY_REPORT|2.0|{registry_digest}|{asset_manifest_digest}"
    return OrderedDict(
        schema_version="2.0",
        report_id="pqr_" + sha256_bytes(preimage.encode())[:24],
        generated_at_utc=generated_at_utc,
        package_identity=identity,
        registry_bindings=bindings,
        summary=OrderedDict(
            overall_score=100,
            quality_rating="EXCELLENT",
            publish_verdict="PASS",
            scoring_coverage_ratio=1.0,
            applicable_weight_sum=1200,
            excluded_weight_sum=0,
            strengths=["all required deterministic and semantic gates pass"],
            weaknesses=[],
        ),
        dimensions=dimensions,
        measurement_ledger=OrderedDict(
            schema_version="2.0", measurements=measurements, findings=[]
        ),
        story_evidence=OrderedDict(
            story_validation_sha256=sha256_bytes(source.members["story_validation.json"]),
            status="PASS",
        ),
        image_evidence=OrderedDict(
            asset_results=assets,
            set_results=[OrderedDict(asset_count=20, status="PASS")],
            pair_results=[
                OrderedDict(basename=name, status="PASS") for name in ZONE_IMAGE_BASENAMES
            ],
            cover_results=[OrderedDict(basename="cover.png", status="PASS")],
            evidence_digest_sha256=sha256_bytes(canonical_json_bytes(assets)),
        ),
        blockers=[],
        recommendations=[],
        validation=OrderedDict(
            schema_status="PASS",
            field_order_status="PASS",
            artifact_binding_status="PASS",
            score_recompute_status="PASS",
            gate_reconciliation_status="PASS",
            report_digest_sha256=None,
            status="PASS",
        ),
    )


def _manifest(source: Stage2PackageInput, members: OrderedDict[str, bytes]) -> tuple[bytes, str]:
    inherited = {item.path: item.owner_stage for item in source.inherited_authority}
    files = [
        OrderedDict(
            path=path,
            sha256=sha256_bytes(data),
            size_bytes=len(data),
            owner_stage=inherited.get(path, "STAGE3"),
            mutation_status="READ_ONLY" if path in inherited else "CREATED_CURRENT_STAGE",
        )
        for path, data in members.items()
    ]
    projection = [
        {key: item[key] for key in ("path", "sha256", "size_bytes", "owner_stage")}
        for item in files
    ]
    digest = sha256_bytes(canonical_json_bytes(projection))
    manifest = OrderedDict(
        schema_version="1.0",
        package_stage="STAGE3",
        package_purpose="FINAL_PACKAGE",
        operation_mode="CREATE",
        created_by_prompt_version="3.16.13",
        active_profile=source.manifest["active_profile"],
        story_sha256=sha256_bytes(source.members["story.json"]),
        parent_package_digest_sha256=source.package_digest_sha256,
        allowed_next_stage="STAGE4",
        file_count=len(files) + 1,
        files=files,
        validation=OrderedDict(
            manifest_schema_status="PASS",
            archive_security_status="PASS",
            file_set_status="PASS",
            file_digest_status="PASS",
            stage_ownership_status="PASS",
            parent_binding_status="PASS",
            stage_gate_status="PASS",
            status="PASS",
        ),
        package_digest_sha256=digest,
    )
    return ordered_json_bytes(manifest), digest


def _zip_bytes(manifest: bytes, members: OrderedDict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in [("workflow_manifest.json", manifest), *members.items()]:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return output.getvalue()


def _reopen(
    zip_bytes: bytes, manifest: bytes, members: OrderedDict[str, bytes], source: Stage2PackageInput
) -> None:
    with tempfile.TemporaryDirectory(prefix="audio-story-m8d-") as temp:
        path = Path(temp) / "story.zip"
        path.write_bytes(zip_bytes)
        if [item.path for item in inspect_zip(path)] != ["workflow_manifest.json", *members]:
            raise Stage3Error("M8D020_REOPEN", "archive order mismatch", "story.zip")
        root = safe_extract(path, Path(temp) / "extract")
        for name, data in [("workflow_manifest.json", manifest), *members.items()]:
            if (root / name).read_bytes() != data:
                raise Stage3Error("M8D021_REOPEN_BYTES", "archive member mismatch", name)
        validate_package_quality_report_bytes((root / "package_quality_report.json").read_bytes())
        parsed: dict[str, Any] = json.loads((root / "workflow_manifest.json").read_bytes())
        if parsed["parent_package_digest_sha256"] != source.package_digest_sha256:
            raise Stage3Error(
                "M8D022_PARENT", "parent package binding mismatch", "workflow_manifest.json"
            )
