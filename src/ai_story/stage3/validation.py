from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import WorkflowError
from ..hashing import sha256_file
from ..stage1.png import png_dimensions
from ..stage2.config import basenames
from .config import stage3_config
from .report import REPORT_FIELDS, report_digest
from .transactions import PortraitCommit


def validate_portrait_set(root: Path, plan: dict[str, Any], commits: dict[str, PortraitCommit]) -> None:
    expected = basenames()
    if [item["basename"] for item in plan["assets"]] != expected:
        raise WorkflowError("Portrait source order differs from Visual Plan")
    if list(commits) != expected:
        raise WorkflowError("Portrait commits do not match the canonical basename order")
    size = [stage3_config()["portrait"]["width"], stage3_config()["portrait"]["height"]]
    for basename in expected:
        commit = commits[basename]
        portrait = root / commit.path
        landscape = root / "landscape" / basename
        if not portrait.is_file() or not landscape.is_file():
            raise WorkflowError(f"Cross-orientation pair is incomplete: {basename}")
        if sha256_file(portrait) != commit.file_sha256:
            raise WorkflowError(f"Portrait hash mismatch: {basename}")
        if sha256_file(landscape) != commit.source_landscape_sha256:
            raise WorkflowError(f"Landscape source hash mismatch: {basename}")
        if list(png_dimensions(portrait.read_bytes())) != size:
            raise WorkflowError(f"Portrait dimensions invalid: {basename}")
        if commit.parity_status != "ASSESSED_PASS":
            raise WorkflowError(f"Cross-orientation parity failed: {basename}")
        if commit.quality_assessment.get("status") not in {"PASS", "ASSESSED_PASS"}:
            raise WorkflowError(f"Portrait quality assessment failed: {basename}")
        transform = commit.quality_assessment.get("portrait_transform", {})
        if transform.get("mode") not in {"OUTPAINT", "RECOMPOSE_IMG2IMG", "FIXTURE_DIRECT"}:
            raise WorkflowError(f"Portrait transform evidence is invalid: {basename}")
        if basename == "cover.png" and not transform.get("title_safe_area_reserved"):
            raise WorkflowError("Portrait cover did not reserve its title-safe area")
        upscale = commit.quality_assessment.get("upscale_postprocess", {})
        if upscale.get("mode") not in {
            "LATENT_X2_PLUS_RESIDUAL", "LANCZOS_FALLBACK", "FIXTURE_DIRECT"
        } or upscale.get("output_size") != size:
            raise WorkflowError(f"Portrait upscale evidence is invalid: {basename}")
        layers = commit.quality_assessment.get("qa_layers")
        if not isinstance(layers, list) or not layers:
            raise WorkflowError(f"Portrait layered QA evidence is missing: {basename}")


def validate_quality_report(report: dict[str, Any], root: Path) -> None:
    if list(report) != REPORT_FIELDS:
        raise WorkflowError("Package quality report root shape is invalid")
    if report["schema_version"] != stage3_config()["package_quality_report_schema_version"]:
        raise WorkflowError("Package quality report schema version is invalid")
    if report["validation"]["report_digest_sha256"] != report_digest(report):
        raise WorkflowError("Package quality report digest mismatch")
    # Publish findings are preserved in the report but do not invalidate its
    # structure or prevent the workflow from continuing.
    if report["package_identity"]["story_sha256"] != sha256_file(root / "story.json"):
        raise WorkflowError("Package quality report story binding mismatch")
    if len(report["measurement_ledger"]) != 10:
        raise WorkflowError("Package quality measurement ledger must contain ten portrait commits")
