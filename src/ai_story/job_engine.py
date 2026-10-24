from __future__ import annotations

import json
import secrets
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .errors import (
    ArtifactError,
    CircuitOpenError,
    RuntimeTimeoutError,
    RuntimeUnavailableError,
    WorkflowError,
)

TERMINAL_JOB_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    job_id: str
    operation: str
    state: str = "QUEUED"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    started_at: str | None = None
    completed_at: str | None = None
    run_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    retryable: bool = False
    retry_of: str | None = None
    attempt: int = 1
    progress_percent: int = 0
    progress_phase: str = "QUEUED"
    progress_message: str = "Đang chờ tài nguyên"
    cancel_requested: bool = False
    resource_class: str = "CPU"
    idempotency_key: str | None = None
    request_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobRegistry:
    """Persistent in-process job engine with cooperative cancellation and GPU serialization."""

    def __init__(self, max_workers: int = 2, storage_root: Path | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, Callable[[Job], dict[str, Any]]] = {}
        self._futures: dict[str, Future[None]] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = threading.RLock()
        self._gpu_lane = threading.Semaphore(1)
        self._storage_root = storage_root.resolve() if storage_root else None
        if self._storage_root:
            self._storage_root.mkdir(parents=True, exist_ok=True)
            self._restore()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="ai-story-job"
        )

    def submit(
        self,
        operation: str,
        task: Callable[[Job], dict[str, Any]],
        *,
        idempotency_key: str | None = None,
        request_payload: dict[str, Any] | None = None,
        resource_class: str = "CPU",
        retry_of: str | None = None,
        attempt: int = 1,
    ) -> Job:
        with self._lock:
            idempotency_scope = f"{operation}:{idempotency_key}" if idempotency_key else None
            if idempotency_scope and idempotency_scope in self._idempotency:
                return self._copy(self._jobs[self._idempotency[idempotency_scope]])
            job = Job(
                job_id=f"job-{secrets.token_hex(8)}",
                operation=operation,
                idempotency_key=idempotency_key,
                request_payload=dict(request_payload or {}),
                resource_class=resource_class,
                retry_of=retry_of,
                attempt=attempt,
            )
            self._jobs[job.job_id] = job
            self._tasks[job.job_id] = task
            if idempotency_scope:
                self._idempotency[idempotency_scope] = job.job_id
            self._persist(job)
            self._futures[job.job_id] = self._executor.submit(self._run, job.job_id)
            return self._copy(job)

    def _run(self, job_id: str) -> None:
        job = self._jobs[job_id]
        lane = self._gpu_lane if job.resource_class == "GPU" else None
        if lane:
            self.update_progress(job_id, 2, "WAITING_FOR_GPU", "Đang chờ GPU")
            lane.acquire()
        try:
            if self.is_cancel_requested(job_id):
                self._cancelled(job_id)
                return
            self._update(
                job_id,
                state="RUNNING",
                started_at=_utc_now(),
                progress_percent=5,
                progress_phase="STARTING",
                progress_message="Đang khởi tạo workflow",
            )
            try:
                result = self._tasks[job_id](self._jobs[job_id])
            except Exception as exc:  # API boundary must retain workflow failures
                if self.is_cancel_requested(job_id):
                    self._cancelled(job_id)
                else:
                    self._update(
                        job_id,
                        state="FAILED",
                        error=str(exc),
                        error_code=type(exc).__name__.upper(),
                        retryable=(
                            not isinstance(exc, WorkflowError)
                            or isinstance(
                                exc,
                                (RuntimeUnavailableError, RuntimeTimeoutError, CircuitOpenError, ArtifactError),
                            )
                        ),
                        completed_at=_utc_now(),
                        progress_phase="FAILED",
                        progress_message="Workflow thất bại",
                    )
                return
            if self.is_cancel_requested(job_id):
                self._cancelled(job_id)
                return
            self._update(
                job_id,
                state="SUCCEEDED",
                result=result,
                completed_at=_utc_now(),
                progress_percent=100,
                progress_phase="COMPLETED",
                progress_message="Đã tạo đầu ra",
            )
        finally:
            if lane:
                lane.release()

    def update_progress(self, job_id: str, percent: int, phase: str, message: str) -> None:
        self._update(
            job_id,
            progress_percent=max(0, min(100, int(percent))),
            progress_phase=phase,
            progress_message=message,
        )

    def set_run_id(self, job_id: str, run_id: str) -> None:
        self._update(job_id, run_id=run_id)

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs[job_id].cancel_requested

    def raise_if_cancelled(self, job_id: str) -> None:
        if self.is_cancel_requested(job_id):
            raise WorkflowError("Job was cancelled by the operator")

    def cancel(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise FileNotFoundError("Job not found")
            if job.state in TERMINAL_JOB_STATES:
                return self._copy(job)
            job.cancel_requested = True
            future = self._futures.get(job_id)
            if job.state == "QUEUED" and future and future.cancel():
                job.state = "CANCELLED"
                job.completed_at = _utc_now()
                job.progress_phase = "CANCELLED"
                job.progress_message = "Đã hủy trước khi chạy"
                job.retryable = True
            else:
                job.progress_message = "Đã yêu cầu hủy; đang chờ điểm dừng an toàn"
            job.updated_at = _utc_now()
            self._persist(job)
            return self._copy(job)

    def _cancelled(self, job_id: str) -> None:
        self._update(
            job_id,
            state="CANCELLED",
            completed_at=_utc_now(),
            progress_phase="CANCELLED",
            progress_message="Đã hủy tại điểm dừng an toàn",
            retryable=True,
        )

    def retry(self, job_id: str) -> Job:
        with self._lock:
            source = self._jobs.get(job_id)
            if not source:
                raise FileNotFoundError("Job not found")
            if source.state not in {"FAILED", "CANCELLED"}:
                raise WorkflowError("Only failed or cancelled jobs can be retried")
            task = self._tasks.get(job_id)
            if not task:
                raise WorkflowError("Job cannot be retried after server restart; submit it again")
            return self.submit(
                source.operation,
                task,
                request_payload=source.request_payload,
                resource_class=source.resource_class,
                retry_of=source.job_id,
                attempt=source.attempt + 1,
            )

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return self._copy(job) if job else None

    def list(self, limit: int = 100) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [self._copy(job) for job in jobs[: max(1, min(limit, 500))]]

    def delete_for_run(self, run_id: str) -> int:
        """Remove terminal jobs and their persisted records for one workflow run."""
        with self._lock:
            matching = [job for job in self._jobs.values() if job.run_id == run_id]
            if any(job.state not in TERMINAL_JOB_STATES for job in matching):
                raise WorkflowError("Không thể xóa tác vụ khi workflow vẫn đang chạy")
            job_ids = {job.job_id for job in matching}
            if not job_ids:
                return 0
            for job_id in job_ids:
                self._jobs.pop(job_id, None)
                self._tasks.pop(job_id, None)
                self._futures.pop(job_id, None)
            self._idempotency = {
                key: job_id
                for key, job_id in self._idempotency.items()
                if job_id not in job_ids
            }
            if self._storage_root:
                for job_id in job_ids:
                    (self._storage_root / f"{job_id}.json").unlink(missing_ok=True)
            return len(job_ids)

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = _utc_now()
            self._persist(job)

    def _persist(self, job: Job) -> None:
        if not self._storage_root:
            return
        target = self._storage_root / f"{job.job_id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(target)
        if job.run_id:
            run_metadata = self._storage_root.parent / job.run_id / "run.json"
            if run_metadata.is_file():
                try:
                    value = json.loads(run_metadata.read_text(encoding="utf-8"))
                    value.update({
                        "status": job.state,
                        "updated_at": job.updated_at,
                        "job_id": job.job_id,
                        "progress_percent": job.progress_percent,
                        "progress_phase": job.progress_phase,
                    })
                    temporary_run = run_metadata.with_suffix(".json.tmp")
                    temporary_run.write_text(
                        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    temporary_run.replace(run_metadata)
                except (OSError, ValueError, json.JSONDecodeError):
                    # Job persistence remains authoritative if run metadata is temporarily unavailable.
                    pass

    def _restore(self) -> None:
        assert self._storage_root is not None
        for path in sorted(self._storage_root.glob("job-*.json")):
            try:
                job = Job(**json.loads(path.read_text(encoding="utf-8")))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if job.state not in TERMINAL_JOB_STATES:
                job.state = "FAILED"
                job.error = "Server restarted before the job reached a terminal state"
                job.error_code = "SERVER_RESTARTED"
                job.retryable = False
                job.completed_at = _utc_now()
                job.progress_phase = "INTERRUPTED"
                job.progress_message = "Bị gián đoạn khi dịch vụ khởi động lại"
                job.updated_at = _utc_now()
            self._jobs[job.job_id] = job
            if job.idempotency_key:
                self._idempotency[f"{job.operation}:{job.idempotency_key}"] = job.job_id
            self._persist(job)

    @staticmethod
    def _copy(job: Job) -> Job:
        return Job(**job.to_dict())

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)


def read_job_history(storage_root: Path, limit: int = 100) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if not storage_root.is_dir():
        return jobs
    for path in storage_root.glob("job-*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            Job(**value)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        jobs.append(value)
    jobs.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return jobs[: max(1, min(limit, 500))]
