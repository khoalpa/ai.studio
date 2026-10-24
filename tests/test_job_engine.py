from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ai_story.job_engine import Job, JobRegistry


def wait_for_terminal(registry: JobRegistry, job_id: str, timeout: float = 5) -> Job:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = registry.get(job_id)
        if job and job.state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return job
        time.sleep(0.01)
    raise AssertionError("Job did not reach a terminal state")


class JobEngineTests(unittest.TestCase):
    def test_idempotency_progress_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = JobRegistry(max_workers=1, storage_root=root)
            try:
                def task(job: Job) -> dict[str, str]:
                    registry.update_progress(job.job_id, 60, "GENERATING", "Đang sinh")
                    return {"value": "done"}

                first = registry.submit("TEST", task, idempotency_key="same-request")
                duplicate = registry.submit("TEST", task, idempotency_key="same-request")
                self.assertEqual(first.job_id, duplicate.job_id)
                completed = wait_for_terminal(registry, first.job_id)
                self.assertEqual(completed.state, "SUCCEEDED")
                self.assertEqual(completed.progress_percent, 100)
                self.assertEqual(completed.result, {"value": "done"})
                persisted = json.loads((root / f"{first.job_id}.json").read_text(encoding="utf-8"))
                self.assertEqual(persisted["state"], "SUCCEEDED")
            finally:
                registry.close()

    def test_cancel_queued_job_and_retry_failed_job(self) -> None:
        blocker = threading.Event()
        registry = JobRegistry(max_workers=1)
        try:
            running = registry.submit("BLOCK", lambda _: blocker.wait(2) or {})
            queued = registry.submit("QUEUED", lambda _: {"unexpected": True})
            cancelled = registry.cancel(queued.job_id)
            self.assertTrue(cancelled.cancel_requested)
            self.assertEqual(cancelled.state, "CANCELLED")
            blocker.set()
            wait_for_terminal(registry, running.job_id)

            calls = 0

            def fail_once(_: Job) -> dict[str, bool]:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("transient")
                return {"ok": True}

            failed = registry.submit("RETRY", fail_once)
            failed = wait_for_terminal(registry, failed.job_id)
            self.assertEqual(failed.state, "FAILED")
            retried = registry.retry(failed.job_id)
            completed = wait_for_terminal(registry, retried.job_id)
            self.assertEqual(completed.state, "SUCCEEDED")
            self.assertEqual(completed.retry_of, failed.job_id)
            self.assertEqual(completed.attempt, 2)
        finally:
            blocker.set()
            registry.close()

    def test_restart_marks_inflight_job_as_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = Job(job_id="job-0123456789abcdef", operation="TEST", state="RUNNING")
            (root / f"{job.job_id}.json").write_text(
                json.dumps(job.to_dict()), encoding="utf-8"
            )
            registry = JobRegistry(max_workers=1, storage_root=root)
            try:
                restored = registry.get(job.job_id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.state, "FAILED")
                self.assertEqual(restored.error_code, "SERVER_RESTARTED")
                self.assertFalse(restored.retryable)
            finally:
                registry.close()

    def test_gpu_jobs_are_serialized(self) -> None:
        registry = JobRegistry(max_workers=2)
        lock = threading.Lock()
        release = threading.Event()
        entered = threading.Event()
        active = 0
        peak = 0

        def gpu_task(_: Job) -> dict[str, bool]:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                entered.set()
            release.wait(2)
            with lock:
                active -= 1
            return {"ok": True}

        try:
            first = registry.submit("GPU_ONE", gpu_task, resource_class="GPU")
            self.assertTrue(entered.wait(1))
            second = registry.submit("GPU_TWO", gpu_task, resource_class="GPU")
            time.sleep(0.05)
            self.assertEqual(peak, 1)
            self.assertEqual(registry.get(second.job_id).progress_phase, "WAITING_FOR_GPU")
            release.set()
            self.assertEqual(wait_for_terminal(registry, first.job_id).state, "SUCCEEDED")
            self.assertEqual(wait_for_terminal(registry, second.job_id).state, "SUCCEEDED")
            self.assertEqual(peak, 1)
        finally:
            release.set()
            registry.close()


if __name__ == "__main__":
    unittest.main()
