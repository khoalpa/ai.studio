from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..archive import PackageBuilder, PackageVerifier, extract_inherited
from ..errors import WorkflowError
from ..hashing import sha256_file
from ..models import Operation, PackageResult, Profile, Stage
from ..provider_config import configure_job, generation_metadata, merge_generation_metadata
from ..providers import portrait_provider as configured_portrait_provider
from ..stage2.validation import validate_stage2_documents
from ..validation_ledger import LEDGER_PATH, stage3_records, write_ledger
from ..workspace import RunWorkspace
from .providers import PortraitProvider
from .report import build_quality_report
from .transactions import PortraitTransactionManager
from .validation import validate_portrait_set, validate_quality_report


@dataclass(frozen=True)
class Stage3Request:
    input_package: Path
    operation: Operation = Operation.CREATE
    allow_blocked_fixture_for_testing: bool = False


@dataclass(frozen=True)
class Stage3Result:
    run_id: str
    quality_report_path: str
    committed_assets: int
    generation_calls: int
    package: PackageResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "quality_report_path": self.quality_report_path,
            "committed_assets": self.committed_assets,
            "generation_calls": self.generation_calls,
            "package": self.package.to_dict(),
        }


class Stage3Pipeline:
    def __init__(
        self, portrait_provider: PortraitProvider | None = None, provider_mode: str | None = None,
        model_overrides: dict[str, dict[str, Any]] | None = None,
        quality_preset: str | None = None,
    ) -> None:
        self._runtime_registry = None
        self._provider_mode = provider_mode
        self._provider_config = None
        if portrait_provider is None:
            portrait_provider, self._runtime_registry = configured_portrait_provider(provider_mode, model_overrides, quality_preset)
            self._provider_config = self._runtime_registry.config if self._runtime_registry else configure_job(provider_mode, model_overrides, quality_preset)
        self.portrait_provider = portrait_provider

    def run(self, request: Stage3Request, workspace: RunWorkspace) -> Stage3Result:
        try:
            return self._run(request, workspace)
        finally:
            assessor = getattr(self.portrait_provider, "assessor", None)
            if assessor is not None:
                assessor.unload()
            if self._runtime_registry is not None:
                self._runtime_registry.close()

    def _run(self, request: Stage3Request, workspace: RunWorkspace) -> Stage3Result:
        if self._runtime_registry is not None:
            self._runtime_registry.telemetry = lambda event: workspace.log(
                "MODEL_RUNTIME_CALL", {key: value for key, value in event.items() if key != "event"}
            )
        if request.operation is not Operation.CREATE:
            raise WorkflowError("Stage 3 REPAIR is not enabled in this milestone")
        source = PackageVerifier().verify(request.input_package)
        if source.package_stage != Stage.STAGE2.value:
            raise WorkflowError("Stage 3 CREATE requires an authoritative STAGE2 package")
        manifest = self._read_manifest(request.input_package)
        if manifest.get("allowed_next_stage") != Stage.STAGE3.value:
            raise WorkflowError("Stage 2 package has no canonical Stage 3 transition")
        source_validation = manifest.get("validation", {})
        artifact_class = source_validation.get("artifact_class", "PRODUCTION_CANDIDATE")
        content_quality_status = source_validation.get("content_quality_status", "NOT_ASSESSED")
        profile = Profile(manifest["active_profile"])
        parent_digest = extract_inherited(request.input_package, workspace.work_dir)
        workspace.log("STAGE3_STARTED", {"source_package_digest": parent_digest})

        plan_path = workspace.work_dir / "visual_plan.json"
        bible_path = workspace.work_dir / "visual_bible.json"
        plan_hash_before = sha256_file(plan_path)
        bible_hash_before = sha256_file(bible_path)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        bible = json.loads(bible_path.read_text(encoding="utf-8"))
        validate_stage2_documents(plan, bible, workspace.work_dir)

        manager = PortraitTransactionManager(self.portrait_provider)
        commits = {}
        for asset in plan["assets"]:
            basename = asset["basename"]
            commit = manager.execute(
                basename=basename,
                landscape_path=workspace.work_dir / "landscape" / basename,
                output_root=workspace.work_dir,
                visual_plan_asset=asset,
                visual_bible=bible,
            )
            commits[basename] = commit
            workspace.log("PORTRAIT_COMMITTED", {"basename": basename, "transaction_id": commit.transaction_id, "call_count": commit.call_count})
        if sha256_file(plan_path) != plan_hash_before or sha256_file(bible_path) != bible_hash_before:
            raise WorkflowError("Stage 3 modified inherited Visual Plan or Visual Bible")
        validate_portrait_set(workspace.work_dir, plan, commits)

        report = build_quality_report(
            root=workspace.work_dir,
            profile=profile.value,
            source_package_digest=parent_digest,
            plan=plan,
            commits=commits,
        )
        report_path = workspace.work_dir / "package_quality_report.json"
        report_path.write_bytes(self._json_bytes(report))
        parsed_report = json.loads(report_path.read_text(encoding="utf-8"))
        if not request.allow_blocked_fixture_for_testing:
            validate_quality_report(parsed_report, workspace.work_dir)
        write_ledger(
            workspace.work_dir / LEDGER_PATH,
            "STAGE3",
            stage3_records(parsed_report),
        )

        package = PackageBuilder().build(
            source_dir=workspace.work_dir,
            output_path=workspace.output_dir / "story.zip",
            stage=Stage.STAGE3,
            operation=Operation.CREATE,
            profile=profile,
            parent_package_digest_sha256=parent_digest,
            source_stage=Stage.STAGE2,
            generation=merge_generation_metadata(
                manifest["generation"],
                generation_metadata(
                    [("portrait", self.portrait_provider.provider_id)],
                    "portrait-transform/1.2",
                    self._provider_mode,
                    self._provider_config,
                    self._runtime_registry.metrics() if self._runtime_registry else None,
                ),
            ),
            allow_next_stage=True,
            artifact_class=artifact_class,
            content_quality_status=content_quality_status,
        )
        calls = sum(item.call_count for item in commits.values())
        workspace.log("STAGE3_COMPLETED", package.to_dict())
        return Stage3Result(
            workspace.run_id, str(report_path), len(commits), calls, package
        )

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        with zipfile.ZipFile(path, "r") as archive:
            return json.loads(archive.read("workflow_manifest.json").decode("utf-8"))

    @staticmethod
    def _json_bytes(value: dict[str, Any]) -> bytes:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
