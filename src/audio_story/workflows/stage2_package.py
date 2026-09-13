"""Deterministic, gate-first Stage 2 story.zip checkpoint publication."""

from __future__ import annotations

import json
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

from audio_story.domain.stage2 import Stage1PackageInput, Stage2Error, Stage2ZonePlan, ZONE_IMAGE_BASENAMES
from audio_story.validation.archives import inspect_zip, safe_extract
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage1 import ordered_json_bytes
from audio_story.workflows.stage2_commitment import validate_stage2_commitments
from audio_story.workflows.stage2_gates import Stage2GateResult, require_stage2_gate_pass
from audio_story.workflows.kernel import WorkflowKernel


def build_stage2_checkpoint(
    kernel: WorkflowKernel,
    stage_id: str,
    source: Stage1PackageInput,
    plan: Stage2ZonePlan,
    gate_result: Stage2GateResult,
    output_path: Path,
) -> str:
    """Publish a self-contained Stage 2 checkpoint only after all gates pass."""
    require_stage2_gate_pass(gate_result)
    if gate_result.semantic_pass_count != len(ZONE_IMAGE_BASENAMES):
        raise Stage2Error("M7D001_GATE", "all landscape semantic gates are required", "STAGE2_PACKAGE_GATE")
    rows = kernel.db.connection.execute(
        "SELECT t.basename,t.id transaction_id,b.artifact_id,a.sha256,a.relative_path "
        "FROM asset_transactions t JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
        "JOIN artifacts a ON a.id=b.artifact_id WHERE t.stage_run_id=? AND t.orientation='LANDSCAPE'",
        (stage_id,),
    ).fetchall()
    by_name = {str(row["basename"]): row for row in rows}
    landscapes: OrderedDict[str, bytes] = OrderedDict()
    for basename in ZONE_IMAGE_BASENAMES:
        row = by_name.get(basename)
        if row is None:
            raise Stage2Error("M7D002_FILE_SET", "landscape is missing", basename)
        data = kernel.store.read(str(row["relative_path"]))
        validate_stage2_commitments(data, basename, str(row["transaction_id"]))
        if sha256_bytes(data) != str(row["sha256"]):
            raise Stage2Error("M7D003_DIGEST", "artifact bytes changed", basename)
        landscapes[f"landscape/{basename}"] = data
    members: OrderedDict[str, bytes] = OrderedDict()
    members["story.json"] = source.story_bytes
    members["story_validation.json"] = source.story_validation_bytes
    members["visual_plan.json"] = plan.visual_plan_bytes
    members["visual_bible.json"] = plan.visual_bible_bytes
    for path, data in source.character_assets.items():
        members[path] = data
    members.update(landscapes)
    if source.series_anchor_bytes is not None:
        members["series_anchor.json"] = source.series_anchor_bytes
    manifest = _build_manifest(source, members)
    digest = _write_zip(output_path, manifest, members)
    _reopen_checkpoint(output_path, manifest, members)
    return digest


def _write_zip(path: Path, manifest: bytes, members: OrderedDict[str, bytes]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in [("workflow_manifest.json", manifest), *members.items()]:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return sha256_bytes(path.read_bytes())


def _build_manifest(source: Stage1PackageInput, members: OrderedDict[str, bytes]) -> bytes:
    files = [OrderedDict(path=path, sha256=sha256_bytes(data), size_bytes=len(data), owner_stage=("STAGE2" if path.startswith(("landscape/", "visual_")) else "STAGE1"), mutation_status=("CREATED_CURRENT_STAGE" if path.startswith(("landscape/", "visual_")) else "READ_ONLY")) for path, data in members.items()]
    projection = [{key: item[key] for key in ("path", "sha256", "size_bytes", "owner_stage")} for item in files]
    manifest = OrderedDict(schema_version="1.0", package_stage="STAGE2", package_purpose="WORKFLOW_CHECKPOINT", operation_mode="CREATE", created_by_prompt_version="3.16.13", active_profile=source.manifest["active_profile"], story_sha256=sha256_bytes(source.story_bytes), parent_package_digest_sha256=source.package_digest_sha256, allowed_next_stage="STAGE3", file_count=1 + len(files), files=files, validation=OrderedDict(manifest_schema_status="PASS", archive_security_status="PASS", file_set_status="PASS", file_digest_status="PASS", stage_ownership_status="PASS", parent_binding_status="PASS", stage_gate_status="PASS", status="PASS"), package_digest_sha256=sha256_bytes(canonical_json_bytes(projection)))
    return ordered_json_bytes(manifest)


def _reopen_checkpoint(path: Path, manifest: bytes, members: OrderedDict[str, bytes]) -> None:
    actual = [item.path for item in inspect_zip(path)]
    expected = ["workflow_manifest.json", *members]
    if actual != expected:
        raise Stage2Error("M7D004_REOPEN", "archive order or file set mismatch", "story.zip")
    import tempfile
    with tempfile.TemporaryDirectory(prefix="audio-story-m7d-") as temp:
        root = safe_extract(path, Path(temp))
        for name, data in [("workflow_manifest.json", manifest), *members.items()]:
            if (root / name).read_bytes() != data:
                raise Stage2Error("M7D005_REOPEN", "archive bytes mismatch", name)
    parsed: Any = json.loads(manifest)
    if parsed["package_stage"] != "STAGE2" or parsed["parent_package_digest_sha256"] is None:
        raise Stage2Error("M7D006_MANIFEST", "invalid Stage 2 parent binding", "workflow_manifest.json")
