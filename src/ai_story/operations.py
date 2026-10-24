from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .archive import PackageBuilder, PackageVerifier, extract_inherited
from .artifacts import artifact_owner
from .errors import WorkflowError
from .hashing import sha256_file
from .models import Operation, PackageResult, Profile, Stage
from .workspace import RunWorkspace


@dataclass(frozen=True)
class RepairResult:
    changed_paths: list[str]
    package: PackageResult


class PackageRepairSession:
    """Rebuilds a same-stage package while enforcing artifact ownership."""

    def run(
        self,
        *,
        input_package: Path,
        workspace: RunWorkspace,
        mutate: Callable[[Path], None],
    ) -> RepairResult:
        source = PackageVerifier().verify(input_package)
        stage = Stage(source.package_stage)
        source_manifest = self._manifest(input_package)
        profile = Profile(source_manifest["active_profile"])
        parent_digest = extract_inherited(input_package, workspace.work_dir)
        before = self._hashes(workspace.work_dir)
        mutate(workspace.work_dir)
        after = self._hashes(workspace.work_dir)
        changed = sorted(
            path for path in set(before) | set(after) if before.get(path) != after.get(path)
        )
        if not changed:
            raise WorkflowError("Repair operation did not change any artifact")
        for path in changed:
            if path not in after:
                raise WorkflowError(f"Repair may not remove a canonical artifact: {path}")
            if artifact_owner(path) != stage.value:
                raise WorkflowError(f"Repair cannot modify inherited artifact {path}")
        package = PackageBuilder().build(
            source_dir=workspace.work_dir,
            output_path=workspace.output_dir / "story.zip",
            stage=stage,
            operation=Operation.REPAIR,
            profile=profile,
            parent_package_digest_sha256=parent_digest,
            source_stage=stage,
            generation=source_manifest.get("generation"),
            allow_next_stage=source_manifest.get("allowed_next_stage") is not None,
            artifact_class=source_manifest.get("validation", {}).get(
                "artifact_class", "PRODUCTION_CANDIDATE"
            ),
            content_quality_status=source_manifest.get("validation", {}).get(
                "content_quality_status", "NOT_ASSESSED"
            ),
        )
        workspace.log("PACKAGE_REPAIRED", {"stage": stage.value, "changed_paths": changed})
        return RepairResult(changed, package)

    @staticmethod
    def _hashes(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): sha256_file(path)
            for path in root.rglob("*") if path.is_file()
        }

    @staticmethod
    def _manifest(package: Path) -> dict[str, Any]:
        import zipfile

        with zipfile.ZipFile(package, "r") as archive:
            return json.loads(archive.read("workflow_manifest.json").decode("utf-8"))


class RunIndex:
    def list_runs(self, root: Path) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        runs = []
        for metadata_path in sorted(root.glob("*/run.json")):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            events_path = metadata_path.parent / "logs" / "events.ndjson"
            events = []
            if events_path.is_file():
                for line in events_path.read_text(encoding="utf-8").splitlines():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            metadata["event_count"] = len(events)
            metadata["last_event"] = events[-1]["event"] if events else None
            metadata["last_event_at"] = events[-1]["timestamp"] if events else None
            metadata["output_package"] = str(metadata_path.parent / "output" / "story.zip") if (metadata_path.parent / "output" / "story.zip").is_file() else None
            runs.append(metadata)
        return runs
