"""Crash-aware content-addressed artifact storage."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class StoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class FaultPoint(StrEnum):
    BEFORE_TEMP_WRITE = "BEFORE_TEMP_WRITE"
    AFTER_TEMP_WRITE = "AFTER_TEMP_WRITE"
    AFTER_RENAME = "AFTER_RENAME"


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    digest: str
    relative_path: str
    byte_size: int
    deduplicated: bool


class ArtifactStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / "artifact_store" / "sha256"
        self.temp = self.workspace / "artifact_store" / "tmp"
        self.root.mkdir(parents=True, exist_ok=True)
        self.temp.mkdir(parents=True, exist_ok=True)

    def path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise StoreError("RK003_INVALID_DIGEST", "digest must be lowercase SHA-256")
        return self.root / digest[:2] / digest[2:]

    def put(self, data: bytes, fault: FaultPoint | None = None) -> StoredArtifact:
        digest = hashlib.sha256(data).hexdigest()
        target = self.path_for(digest)
        relative = target.relative_to(self.workspace).as_posix()
        if target.exists():
            if target.read_bytes() != data:
                raise StoreError("RK004_STORE_DIGEST_COLLISION", "existing bytes differ")
            return StoredArtifact(digest, relative, len(data), True)
        if fault is FaultPoint.BEFORE_TEMP_WRITE:
            raise StoreError("RK900_INJECTED_FAILURE", fault.value)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"{digest}.", suffix=".tmp", dir=self.temp
        )
        temporary = Path(temporary_name)
        preserve_temporary = False
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if fault is FaultPoint.AFTER_TEMP_WRITE:
                preserve_temporary = True
                raise StoreError("RK900_INJECTED_FAILURE", fault.value)
            if not self._same_volume(temporary, target.parent):
                raise StoreError(
                    "RK005_CROSS_VOLUME_COMMIT", "temporary and target are on different volumes"
                )
            os.replace(temporary, target)
            if fault is FaultPoint.AFTER_RENAME:
                raise StoreError("RK900_INJECTED_FAILURE", fault.value)
            reopened = target.read_bytes()
            if hashlib.sha256(reopened).hexdigest() != digest:
                raise StoreError(
                    "RK006_REOPEN_DIGEST_MISMATCH", "committed bytes failed digest reopen"
                )
            return StoredArtifact(digest, relative, len(data), False)
        finally:
            if temporary.exists() and not preserve_temporary:
                temporary.unlink()

    def read(self, relative_path: str) -> bytes:
        path = (self.workspace / relative_path).resolve()
        if self.workspace not in path.parents:
            raise StoreError("RK007_PATH_ESCAPE", "artifact path escapes workspace")
        return path.read_bytes()

    def orphan_temps(self) -> tuple[Path, ...]:
        return tuple(sorted(self.temp.glob("*.tmp")))

    @staticmethod
    def _same_volume(temporary: Path, target_parent: Path) -> bool:
        return temporary.stat().st_dev == target_parent.stat().st_dev
