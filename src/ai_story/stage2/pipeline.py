from __future__ import annotations

import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from ..archive import PackageBuilder, PackageVerifier, extract_inherited
from ..errors import WorkflowError
from ..hashing import sha256_file
from ..models import Operation, PackageResult, Profile, Stage
from ..provider_config import configure_job, generation_metadata, merge_generation_metadata
from ..providers import landscape_provider as configured_landscape_provider
from ..serial import validate_anchor
from ..validation_ledger import LEDGER_PATH, stage2_records, write_ledger
from ..workspace import RunWorkspace
from .config import resolve_image_mode
from .planning import create_visual_bible, create_visual_plan, finalize_documents
from .providers import LandscapeProvider
from .transactions import LandscapeCommit, LandscapeTransactionManager
from .validation import validate_stage1_source, validate_stage2_documents


@dataclass(frozen=True)
class Stage2Request:
    input_package: Path
    requested_mode: str = "ZONE"
    operation: Operation = Operation.CREATE
    allow_blocked_fixture_for_testing: bool = False


@dataclass(frozen=True)
class Stage2Result:
    run_id: str
    visual_plan_path: str
    visual_bible_path: str
    committed_assets: int
    generation_calls: int
    package: PackageResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "visual_plan_path": self.visual_plan_path,
            "visual_bible_path": self.visual_bible_path,
            "committed_assets": self.committed_assets,
            "generation_calls": self.generation_calls,
            "package": self.package.to_dict(),
        }


