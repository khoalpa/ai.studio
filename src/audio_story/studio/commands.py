"""Bounded background commands owned by the local Studio process."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import sys
import threading
import uuid
import zipfile
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from queue import Queue
from typing import Any

from audio_story.adapters.image import (
    ComfyUIConfig,
    ComfyUIImageAdapter,
    DeterministicMockImageAdapter,
    LocalImageAdapter,
)
from audio_story.adapters.llm.base import LocalLLMAdapter
from audio_story.adapters.llm.mock import DeterministicMockAdapter
from audio_story.adapters.video.ffmpeg import FFmpegAdapter, FFmpegConfig
from audio_story.backup import create_backup
from audio_story.domain.stage1 import Stage1Error, Stage1Request, resolve_profile
from audio_story.domain.stage2 import Stage2Error
from audio_story.domain.stage3 import Stage3Error
from audio_story.domain.state import StageStatus, WorkflowStatus
from audio_story.studio.vlm import LocalQwenVlmAssessor, VlmAssessmentError
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage2 import load_stage1_package
from audio_story.validation.stage3 import load_stage2_package
from audio_story.validation.stage4 import load_stage3_package
from audio_story.validation.video_studio import load_stage4_video_input
from audio_story.workflows import KernelError, Stage1Service, WorkflowKernel
from audio_story.workflows.image_transaction import SemanticImageGateResult
from audio_story.workflows.kernel import utc_now
from audio_story.workflows.stage1_characters import CharacterImageConfig
from audio_story.workflows.stage1_materialization import StoryQualityResult
from audio_story.workflows.stage2_execution import Stage2ZoneExecutor
from audio_story.workflows.stage2_gates import (
    SemanticAssessment,
    evaluate_stage2_landscape_gates,
)
from audio_story.workflows.stage2_package import build_stage2_checkpoint
from audio_story.workflows.stage2_planning import build_stage2_zone_plan
from audio_story.workflows.stage3_execution import Stage3PortraitExecutor
from audio_story.workflows.stage3_package import build_stage3_package, write_stage3_package
from audio_story.workflows.stage3_planning import build_stage3_portrait_plan
from audio_story.workflows.stage4_package import build_stage4_package, write_stage4_package
from audio_story.workflows.stage4_planning import build_video_prompts, resolve_stage4_config
from audio_story.workflows.video_studio import derive_srt_bytes, render_video


class StudioCommandError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(slots=True)
class StudioJob:
    id: str
    kind: str
    status: str
    profile: str
    language: str
    duration_minutes: int
    seed: int
    title: str
    workflow_id: str | None = None
    stage_id: str | None = None
    package_path: str | None = None
    package_digest: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    source_package: str | None = None
    execution_mode: str | None = None
    committed_count: int = 0
    required_count: int = 0
    next_pending_basename: str | None = None


@dataclass(frozen=True, slots=True)
class _QueuedStage1:
    job_id: str
    request: Stage1Request
    resume: bool = False


@dataclass(frozen=True, slots=True)
class _QueuedStage2:
    job_id: str
    source_package: Path
    execution_mode: str


@dataclass(frozen=True, slots=True)
class _QueuedVlmReview:
    job_id: str


@dataclass(frozen=True, slots=True)
class _QueuedStage3:
    job_id: str
    source_package: Path
    execution_mode: str


@dataclass(frozen=True, slots=True)
class _QueuedStage4:
    job_id: str
    source_package: Path


class StudioCommandRunner:
    """Run one local Stage 1 command at a time outside the HTTP loop."""

    def __init__(
        self,
        workspace: Path,
        canonical_path: Path,
        *,
        comfyui_endpoint: str = "http://127.0.0.1:8188",
        comfyui_workflow_path: Path | None = None,
        qwen_model_path: Path | None = None,
        qwen_runner_path: Path | None = None,
        ffmpeg_path: Path | None = None,
        ffprobe_path: Path | None = None,
        stage1_adapter: LocalLLMAdapter | None = None,
        stage1_test_mode: bool = True,
        stage1_character_image_config: CharacterImageConfig | None = None,
        stage1_story_quality_assessor: Callable[
            [bytes, OrderedDict[str, bytes]], StoryQualityResult
        ]
        | None = None,
        stage4_prompt_assessor: Callable[[bytes], None] | None = None,
    ) -> None:
        self._workspace = workspace.resolve()
        self._canonical_path = canonical_path.resolve()
        self._jobs: dict[str, StudioJob] = {}
        self._stage1_requests: dict[str, Stage1Request] = {}
        self._cancellations: dict[str, threading.Event] = {}
        self._semantic_assessments: dict[str, dict[str, SemanticAssessment]] = {}
        self._lock = threading.Lock()
        self._comfyui_endpoint = comfyui_endpoint
        self._comfyui_workflow_path = comfyui_workflow_path
        self._qwen_model_path = qwen_model_path
        self._qwen_runner_path = qwen_runner_path
        self._ffmpeg_path, self._ffprobe_path = ffmpeg_path, ffprobe_path
        self._stage1_adapter = stage1_adapter or DeterministicMockAdapter()
        self._stage1_test_mode = stage1_test_mode
        self._stage1_character_image_config = stage1_character_image_config
        self._stage1_story_quality_assessor = stage1_story_quality_assessor
        self._stage4_prompt_assessor = stage4_prompt_assessor
        self._queue: Queue[
            _QueuedStage1 | _QueuedStage2 | _QueuedVlmReview | _QueuedStage3 | _QueuedStage4 | None
        ] = Queue()
        self._restore_stage2_jobs()
        self._thread = threading.Thread(
            target=self._worker,
            name="audio-story-studio-runner",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)

    @property
    def worker_alive(self) -> bool:
        return self._thread.is_alive()

    def _require_worker(self) -> None:
        if not self.worker_alive:
            raise StudioCommandError(
                "UI198_WORKER_UNAVAILABLE", "Studio background worker is not running"
            )

    def ensure_workspace_can_be_deleted(self) -> None:
        """Reject deletion while a background job could still write to disk."""
        with self._lock:
            active = [
                job.id
                for job in self._jobs.values()
                if job.status in {"QUEUED", "QUEUED_VLM_REVIEW", "RUNNING", "CANCELLING"}
            ]
        if active:
            raise StudioCommandError(
                "UI115_WORKSPACE_BUSY",
                "cannot delete the workspace while a job is running",
            )

    def delete_story(self, workflow_id: str) -> dict[str, Any]:
        self.ensure_workspace_can_be_deleted()
        kernel = WorkflowKernel(self._workspace)
        try:
            paths = kernel.delete_workflow(workflow_id)
        except KernelError as exc:
            raise StudioCommandError("UI117_STORY_NOT_FOUND", str(exc)) from exc
        finally:
            kernel.close()
        for relative in paths:
            path = (self._workspace / relative).resolve()
            if self._workspace in path.parents and path.is_file():
                path.unlink()
        output = self._workspace / "outputs" / workflow_id
        if output.is_dir():
            shutil.rmtree(output)
        return {"workflow_id": workflow_id, "deleted": True}

    def submit_stage1(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_worker()
        request = self._stage1_request(payload)
        job = StudioJob(
            id=uuid.uuid4().hex,
            kind="STAGE1_CREATE",
            status="QUEUED",
            profile=str(request.profile),
            language=request.language,
            duration_minutes=int(request.duration_minutes or 0),
            seed=request.seed,
            title=request.title,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._stage1_requests[job.id] = request
            self._cancellations[job.id] = threading.Event()
        self._queue.put(_QueuedStage1(job.id, request))
        return asdict(job)

    def import_story_package(self, data: bytes, filename: str) -> dict[str, Any]:
        if not filename.lower().endswith(".zip"):
            raise StudioCommandError("UI120_STORY_ZIP_REQUIRED", "story package must be a ZIP")
        if not data:
            raise StudioCommandError("UI121_EMPTY_STORY_PACKAGE", "story package is empty")
        digest = sha256_bytes(data)
        import_root = self._workspace / "imports" / digest
        package = import_root / "story.zip"
        import_root.mkdir(parents=True, exist_ok=True)
        candidate = import_root / ".story.zip.pending"
        candidate.write_bytes(data)
        try:
            try:
                with zipfile.ZipFile(candidate) as archive:
                    manifest = json.loads(archive.read("workflow_manifest.json"))
            except (OSError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
                raise StudioCommandError(
                    "UI122_INVALID_STORY_PACKAGE", "missing or malformed workflow manifest"
                ) from exc
            stage = manifest.get("package_stage", "STAGE1")
            try:
                if stage == "STAGE1":
                    load_stage1_package(candidate)
                    kind = "STAGE1_CREATE"
                elif stage == "STAGE2":
                    load_stage2_package(candidate)
                    kind = "STAGE2_CREATE"
                elif stage == "STAGE3":
                    load_stage3_package(candidate)
                    kind = "STAGE3_CREATE"
                else:
                    raise StudioCommandError(
                        "UI123_UNSUPPORTED_STORY_STAGE",
                        f"unsupported story package stage: {stage}",
                    )
            except (Stage1Error, Stage2Error, Stage3Error, OSError, ValueError) as exc:
                raise StudioCommandError(
                    "UI126_STORY_VALIDATION_FAILED", f"story package failed validation: {exc}"
                ) from exc
            if package.exists() and package.read_bytes() != data:
                raise StudioCommandError("UI124_IMPORT_CONFLICT", "import digest path conflicts")
            candidate.replace(package)
            job = StudioJob(
                id=f"import-{digest[:16]}",
                kind=kind,
                status="PASS",
                profile=str(manifest.get("active_profile", "IMPORTED")),
                language="FROM_PACKAGE",
                duration_minutes=0,
                seed=0,
                title=filename,
                package_path=str(package),
                package_digest=digest,
                execution_mode="IMPORTED",
            )
            with self._lock:
                self._jobs[job.id] = job
                self._cancellations[job.id] = threading.Event()
            return {**asdict(job), "package_stage": stage}
        finally:
            candidate.unlink(missing_ok=True)

    def submit_stage2(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"source_package", "execution_mode"}
        if set(payload) - allowed:
            raise StudioCommandError("UI103_UNKNOWN_FIELD", "request has unknown fields")
        mode = payload.get("execution_mode", "COMFYUI")
        if mode not in {"MOCK", "COMFYUI"}:
            raise StudioCommandError("UI104_INVALID_REQUEST", "invalid Stage 2 execution mode")
        source_value = payload.get("source_package")
        if source_value is None:
            source_value = self._latest_stage1_package()
        if not isinstance(source_value, str) or not source_value:
            raise StudioCommandError(
                "UI110_STAGE1_PACKAGE_REQUIRED", "a published Stage 1 package is required"
            )
        source = Path(source_value).resolve()
        if self._workspace not in source.parents or not source.is_file():
            raise StudioCommandError(
                "UI111_STAGE1_PACKAGE_INVALID",
                "Stage 1 package must be a file inside the selected workspace",
            )
        if mode == "COMFYUI" and (
            self._comfyui_workflow_path is None or not self._comfyui_workflow_path.is_file()
        ):
            raise StudioCommandError(
                "UI112_COMFYUI_WORKFLOW_MISSING", "configured ComfyUI workflow is unavailable"
            )
        job = StudioJob(
            id=uuid.uuid4().hex,
            kind="STAGE2_CREATE",
            status="QUEUED",
            profile="FROM_STAGE1",
            language="FROM_STAGE1",
            duration_minutes=0,
            seed=0,
            title="Stage 2 · Visual Bible",
            source_package=str(source),
            execution_mode=str(mode),
            required_count=10,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._cancellations[job.id] = threading.Event()
        self._queue.put(_QueuedStage2(job.id, source, str(mode)))
        return asdict(job)

    def submit_stage3(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:  # pragma: no cover - runtime integration
        if set(payload) - {"source_package", "execution_mode"}:
            raise StudioCommandError("UI103_UNKNOWN_FIELD", "request has unknown fields")
        source_value = payload.get("source_package") or self._latest_stage2_package()
        if not isinstance(source_value, str) or not source_value:
            raise StudioCommandError(
                "UI117_STAGE2_PACKAGE_REQUIRED", "a PASS Stage 2 package is required"
            )
        source = Path(source_value).resolve()
        if self._workspace not in source.parents or not source.is_file():
            raise StudioCommandError(
                "UI111_STAGE2_PACKAGE_INVALID", "Stage 2 package must be inside workspace"
            )
        mode = payload.get("execution_mode", "VLM_LOCAL")
        if mode not in {"MOCK", "VLM_LOCAL"}:
            raise StudioCommandError("UI104_INVALID_REQUEST", "invalid Stage 3 execution mode")
        if mode == "VLM_LOCAL" and (
            self._qwen_model_path is None or self._qwen_runner_path is None
        ):
            raise StudioCommandError("VLM001_LOCAL_RUNTIME_MISSING", "local VLM is not configured")
        job = StudioJob(
            uuid.uuid4().hex,
            "STAGE3_CREATE",
            "QUEUED",
            "FROM_STAGE2",
            "FROM_STAGE2",
            0,
            0,
            "Stage 3 · Portrait Runner",
            source_package=str(source),
            execution_mode=str(mode),
            required_count=10,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._cancellations[job.id] = threading.Event()
        self._queue.put(_QueuedStage3(job.id, source, str(mode)))
        return asdict(job)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(job) for job in reversed(tuple(self._jobs.values()))]

    def release_readiness(self) -> dict[str, Any]:
        blockers: list[str] = []
        canonical = hashlib.sha256(self._canonical_path.read_bytes()).hexdigest()
        if canonical != "4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27":
            blockers.append("M22_CANONICAL_DIGEST")
        kernel = WorkflowKernel(self._workspace)
        try:
            integrity = str(
                kernel.db.connection.execute("PRAGMA integrity_check").fetchone()[0]
            ).upper()
            if integrity != "OK":
                blockers.append("M22_SQLITE_INTEGRITY")
            with self._lock:
                final = next(
                    (
                        job
                        for job in self._jobs.values()
                        if job.kind == "STAGE4_CREATE" and job.status == "PASS"
                    ),
                    None,
                )
            if final is None or not final.package_path or not Path(final.package_path).is_file():
                blockers.append("M22_STAGE4_OUTPUT_MISSING")
            output_digest = (
                hashlib.sha256(Path(final.package_path).read_bytes()).hexdigest()
                if final and final.package_path
                else None
            )
            return {
                "status": "PASS" if not blockers else "BLOCKED",
                "blockers": blockers,
                "canonical_sha256": canonical,
                "sqlite_integrity": integrity,
                "stage4_output": final.package_path if final else None,
                "stage4_output_sha256": output_digest,
            }
        finally:
            kernel.close()

    def diagnostics(self) -> dict[str, Any]:  # pragma: no cover - diagnostics integration
        kernel = WorkflowKernel(self._workspace)
        try:
            integrity = str(
                kernel.db.connection.execute("PRAGMA integrity_check").fetchone()[0]
            ).upper()
            with self._lock:
                jobs = list(self._jobs.values())
            counts: dict[str, int] = {}
            for job in jobs:
                counts[job.status] = counts.get(job.status, 0) + 1
            disk = shutil.disk_usage(self._workspace)
            return {
                "status": "PASS" if integrity == "OK" else "FAIL",
                "workspace": str(self._workspace),
                "runtime": {"python": sys.version.split()[0], "platform": platform.platform()},
                "sqlite": {"integrity": integrity, "journal_mode": "WAL"},
                "jobs": {
                    "total": len(jobs),
                    "by_status": counts,
                    "worker_alive": self.worker_alive,
                },
                "dependencies": {
                    "ffmpeg": shutil.which("ffmpeg") is not None,
                    "ffprobe": shutil.which("ffprobe") is not None,
                    "qwen_model": self._qwen_model_path is not None
                    and self._qwen_model_path.is_dir(),
                },
                "disk": {"free_bytes": disk.free, "total_bytes": disk.total},
            }
        finally:
            kernel.close()

    def create_workspace_backup(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:  # pragma: no cover
        if set(payload) - {"mode"}:
            raise StudioCommandError("UI103_UNKNOWN_FIELD", "request has unknown fields")
        mode = payload.get("mode", "STATE_ONLY")
        if mode not in {"FULL", "STATE_ONLY"}:
            raise StudioCommandError("UI104_INVALID_REQUEST", "backup mode is invalid")
        output = self._workspace / "backups" / f"studio-{uuid.uuid4().hex}.zip"
        result = create_backup(self._workspace, output, mode=mode)
        return {
            "path": str(result.path),
            "sha256": result.sha256,
            "content_digest": result.content_digest,
            "member_count": result.member_count,
            "mode": result.mode,
        }

    def submit_stage4(self, payload: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        if set(payload) - {"source_package"}:
            raise StudioCommandError("UI103_UNKNOWN_FIELD", "request has unknown fields")
        source_value = payload.get("source_package") or self._latest_stage3_package()
        if not isinstance(source_value, str) or not source_value:
            raise StudioCommandError(
                "UI119_STAGE3_PACKAGE_REQUIRED", "a PASS Stage 3 package is required"
            )
        source = Path(source_value).resolve()
        if self._workspace not in source.parents or not source.is_file():
            raise StudioCommandError(
                "UI111_STAGE3_PACKAGE_INVALID", "Stage 3 package must be inside workspace"
            )
        if self._ffmpeg_path is None or self._ffprobe_path is None:
            raise StudioCommandError("M10C001_DEPENDENCY", "FFmpeg and FFprobe paths are required")
        job = StudioJob(
            uuid.uuid4().hex,
            "STAGE4_CREATE",
            "QUEUED",
            "FROM_STAGE3",
            "FROM_STAGE3",
            0,
            0,
            "Stage 4 · Video Runner",
            source_package=str(source),
            required_count=1,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._cancellations[job.id] = threading.Event()
        self._queue.put(_QueuedStage4(job.id, source))
        return asdict(job)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise StudioCommandError("UI101_JOB_NOT_FOUND", "job does not exist")
            return asdict(job)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise StudioCommandError("UI101_JOB_NOT_FOUND", "job does not exist")
            if job.status not in {"QUEUED", "QUEUED_VLM_REVIEW", "RUNNING", "CANCELLING"}:
                raise StudioCommandError(
                    "UI102_JOB_NOT_CANCELLABLE", "job is not cancellable in its current state"
                )
            self._cancellations[job_id].set()
            job.status = (
                "CANCELLED" if job.status in {"QUEUED", "QUEUED_VLM_REVIEW"} else "CANCELLING"
            )
            return asdict(job)

    def semantic_review_assets(
        self, job_id: str
    ) -> dict[str, Any]:  # pragma: no cover - HTTP integration
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise StudioCommandError("UI101_JOB_NOT_FOUND", "job does not exist")
            if job.kind != "STAGE2_CREATE" or job.stage_id is None:
                raise StudioCommandError(
                    "UI115_REVIEW_UNAVAILABLE", "Stage 2 review is unavailable"
                )
            stage_id = job.stage_id
            current = dict(self._semantic_assessments.get(job_id, {}))
        kernel = WorkflowKernel(self._workspace)
        try:
            rows = kernel.db.connection.execute(
                "SELECT t.basename,a.sha256 FROM asset_transactions t "
                "JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
                "JOIN artifacts a ON a.id=b.artifact_id WHERE t.stage_run_id=? "
                "AND t.orientation='LANDSCAPE' ORDER BY t.created_at,t.basename",
                (stage_id,),
            ).fetchall()
            return {
                "job_id": job_id,
                "assets": [
                    {
                        "basename": str(row["basename"]),
                        "image_sha256": str(row["sha256"]),
                        "status": current[str(row["basename"])].status
                        if str(row["basename"]) in current
                        else "NOT_VERIFIED",
                    }
                    for row in rows
                ],
            }
        finally:
            kernel.close()

    def submit_semantic_review(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"assessments"} or not isinstance(payload["assessments"], list):
            raise StudioCommandError("UI104_INVALID_REQUEST", "assessments array is required")
        assets = self.semantic_review_assets(job_id)["assets"]
        digests = {item["basename"]: item["image_sha256"] for item in assets}
        if len(digests) != 10 or len(payload["assessments"]) != 10:
            raise StudioCommandError(
                "UI116_REVIEW_INCOMPLETE", "exactly 10 committed assets are required"
            )
        assessments: dict[str, SemanticAssessment] = {}
        for value in payload["assessments"]:
            if not isinstance(value, dict) or set(value) != {
                "basename",
                "status",
                "observable_findings",
            }:
                raise StudioCommandError("UI104_INVALID_REQUEST", "assessment shape is invalid")
            name, status, findings = (
                value["basename"],
                value["status"],
                value["observable_findings"],
            )
            if name not in digests or name in assessments or status not in {"PASS", "FAIL"}:
                raise StudioCommandError(
                    "UI104_INVALID_REQUEST", "assessment identity or status is invalid"
                )
            if (
                not isinstance(findings, list)
                or not findings
                or any(
                    not isinstance(item, str) or not item.strip() or len(item) > 500
                    for item in findings
                )
            ):
                raise StudioCommandError(
                    "UI104_INVALID_REQUEST", "observable findings are required"
                )
            evidence = {
                "basename": name,
                "image_sha256": digests[name],
                "method": "HUMAN_REVIEW",
                "observable_findings": [item.strip() for item in findings],
                "status": status,
            }
            assessments[name] = SemanticAssessment(
                name,
                status,
                "HUMAN_REVIEW",
                sha256_bytes(canonical_json_bytes(evidence)),
                tuple(evidence["observable_findings"]),
            )
        with self._lock:
            self._semantic_assessments[job_id] = assessments
            job = self._jobs[job_id]
        self._persist_assessments(job, assessments)
        return self._finalize_stage2(job, assessments)

    def submit_vlm_review(
        self, job_id: str
    ) -> dict[str, Any]:  # pragma: no cover - GPU integration
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise StudioCommandError("UI101_JOB_NOT_FOUND", "job does not exist")
            if job.status != "WAITING_SEMANTIC_REVIEW":
                raise StudioCommandError(
                    "UI115_REVIEW_UNAVAILABLE", "Stage 2 is not waiting for review"
                )
            if self._qwen_model_path is None or self._qwen_runner_path is None:
                raise StudioCommandError(
                    "VLM001_LOCAL_RUNTIME_MISSING", "local VLM is not configured"
                )
            self._cancellations[job_id] = threading.Event()
            job.status = "QUEUED_VLM_REVIEW"
        self._queue.put(_QueuedVlmReview(job_id))
        return asdict(job)

    def retry_stage2(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise StudioCommandError("UI101_JOB_NOT_FOUND", "job does not exist")
            if (
                job.kind != "STAGE2_CREATE"
                or job.status != "FAILED"
                or job.source_package is None
                or job.execution_mode is None
            ):
                raise StudioCommandError(
                    "UI114_STAGE2_NOT_RETRYABLE",
                    "only a failed Stage 2 generation job can be retried",
                )
            job.status = "QUEUED"
            job.error_code = None
            job.error_message = None
            self._cancellations[job.id] = threading.Event()
            queued = _QueuedStage2(job.id, Path(job.source_package), job.execution_mode)
        self._queue.put(queued)
        return asdict(job)

    def retry_stage1_asset(self, transaction_id: str) -> dict[str, Any]:
        """Resume the owning Stage 1 run for one retryable text transaction."""
        self._require_worker()
        kernel = WorkflowKernel(self._workspace)
        try:
            row = kernel.db.connection.execute(
                "SELECT w.id workflow_id,w.status workflow_status,s.id stage_id,s.stage,s.status "
                "stage_status,t.status transaction_status FROM asset_transactions t "
                "JOIN stage_runs s ON s.id=t.stage_run_id "
                "JOIN workflow_runs w ON w.id=s.workflow_id WHERE t.id=?",
                (transaction_id,),
            ).fetchone()
            if row is None:
                raise StudioCommandError(
                    "UI118_TRANSACTION_NOT_FOUND", "transaction does not exist"
                )
            if (
                row["stage"] != "STAGE1"
                or row["transaction_status"] != "FAILED_RETRYABLE"
                or row["stage_status"] != StageStatus.FAIL
                or row["workflow_status"] != WorkflowStatus.FAILED
            ):
                raise StudioCommandError(
                    "UI119_TRANSACTION_NOT_RETRYABLE",
                    "only a failed retryable Stage 1 transaction can be regenerated",
                )
            with self._lock:
                job = next(
                    (
                        candidate
                        for candidate in self._jobs.values()
                        if candidate.workflow_id == row["workflow_id"]
                        and candidate.stage_id == row["stage_id"]
                    ),
                    None,
                )
                request = self._stage1_requests.get(job.id) if job is not None else None
                if job is None or request is None:
                    raise StudioCommandError(
                        "UI120_RETRY_CONTEXT_UNAVAILABLE",
                        "the original Stage 1 request is not available in this Studio session",
                    )
                job.status = "QUEUED"
                job.error_code = None
                job.error_message = None
                self._cancellations[job.id] = threading.Event()
            kernel.transition_workflow(str(row["workflow_id"]), WorkflowStatus.RUNNING)
            kernel.transition_stage(str(row["stage_id"]), StageStatus.GENERATING)
            self._queue.put(_QueuedStage1(job.id, request, resume=True))
            return asdict(job)
        finally:
            kernel.close()

    def _worker(self) -> None:
        try:
            self._worker_loop()
        finally:
            with self._lock:
                for job in self._jobs.values():
                    if job.status in {"QUEUED", "QUEUED_VLM_REVIEW", "RUNNING", "CANCELLING"}:
                        job.status = "FAILED"
                        job.error_code = "UI198_WORKER_UNAVAILABLE"
                        job.error_message = "Studio background worker stopped unexpectedly"

    def _worker_loop(self) -> None:
        while True:
            queued = self._queue.get()
            if queued is None:
                return
            with self._lock:
                job = self._jobs[queued.job_id]
                if job.status == "CANCELLED":
                    continue
                job.status = "RUNNING"
            try:
                if isinstance(queued, _QueuedStage1):
                    self._run_stage1(job, queued.request, resume=queued.resume)
                elif isinstance(queued, _QueuedVlmReview):
                    self._run_vlm_review(job)
                elif isinstance(queued, _QueuedStage3):
                    self._run_stage3(job, queued)
                elif isinstance(queued, _QueuedStage4):
                    self._run_stage4(job, queued)
                else:
                    self._run_stage2(job, queued)
            except (
                Stage1Error,
                Stage2Error,
                Stage3Error,
                KernelError,
                StudioCommandError,
                VlmAssessmentError,
            ) as exc:
                with self._lock:
                    job.status = "FAILED"
                    job.error_code = exc.code
                    job.error_message = str(exc)
                self._update_persisted_status(job)
            except Exception as exc:  # pragma: no cover - containment boundary
                with self._lock:
                    job.status = "FAILED"
                    job.error_code = "UI199_COMMAND_FAILURE"
                    job.error_message = type(exc).__name__
                self._update_persisted_status(job)

    def _run_stage1(self, job: StudioJob, request: Stage1Request, *, resume: bool = False) -> None:
        kernel = WorkflowKernel(self._workspace)
        try:
            try:
                service = Stage1Service(
                    kernel,
                    self._stage1_adapter,
                    self._canonical_path,
                    character_image_config=self._stage1_character_image_config,
                    story_quality_assessor=self._stage1_story_quality_assessor,
                )
                if resume:
                    assert job.workflow_id is not None and job.stage_id is not None
                    result = service.resume_recovery(job.workflow_id, job.stage_id, request)
                else:
                    result = service.start(request)
            except Stage1Error:
                failed = kernel.db.connection.execute(
                    "SELECT w.id workflow_id,s.id stage_id FROM workflow_runs w "
                    "JOIN stage_runs s ON s.workflow_id=w.id "
                    "WHERE w.status=? AND s.stage='STAGE1' "
                    "ORDER BY w.created_at DESC,w.id DESC LIMIT 1",
                    (WorkflowStatus.FAILED,),
                ).fetchone()
                if failed is not None:
                    with self._lock:
                        job.workflow_id = str(failed["workflow_id"])
                        job.stage_id = str(failed["stage_id"])
                raise
            with self._lock:
                job.workflow_id = result.workflow_id
                job.stage_id = result.stage_id
                job.package_path = str(result.package_path) if result.package_path else None
                job.package_digest = result.package_digest
                job.error_code = result.reason_code
                job.status = str(result.status)
        finally:
            kernel.close()

    def _run_stage2(self, job: StudioJob, queued: _QueuedStage2) -> None:
        kernel = WorkflowKernel(self._workspace)
        try:
            source = load_stage1_package(
                queued.source_package, test_mode=queued.execution_mode == "MOCK"
            )
            plan = build_stage2_zone_plan(source)
            canonical_digest = sha256_bytes(self._canonical_path.read_bytes())
            plan_digest = sha256_bytes(plan.visual_plan_bytes)
            config_digest = sha256_bytes(
                canonical_json_bytes(
                    {
                        "source_package": source.package_digest_sha256,
                        "execution_mode": queued.execution_mode,
                    }
                )
            )
            if job.workflow_id is None or job.stage_id is None:
                workflow_id = kernel.create_workflow(
                    str(source.manifest["active_profile"]),
                    "STAGE2",
                    "CREATE",
                    canonical_digest,
                    config_digest,
                )
                kernel.transition_workflow(workflow_id, WorkflowStatus.RUNNING)
                stage_id = kernel.start_stage(workflow_id, "STAGE2", plan_digest)
                kernel.transition_stage(stage_id, StageStatus.GENERATING)
            else:
                workflow_id = job.workflow_id
                stage_id = job.stage_id
            with self._lock:
                job.workflow_id = workflow_id
                job.stage_id = stage_id
                job.profile = str(source.manifest["active_profile"])
            self._persist_stage2_run(job, source.package_digest_sha256)
            adapter = self._stage2_adapter(queued.execution_mode)
            progress = self._workspace / "outputs" / workflow_id / "stage_image_progress.json"
            executor = Stage2ZoneExecutor(
                kernel,
                stage_id,
                source,
                plan,
                adapter,
                progress,
                model_identity=(
                    "deterministic-mock" if queued.execution_mode == "MOCK" else "comfyui-local"
                ),
                timeout_seconds=120 if queued.execution_mode == "COMFYUI" else 30,
                cancellation=self._cancellations[job.id],
            )
            execution = executor.execute_next()
            while True:
                with self._lock:
                    job.committed_count = execution.committed_count
                    job.next_pending_basename = execution.next_pending_basename
                if execution.status != "IN_PROGRESS":
                    break
                if (
                    execution.last_transaction is None
                    or execution.last_transaction.status != "AUTHORITATIVE"
                ):
                    break
                execution = executor.execute_next()
            if self._cancellations[job.id].is_set():
                with self._lock:
                    job.status = "CANCELLED"
                    job.error_code = "IMG004_CANCELLED"
                    job.error_message = "Stage 2 was cancelled"
                return
            if execution.status != "READY_FOR_AGGREGATE_GATES":
                raise StudioCommandError(
                    "UI113_STAGE2_INCOMPLETE",
                    f"Stage 2 stopped before {execution.next_pending_basename}",
                )
            kernel.transition_stage(stage_id, StageStatus.VALIDATING)
            assessments = (
                self._mock_assessments(plan.execution_queue)
                if queued.execution_mode == "MOCK"
                else {}
            )
            gates = evaluate_stage2_landscape_gates(kernel, stage_id, plan, assessments)
            if gates.status != "PASS":
                with self._lock:
                    job.status = "WAITING_SEMANTIC_REVIEW"
                    job.error_code = "M7C299_AGGREGATE_BLOCKED"
                    job.error_message = ",".join(gates.blocker_codes)
                self._update_persisted_status(job)
                return
            kernel.transition_stage(stage_id, StageStatus.PACKAGING)
            output = self._workspace / "outputs" / workflow_id / "stage2" / "story.zip"
            digest = build_stage2_checkpoint(kernel, stage_id, source, plan, gates, output)
            kernel.transition_stage(stage_id, StageStatus.PASS)
            kernel.transition_workflow(workflow_id, WorkflowStatus.COMPLETED)
            with self._lock:
                job.status = "PASS"
                job.package_path = str(output)
                job.package_digest = digest
                job.committed_count = 10
                job.next_pending_basename = None
            self._update_persisted_status(job)
        finally:
            kernel.close()

    def _run_stage3(
        self, job: StudioJob, queued: _QueuedStage3
    ) -> None:  # pragma: no cover - workflow integration
        kernel = WorkflowKernel(self._workspace)
        try:
            source = load_stage2_package(
                queued.source_package, test_mode=queued.execution_mode == "MOCK"
            )
            plan = build_stage3_portrait_plan(source)
            digest = sha256_bytes(self._canonical_path.read_bytes())
            config_digest = sha256_bytes(
                canonical_json_bytes({"parent": source.package_digest_sha256})
            )
            workflow_id = kernel.create_workflow(
                str(source.manifest["active_profile"]), "STAGE3", "CREATE", digest, config_digest
            )
            kernel.transition_workflow(workflow_id, WorkflowStatus.RUNNING)
            stage_id = kernel.start_stage(workflow_id, "STAGE3", plan.adaptation_plan_digest_sha256)
            kernel.transition_stage(stage_id, StageStatus.GENERATING)
            with self._lock:
                job.workflow_id, job.stage_id = workflow_id, stage_id

            def assessor(data: bytes, request: Any) -> SemanticImageGateResult:
                if queued.execution_mode == "VLM_LOCAL":
                    if self._qwen_model_path is None or self._qwen_runner_path is None:
                        raise StudioCommandError(
                            "VLM001_LOCAL_RUNTIME_MISSING", "local VLM is not configured"
                        )
                    result = LocalQwenVlmAssessor(
                        self._qwen_model_path, self._qwen_runner_path
                    ).assess(
                        data,
                        request.basename,
                        {
                            "basename": request.basename,
                            "asset_role": "Stage 3 portrait pair review",
                            "pair_reference": request.commitment_context.get("landscape_reference"),
                            "pair_reference_sha256": request.commitment_context.get(
                                "landscape_sha256"
                            ),
                            "required": [
                                "preserve landscape narrative function",
                                "portrait safe margins",
                                "no text or watermark",
                            ],
                        },
                        self._cancellations[job.id],
                    )
                    return SemanticImageGateResult(
                        result.status,
                        {
                            "image_sha256": sha256_bytes(data),
                            "basename": request.basename,
                            "landscape_reference": request.commitment_context.get(
                                "landscape_reference"
                            ),
                            "landscape_sha256": request.commitment_context.get("landscape_sha256"),
                            "method": "QWEN2_5_VL_LOCAL_PAIR_REVIEW",
                            "observable_findings": list(result.observable_findings),
                            "evidence_digest_sha256": result.evidence_digest_sha256,
                        },
                        "Qwen2.5-VL-7B-Instruct",
                        "offline-local-1.0",
                    )
                return SemanticImageGateResult(
                    "PASS",
                    {
                        "image_sha256": sha256_bytes(data),
                        "basename": request.basename,
                        "method": "TEST_ONLY_DETERMINISTIC_SEMANTIC_FIXTURE",
                        "observable_findings": ["fixture portrait review"],
                    },
                    "deterministic-mock",
                    "M19-mock-1.0",
                )

            image_adapter = (
                DeterministicMockImageAdapter()
                if queued.execution_mode == "MOCK"
                else self._stage2_adapter("COMFYUI")
            )
            executor = Stage3PortraitExecutor(
                kernel,
                stage_id,
                source,
                plan,
                image_adapter,
                assessor,
                workflow_digest=plan.adaptation_plan_digest_sha256,
                model_identity=(
                    "deterministic-mock" if queued.execution_mode == "MOCK" else "comfyui-local"
                ),
                timeout_seconds=30 if queued.execution_mode == "MOCK" else 120,
            )
            execution = executor.execute_all()
            with self._lock:
                job.committed_count = execution.committed_count
                job.next_pending_basename = execution.next_pending_basename
            if execution.status != "READY_FOR_AGGREGATE_GATES":
                raise StudioCommandError(
                    "UI118_STAGE3_INCOMPLETE", "Stage 3 did not commit all portraits"
                )
            kernel.transition_stage(stage_id, StageStatus.VALIDATING)
            package = build_stage3_package(kernel, stage_id, source, generated_at_utc=utc_now())
            kernel.transition_stage(stage_id, StageStatus.PACKAGING)
            output = self._workspace / "outputs" / workflow_id / "stage3" / "story.zip"
            write_stage3_package(package, output)
            kernel.transition_stage(stage_id, StageStatus.PASS)
            kernel.transition_workflow(workflow_id, WorkflowStatus.COMPLETED)
            with self._lock:
                job.status = "PASS"
                job.package_path = str(output)
                job.package_digest = package.archive_sha256
                job.next_pending_basename = None
        finally:
            kernel.close()

    def _run_vlm_review(self, job: StudioJob) -> None:  # pragma: no cover - GPU integration
        if self._qwen_model_path is None or self._qwen_runner_path is None or job.stage_id is None:
            raise StudioCommandError("VLM001_LOCAL_RUNTIME_MISSING", "local VLM is not configured")
        assessor = LocalQwenVlmAssessor(self._qwen_model_path, self._qwen_runner_path)
        kernel = WorkflowKernel(self._workspace)
        try:
            rows = kernel.db.connection.execute(
                "SELECT t.basename,a.sha256,a.relative_path FROM asset_transactions t "
                "JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
                "JOIN artifacts a ON a.id=b.artifact_id WHERE t.stage_run_id=? "
                "AND t.orientation='LANDSCAPE' ORDER BY t.created_at,t.basename",
                (job.stage_id,),
            ).fetchall()
            if len(rows) != 10:
                raise StudioCommandError(
                    "UI116_REVIEW_INCOMPLETE", "exactly 10 assets are required"
                )
            assessments: dict[str, SemanticAssessment] = {}
            for row in rows:
                name = str(row["basename"])
                data = kernel.store.read(str(row["relative_path"]))
                if sha256_bytes(data) != str(row["sha256"]):
                    raise StudioCommandError("VLM006_DIGEST_MISMATCH", "committed image is stale")
                result = assessor.assess(
                    data,
                    name,
                    {
                        "basename": name,
                        "asset_role": "Stage 2 landscape",
                        "required": [
                            "landscape composition",
                            "no text or watermark",
                            "single coherent scene",
                        ],
                    },
                    self._cancellations[job.id],
                )
                assessments[name] = SemanticAssessment(
                    name,
                    result.status,
                    "QWEN2_5_VL_LOCAL",
                    result.evidence_digest_sha256,
                    result.observable_findings,
                )
            with self._lock:
                self._semantic_assessments[job.id] = assessments
            self._persist_assessments(job, assessments)
        finally:
            kernel.close()
        self._finalize_stage2(job, assessments)

    def _finalize_stage2(
        self, job: StudioJob, assessments: dict[str, SemanticAssessment]
    ) -> dict[str, Any]:
        if job.source_package is None or job.stage_id is None or job.workflow_id is None:
            raise StudioCommandError("UI115_REVIEW_UNAVAILABLE", "Stage 2 review is unavailable")
        kernel = WorkflowKernel(self._workspace)
        try:
            source = load_stage1_package(
                Path(job.source_package), test_mode=job.execution_mode == "MOCK"
            )
            plan = build_stage2_zone_plan(source)
            gates = evaluate_stage2_landscape_gates(kernel, job.stage_id, plan, assessments)
            if gates.status != "PASS":
                with self._lock:
                    job.status = "WAITING_SEMANTIC_REVIEW"
                    job.error_code = "M7C299_AGGREGATE_BLOCKED"
                    job.error_message = ",".join(gates.blocker_codes)
                self._update_persisted_status(job)
                return asdict(job)
            kernel.transition_stage(job.stage_id, StageStatus.PACKAGING)
            output = self._workspace / "outputs" / job.workflow_id / "stage2" / "story.zip"
            digest = build_stage2_checkpoint(kernel, job.stage_id, source, plan, gates, output)
            kernel.transition_stage(job.stage_id, StageStatus.PASS)
            kernel.transition_workflow(job.workflow_id, WorkflowStatus.COMPLETED)
            with self._lock:
                job.status = "PASS"
                job.package_path = str(output)
                job.package_digest = digest
                job.error_code = None
                job.error_message = None
            self._update_persisted_status(job)
            return asdict(job)
        finally:
            kernel.close()

    def _run_stage4(self, job: StudioJob, queued: _QueuedStage4) -> None:  # pragma: no cover
        if self._ffmpeg_path is None or self._ffprobe_path is None:
            raise StudioCommandError("M10C001_DEPENDENCY", "FFmpeg and FFprobe paths are required")
        source = load_stage3_package(queued.source_package)
        config = resolve_stage4_config()
        _, prompts_bytes = build_video_prompts(source, config)
        if self._stage4_prompt_assessor is not None:
            self._stage4_prompt_assessor(prompts_bytes)
        package = build_stage4_package(source, prompts_bytes)
        root = self._workspace / "outputs" / job.id / "stage4"
        package_path = root / "story.zip"
        write_stage4_package(package, package_path)
        video_source = load_stage4_video_input(package_path)
        srt_path = root / "subtitles.srt"
        srt_path.write_bytes(derive_srt_bytes(video_source))
        adapter = FFmpegAdapter(
            FFmpegConfig(
                self._ffmpeg_path,
                self._ffprobe_path,
                hashlib.sha256(self._ffmpeg_path.read_bytes()).hexdigest(),
                hashlib.sha256(self._ffprobe_path.read_bytes()).hexdigest(),
            )
        )
        result = render_video(
            video_source,
            srt_path,
            root / "final.mp4",
            adapter,
            cancellation=self._cancellations[job.id],
        )
        with self._lock:
            job.status = "PASS"
            job.package_path = str(result.output_path)
            job.package_digest = result.output_sha256
            job.committed_count = 1
            job.next_pending_basename = None

    def _latest_stage3_package(self) -> str | None:  # pragma: no cover
        with self._lock:
            for job in reversed(tuple(self._jobs.values())):
                if job.kind == "STAGE3_CREATE" and job.status == "PASS" and job.package_path:
                    return job.package_path
        return None

    def _stage2_adapter(self, mode: str) -> LocalImageAdapter:
        if mode == "MOCK":
            return DeterministicMockImageAdapter()
        return ComfyUIImageAdapter(
            ComfyUIConfig(
                endpoint=self._comfyui_endpoint,
                workflow_path=self._comfyui_workflow_path,
            )
        )

    @staticmethod
    def _mock_assessments(names: tuple[str, ...]) -> dict[str, SemanticAssessment]:
        return {
            name: SemanticAssessment(
                name,
                "PASS",
                "TEST_ONLY_DETERMINISTIC_SEMANTIC_FIXTURE",
                f"{index:064x}",
                (f"fixture-observable-{index}",),
            )
            for index, name in enumerate(names, 1)
        }

    def _latest_stage1_package(self) -> str | None:
        with self._lock:
            for job in reversed(tuple(self._jobs.values())):
                if job.kind == "STAGE1_CREATE" and job.status == "PASS" and job.package_path:
                    return job.package_path
        return None

    def _latest_stage2_package(self) -> str | None:  # pragma: no cover - runtime integration
        with self._lock:
            for job in reversed(tuple(self._jobs.values())):
                if job.kind == "STAGE2_CREATE" and job.status == "PASS" and job.package_path:
                    return job.package_path
        return None

    def _restore_stage2_jobs(self) -> None:  # pragma: no cover - restart integration
        kernel = WorkflowKernel(self._workspace)
        try:
            rows = kernel.db.connection.execute(
                "SELECT * FROM studio_stage2_runs ORDER BY created_at"
            ).fetchall()
            for row in rows:
                status = str(row["status"])
                if status in {"RUNNING", "QUEUED", "QUEUED_VLM_REVIEW", "CANCELLING"}:
                    status = "WAITING_SEMANTIC_REVIEW"
                job = StudioJob(
                    id=str(row["job_id"]),
                    kind="STAGE2_CREATE",
                    status=status,
                    profile="RESTORED",
                    language="FROM_STAGE1",
                    duration_minutes=0,
                    seed=0,
                    title="Stage 2 · Visual Bible",
                    workflow_id=str(row["workflow_id"]),
                    stage_id=str(row["stage_run_id"]),
                    source_package=str(row["source_package_path"]),
                    execution_mode=str(row["execution_mode"]),
                    required_count=10,
                )
                self._jobs[job.id] = job
                self._cancellations[job.id] = threading.Event()
                assessment_rows = kernel.db.connection.execute(
                    "SELECT * FROM studio_semantic_assessments WHERE stage_run_id=?",
                    (job.stage_id,),
                ).fetchall()
                self._semantic_assessments[job.id] = {
                    str(item["basename"]): SemanticAssessment(
                        str(item["basename"]),
                        str(item["status"]),
                        str(item["method"]),
                        str(item["evidence_digest_sha256"]),
                        tuple(json.loads(str(item["observable_findings_json"]))),
                    )
                    for item in assessment_rows
                }
        finally:
            kernel.close()

    def _persist_stage2_run(self, job: StudioJob, source_digest: str) -> None:  # pragma: no cover
        if job.workflow_id is None or job.stage_id is None or job.source_package is None:
            return
        kernel = WorkflowKernel(self._workspace)
        try:
            now = utc_now()
            with kernel.db.transaction() as connection:
                connection.execute(
                    "INSERT INTO studio_stage2_runs VALUES (?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,"
                    "updated_at=excluded.updated_at",
                    (
                        job.id,
                        job.workflow_id,
                        job.stage_id,
                        job.source_package,
                        source_digest,
                        job.execution_mode,
                        job.status,
                        now,
                        now,
                    ),
                )
        finally:
            kernel.close()

    def _persist_assessments(  # pragma: no cover - SQLite integration
        self, job: StudioJob, assessments: dict[str, SemanticAssessment]
    ) -> None:
        if job.stage_id is None:
            return
        assets = self.semantic_review_assets(job.id)["assets"]
        digests = {item["basename"]: item["image_sha256"] for item in assets}
        kernel = WorkflowKernel(self._workspace)
        try:
            now = utc_now()
            with kernel.db.transaction() as connection:
                for name, assessment in assessments.items():
                    connection.execute(
                        "INSERT INTO studio_semantic_assessments VALUES (?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(stage_run_id,basename) DO UPDATE SET "
                        "image_sha256=excluded.image_sha256,status=excluded.status,method=excluded.method,"
                        "observable_findings_json=excluded.observable_findings_json,"
                        "evidence_digest_sha256=excluded.evidence_digest_sha256,updated_at=excluded.updated_at",
                        (
                            job.stage_id,
                            name,
                            digests[name],
                            assessment.status,
                            assessment.method,
                            canonical_json_bytes(list(assessment.observable_findings)).decode(),
                            assessment.evidence_digest_sha256,
                            now,
                            now,
                        ),
                    )
        finally:
            kernel.close()

    def _update_persisted_status(
        self, job: StudioJob
    ) -> None:  # pragma: no cover - SQLite integration
        if job.workflow_id is None:
            return
        kernel = WorkflowKernel(self._workspace)
        try:
            with kernel.db.transaction() as connection:
                connection.execute(
                    "UPDATE studio_stage2_runs SET status=?,updated_at=? WHERE job_id=?",
                    (job.status, utc_now(), job.id),
                )
        finally:
            kernel.close()

    def _stage1_request(self, payload: dict[str, Any]) -> Stage1Request:
        allowed = {
            "profile",
            "language",
            "duration_minutes",
            "seed",
            "title",
            "series",
            "episode",
            "episode_mode",
            "creative_input",
        }
        if set(payload) - allowed:
            raise StudioCommandError("UI103_UNKNOWN_FIELD", "request has unknown fields")
        profile = payload.get("profile")
        language = payload.get("language", "vi")
        duration = payload.get("duration_minutes")
        seed = payload.get("seed", 0)
        title = payload.get("title", "Ngọn Đèn Sau Mưa")
        series = payload.get("series")
        episode = payload.get("episode", 1)
        episode_mode = payload.get("episode_mode", "START_SERIES")
        creative_input = payload.get("creative_input", "")
        if not isinstance(profile, str) or not isinstance(language, str):
            raise StudioCommandError("UI104_INVALID_REQUEST", "profile and language are required")
        if not isinstance(duration, int) or isinstance(duration, bool):
            raise StudioCommandError("UI104_INVALID_REQUEST", "duration must be an integer")
        if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 2_147_483_647:
            raise StudioCommandError("UI104_INVALID_REQUEST", "seed is outside the accepted range")
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise StudioCommandError(
                "UI104_INVALID_REQUEST", "title must contain 1 to 120 characters"
            )
        if series is not None and (
            not isinstance(series, str) or not series.strip() or len(series) > 120
        ):
            raise StudioCommandError(
                "UI104_INVALID_REQUEST", "series must contain 1 to 120 characters"
            )
        if not isinstance(episode, int) or isinstance(episode, bool) or not 1 <= episode <= 9999:
            raise StudioCommandError(
                "UI104_INVALID_REQUEST", "episode must be an integer from 1 to 9999"
            )
        if episode_mode != "START_SERIES" and episode_mode is not None:
            raise StudioCommandError(
                "UI105_UNSUPPORTED_EPISODE_MODE",
                "continuing or finalizing a series is not supported by the Stage 1 anchor builder",
            )
        if not isinstance(creative_input, str) or len(creative_input) > 2_000:
            raise StudioCommandError(
                "UI104_INVALID_REQUEST", "creative_input must contain at most 2000 characters"
            )
        try:
            contract = resolve_profile(profile, language)
        except Stage1Error as exc:
            raise StudioCommandError(exc.code, str(exc)) from exc
        if profile == "SERIAL_DETECTIVE" and episode != 1:
            raise StudioCommandError(
                "UI105_UNSUPPORTED_EPISODE_MODE", "a new serial package must start at episode 1"
            )
        if not contract.min_minutes <= duration <= contract.max_minutes:
            raise StudioCommandError(
                "S107_DURATION_RANGE",
                f"duration must be {contract.min_minutes}-{contract.max_minutes} minutes",
            )
        return Stage1Request(
            profile=profile,
            language=language,
            duration_minutes=duration,
            duration_confirmed=True,
            seed=seed,
            title=title.strip(),
            series=series.strip() if series is not None else None,
            episode=str(episode),
            creative_input=creative_input.strip(),
            test_mode=self._stage1_test_mode,
        )
