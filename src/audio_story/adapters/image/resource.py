"""Single GPU-heavy image worker and deterministic OOM handling."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Semaphore

GPU_HEAVY_JOBS = Semaphore(1)


class ImageResourceError(RuntimeError):
    code = "IMG012_OOM"


@contextmanager
def gpu_job() -> Iterator[None]:
    if not GPU_HEAVY_JOBS.acquire(timeout=120):
        raise ImageResourceError("GPU job semaphore timeout")
    try:
        yield
    finally:
        GPU_HEAVY_JOBS.release()