class Stage2Pipeline:
    def __init__(
        self, landscape_provider: LandscapeProvider | None = None, provider_mode: str | None = None,
        model_overrides: dict[str, dict[str, Any]] | None = None,
        quality_preset: str | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> None:
        self._runtime_registry = None
        self._provider_mode = provider_mode
        self._provider_config = None
        if landscape_provider is None:
            landscape_provider, self._runtime_registry = configured_landscape_provider(provider_mode, model_overrides, quality_preset)
            self._provider_config = self._runtime_registry.config if self._runtime_registry else configure_job(provider_mode, model_overrides, quality_preset)
        self.landscape_provider = landscape_provider
        self.progress_callback = progress_callback

    def run(self, request: Stage2Request, workspace: RunWorkspace) -> Stage2Result:
        workspace.update_status("RUNNING", stage="STAGE2")
        try:
            result = self._run(request, workspace)
            workspace.update_status("SUCCEEDED", stage="STAGE2", output_package=result.package.archive_path)
            return result
        except Exception as exc:
            workspace.update_status("FAILED", stage="STAGE2", error=str(exc))
            raise
        finally:
            assessor = getattr(self.landscape_provider, "assessor", None)
            if assessor is not None:
                assessor.unload()
            unload = getattr(self.landscape_provider, "unload", None)
            if callable(unload):
                unload()
            if self._runtime_registry is not None:
                self._runtime_registry.close()

    def _run(self, request: Stage2Request, workspace: RunWorkspace) -> Stage2Result:
        if self._runtime_registry is not None:
            self._runtime_registry.telemetry = lambda event: workspace.log(
                "MODEL_RUNTIME_CALL", {key: value for key, value in event.items() if key != "event"}
            )
        if request.operation is not Operation.CREATE:
            raise WorkflowError("Stage 2 REPAIR is not enabled in this milestone")
        resolve_image_mode(request.requested_mode)
        source = PackageVerifier().verify(request.input_package)
        if source.package_stage != Stage.STAGE1.value:
            raise WorkflowError("Stage 2 CREATE requires an authoritative STAGE1 package")
        manifest = self._read_manifest(request.input_package)
        source_validation = manifest.get("validation", {})
        artifact_class = source_validation.get("artifact_class", "PRODUCTION_CANDIDATE")
        content_quality_status = source_validation.get("content_quality_status", "NOT_ASSESSED")
        if manifest.get("allowed_next_stage") != Stage.STAGE2.value:
            raise WorkflowError("Stage 1 package has no canonical Stage 2 transition")
        profile = Profile(manifest["active_profile"])
        checkpoint_path = workspace.root / "stage2_checkpoint.json"
        checkpoint = self._read_checkpoint(checkpoint_path)
        if checkpoint:
            parent_digest = str(checkpoint.get("source_package_digest", ""))
            if parent_digest != source.package_digest_sha256:
                raise WorkflowError("Stage 2 checkpoint belongs to a different source package")
        else:
            parent_digest = extract_inherited(request.input_package, workspace.work_dir)
        workspace.log("STAGE2_STARTED", {"source_package_digest": parent_digest, "mode": "ZONE"})

        story_path = workspace.work_dir / "story.json"
        report_path = workspace.work_dir / "story_validation.json"
        story = json.loads(story_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validate_stage1_source(story, report, profile.value, story_path)
        warnings = [gate for gate in report.get("gates", []) if gate.get("status") != "PASS"]
        if warnings:
            workspace.log("INHERITED_GATE_WARNINGS", {"count": len(warnings), "stage": "STAGE1"})

        plan = create_visual_plan(
            story, report, sha256_file(story_path), sha256_file(report_path)
        )
        series_anchor = None
        if profile is Profile.SERIAL_DETECTIVE:
            anchor_path = workspace.work_dir / "series_anchor.json"
            if not anchor_path.is_file():
                raise WorkflowError("Serial Stage 2 requires series_anchor.json")
            series_anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            validate_anchor(series_anchor)
            if story["meta"]["series"] != series_anchor["series"]["title"]:
                raise WorkflowError("Story series title differs from anchor")
            if int(story["meta"]["episode"]) != series_anchor["continuity"]["latest_episode"]:
                raise WorkflowError("Story episode differs from anchor latest episode")
        bible = create_visual_bible(story, sha256_file(story_path), profile, series_anchor)
        manager = LandscapeTransactionManager(self.landscape_provider)
        commits: dict[str, LandscapeCommit] = {}
        if checkpoint:
            for basename, value in checkpoint.get("commits", {}).items():
                commit = LandscapeCommit.from_dict(value)
                asset_path = workspace.work_dir / commit.path
                if asset_path.is_file() and sha256_file(asset_path) == commit.file_sha256:
                    commits[basename] = commit
                else:
                    workspace.log("LANDSCAPE_CHECKPOINT_INVALID", {"basename": basename})
        total_assets = len(plan["assets"])
        for asset in plan["assets"]:
            if asset["basename"] in commits:
                workspace.log("LANDSCAPE_RESUMED", {"basename": asset["basename"]})
                if self.progress_callback:
                    self.progress_callback(len(commits), total_assets, asset["basename"])
                continue
            commit = manager.execute(
                basename=asset["basename"], output_root=workspace.work_dir,
                story=story, visual_plan_asset=asset, visual_bible=bible,
            )
            commits[asset["basename"]] = commit
            workspace.log("LANDSCAPE_COMMITTED", {"basename": commit.basename, "transaction_id": commit.transaction_id, "call_count": commit.call_count})
            self._write_checkpoint(checkpoint_path, parent_digest, commits)
            if self.progress_callback:
                self.progress_callback(len(commits), total_assets, commit.basename)

        plan, bible = finalize_documents(plan, bible, commits)
        visual_plan_path = workspace.work_dir / "visual_plan.json"
        visual_bible_path = workspace.work_dir / "visual_bible.json"
        visual_plan_path.write_bytes(self._json_bytes(plan))
        visual_bible_path.write_bytes(self._json_bytes(bible))
        parsed_plan = json.loads(visual_plan_path.read_text(encoding="utf-8"))
        parsed_bible = json.loads(visual_bible_path.read_text(encoding="utf-8"))
        validate_stage2_documents(parsed_plan, parsed_bible, workspace.work_dir)
        write_ledger(
            workspace.work_dir / LEDGER_PATH,
            "STAGE2",
            stage2_records(parsed_plan),
        )

        package = PackageBuilder().build(
            source_dir=workspace.work_dir,
            output_path=workspace.output_dir / "story.zip",
            stage=Stage.STAGE2,
            operation=Operation.CREATE,
            profile=profile,
            parent_package_digest_sha256=parent_digest,
            source_stage=Stage.STAGE1,
            generation=merge_generation_metadata(
                manifest["generation"],
                generation_metadata(
                    [("landscape", self.landscape_provider.provider_id)],
                    "visual-plan/1.2",
                    self._provider_mode,
                    self._provider_config,
                    self._runtime_registry.metrics() if self._runtime_registry else None,
                ),
            ),
            allow_next_stage=True,
            artifact_class=artifact_class,
            content_quality_status=content_quality_status,
        )
        calls = sum(commit.call_count for commit in commits.values())
        checkpoint_path.unlink(missing_ok=True)
        workspace.log("STAGE2_COMPLETED", package.to_dict())
        return Stage2Result(
            workspace.run_id, str(visual_plan_path), str(visual_bible_path),
            len(commits), calls, package,
        )

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        with zipfile.ZipFile(path, "r") as archive:
            return json.loads(archive.read("workflow_manifest.json").decode("utf-8"))

    @staticmethod
    def _json_bytes(value: dict[str, Any]) -> bytes:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _read_checkpoint(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"Stage 2 checkpoint cannot be read: {exc}") from exc
        if value.get("schema_version") != "1.0" or not isinstance(value.get("commits"), dict):
            raise WorkflowError("Stage 2 checkpoint shape is invalid")
        return value

    @classmethod
    def _write_checkpoint(
        cls, path: Path, source_package_digest: str, commits: dict[str, LandscapeCommit]
    ) -> None:
        value = {
            "schema_version": "1.0",
            "source_package_digest": source_package_digest,
            "commits": {name: asdict(commit) for name, commit in commits.items()},
        }
        temporary = path.with_suffix(".json.tmp")
        temporary.write_bytes(cls._json_bytes(value))
        temporary.replace(path)
