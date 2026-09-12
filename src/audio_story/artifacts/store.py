"""Crash-aware content-addressed artifact storage."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast


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
    def __init__(self, workspace: Path, connection: sqlite3.Connection | None = None) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / "artifact_store" / "sha256"
        self.temp = self.workspace / "artifact_store" / "tmp"
        self.root.mkdir(parents=True, exist_ok=True)
        self.temp.mkdir(parents=True, exist_ok=True)
        self.connection = connection

    def _metadata_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise StoreError("RK047_METADATA_STORE_REQUIRED", "SQLite metadata store is required")
        return self.connection

    def get_artifact_by_digest(self, digest: str) -> bytes:
        """Return exact content-addressed bytes or raise a stable store error."""
        path = self.path_for(digest)
        if not path.is_file():
            raise StoreError("RK041_ARTIFACT_MISSING", "artifact is not present")
        data = path.read_bytes()
        self.verify_artifact_bytes(digest, data)
        return data

    def verify_artifact_bytes(self, digest: str, data: bytes) -> None:
        if hashlib.sha256(data).hexdigest() != digest:
            raise StoreError("RK042_ARTIFACT_DIGEST_MISMATCH", "artifact bytes do not match digest")

    def register_image_candidate(self, digest: str, **metadata: object) -> None:
        self.get_artifact_by_digest(digest)
        self._metadata_connection().execute(
            "INSERT OR REPLACE INTO image_artifact_authority "
            "VALUES (?,?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
            (
                digest,
                metadata.get("owner_stage"),
                metadata.get("transaction_id"),
                metadata.get("generation_call_id"),
                metadata.get("delivery_status"),
                metadata.get("provenance_digest"),
                metadata.get("evidence_digest"),
                metadata.get("gate_status"),
                0,
                None,
            ),
        )

    def _image_record(self, digest: str) -> sqlite3.Row:
        row = (
            self._metadata_connection()
            .execute("SELECT * FROM image_artifact_authority WHERE artifact_sha256=?", (digest,))
            .fetchone()
        )
        if row is None:
            raise StoreError("RK048_METADATA_MISSING", "artifact authority metadata is missing")
        return cast(sqlite3.Row, row)

    def verify_artifact_ownership(
        self, digest: str, *, owner_stage: str, transaction_id: str, generation_call_id: str
    ) -> None:
        record = self._image_record(digest)
        if (
            record["owner_stage"] != owner_stage
            or record["transaction_id"] != transaction_id
            or record["generation_call_id"] != generation_call_id
        ):
            raise StoreError("RK043_OWNERSHIP_MISMATCH", "artifact ownership does not match")

    def verify_artifact_provenance(self, digest: str) -> None:
        record = self._image_record(digest)
        if not record["provenance_digest"] or not record["evidence_digest"]:
            raise StoreError("RK044_PROVENANCE_MISSING", "artifact provenance is incomplete")

    def verify_current_pass_gate(self, digest: str) -> None:
        if self._image_record(digest)["gate_status"] != "PASS":
            raise StoreError("RK045_GATE_NOT_PASS", "current artifact gate is not PASS")

    def bind_authoritative_artifact(self, digest: str) -> bytes:
        self.get_artifact_by_digest(digest)
        record = self._image_record(digest)
        if record["delivery_status"] != "AUTHORITATIVE":
            raise StoreError("RK046_NOT_AUTHORITATIVE", "artifact is not authoritative")
        self._metadata_connection().execute(
            "UPDATE image_artifact_authority SET immutable=1 WHERE artifact_sha256=?", (digest,)
        )
        return self.get_artifact_by_digest(digest)

    def quarantine_artifact(self, digest: str, code: str) -> None:
        self._metadata_connection().execute(
            "UPDATE image_artifact_authority SET quarantine_code=?,"
            "delivery_status='QUARANTINED' WHERE artifact_sha256=?",
            (code, digest),
        )

    def reconcile_artifact(self, digest: str) -> bool:
        try:
            self.get_artifact_by_digest(digest)
        except StoreError:
            return False
        return True

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
