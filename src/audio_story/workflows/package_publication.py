"""Crash-aware filesystem publication for verified M6 image packages."""

from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Event

from audio_story.validation.archives import inspect_zip, safe_extract
from audio_story.validation.canonical import sha256_bytes
from audio_story.workflows.kernel import KernelError, WorkflowKernel


class PublicationFault(StrEnum):
    AFTER_TEMP_WRITE = "AFTER_TEMP_WRITE"
    AFTER_RENAME = "AFTER_RENAME"
    BEFORE_SQLITE_COMMIT = "BEFORE_SQLITE_COMMIT"
    CONNECTION_INTERRUPTION = "CONNECTION_INTERRUPTION"


@dataclass(frozen=True, slots=True)
class PublicationResult:
    package_id: str
    relative_path: str
    digest: str
    byte_size: int


def publish_package(
    kernel: WorkflowKernel,
    package_id: str,
    zip_bytes: bytes,
    relative_path: str,
    *,
    fault: PublicationFault | None = None,
    cancellation: Event | None = None,
) -> PublicationResult:
    """Atomically publish exact verified ZIP bytes, then commit SQLite state."""
    cancellation = cancellation if cancellation is not None else Event()
    _raise_if_cancelled(cancellation)
    destination = (kernel.workspace / relative_path).resolve()
    if kernel.workspace not in destination.parents:
        raise KernelError("RK023_PACKAGE_PATH_ESCAPE", "package path escapes workspace")
    expected = kernel.db.connection.execute(
        "SELECT zip_digest,status FROM image_packages WHERE id=?", (package_id,)
    ).fetchone()
    if expected is None or expected["status"] != "PASS":
        raise KernelError("RK022_PACKAGE_STATE", "only a PASS package can publish")
    digest = sha256_bytes(zip_bytes)
    if digest != expected["zip_digest"]:
        raise KernelError("RK024_PACKAGE_DIGEST_MISMATCH", "ZIP digest differs from PASS record")
    destination.parent.mkdir(parents=True, exist_ok=True)
    canonical_relative = destination.relative_to(kernel.workspace).as_posix()
    kernel.register_image_package_target(package_id, canonical_relative)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    preserve = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(zip_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.read_bytes() != zip_bytes:
            raise KernelError("RK025_PACKAGE_TEMP_REOPEN", "temporary ZIP reopen mismatch")
        inspect_zip(temporary)
        with tempfile.TemporaryDirectory(prefix="audio-story-publish-check-") as parent:
            safe_extract(temporary, Path(parent))
        _raise_if_cancelled(cancellation)
        if fault is PublicationFault.AFTER_TEMP_WRITE:
            preserve = True
            raise KernelError("RK900_INJECTED_FAILURE", fault.value)
        os.replace(temporary, destination)
        if sha256_bytes(destination.read_bytes()) != digest:
            raise KernelError("RK026_PACKAGE_CANONICAL_REOPEN", "published ZIP digest mismatch")
        _raise_if_cancelled(cancellation)
        if fault is PublicationFault.AFTER_RENAME:
            raise KernelError("RK900_INJECTED_FAILURE", fault.value)
        if fault is PublicationFault.BEFORE_SQLITE_COMMIT:
            raise KernelError("RK900_INJECTED_FAILURE", fault.value)
        if fault is PublicationFault.CONNECTION_INTERRUPTION:
            kernel.db.close()
            raise KernelError("RK037_CONNECTION_INTERRUPTED", fault.value)
        kernel.finalize_image_package_publication(package_id, canonical_relative, len(zip_bytes))
        return PublicationResult(package_id, relative_path, digest, len(zip_bytes))
    except OSError as exc:
        raise KernelError(
            "RK028_PACKAGE_FILESYSTEM", "package filesystem operation failed"
        ) from exc
    finally:
        if temporary.exists() and not preserve:
            temporary.unlink()


def _raise_if_cancelled(cancellation: Event) -> None:
    if cancellation.is_set():
        raise KernelError("RK040_PACKAGE_PUBLICATION_CANCELLED", "package publication cancelled")


def recover_package_publication(
    kernel: WorkflowKernel, package_id: str, expected_relative_path: str | None = None
) -> str:
    """Reconcile canonical package bytes with persisted lifecycle state."""
    row = kernel.db.connection.execute(
        "SELECT status,zip_digest,zip_size,published_relative_path FROM image_packages WHERE id=?",
        (package_id,),
    ).fetchone()
    if row is None:
        raise KernelError("RK013_NOT_FOUND", "package does not exist")
    relative = row["published_relative_path"] or expected_relative_path
    if relative is None:
        return "NO_CANONICAL_BINDING"
    path = (kernel.workspace / relative).resolve()
    matches = (
        kernel.workspace in path.parents
        and path.is_file()
        and path.stat().st_size == row["zip_size"]
        and sha256_bytes(path.read_bytes()) == row["zip_digest"]
    )
    if row["status"] == "PASS" and matches:
        try:
            kernel.finalize_image_package_publication(package_id, relative, int(row["zip_size"]))
        except KernelError as exc:
            current = kernel.db.connection.execute(
                "SELECT status FROM image_packages WHERE id=?", (package_id,)
            ).fetchone()
            if (
                exc.code != "RK022_PACKAGE_STATE"
                or current is None
                or current["status"] != "PUBLISHED"
            ):
                raise
        return "PUBLISHED"
    if row["status"] == "PUBLISHED" and not matches:
        kernel.quarantine_image_package_recovery(
            package_id, "RK027_PUBLISHED_PACKAGE_MISSING_OR_MISMATCH"
        )
        return "QUARANTINED"
    return str(row["status"])


def inventory_package_path(
    kernel: WorkflowKernel,
    relative_path: str,
    file_kind: str,
    expected_package_id: str | None = None,
) -> str:
    """Persist an idempotent ownership classification without mutating observed bytes."""
    if file_kind not in {"TEMP", "CANONICAL"}:
        raise KernelError("RK030_ORPHAN_KIND", "invalid package file kind")
    path = (kernel.workspace / relative_path).resolve()
    if kernel.workspace not in path.parents or not path.is_file():
        raise KernelError("RK031_ORPHAN_PATH", "inventory path is missing or unsafe")
    data = path.read_bytes()
    digest = sha256_bytes(data)
    size = len(data)
    package = None
    if expected_package_id is not None:
        package = kernel.db.connection.execute(
            "SELECT package_transaction_id,generation_call_id,status,zip_digest,zip_size,published_relative_path FROM image_packages WHERE id=?",
            (expected_package_id,),
        ).fetchone()
    if package is None:
        classification, reason = "ORPHANED", "RK032_ORPHAN_NO_OWNER"
    elif (
        package["zip_digest"] != digest
        or package["zip_size"] != size
        or (file_kind == "CANONICAL" and package["published_relative_path"] != relative_path)
    ):
        classification, reason = "MISMATCH", "RK033_ORPHAN_AUTHORITY_MISMATCH"
    elif package["status"] == "PASS":
        classification, reason = "OWNED_RECOVERABLE", "RK034_OWNED_RECOVERABLE"
    elif package["status"] == "PUBLISHED" and file_kind == "CANONICAL":
        classification, reason = "RECONCILED", "RK035_ALREADY_RECONCILED"
    else:
        classification, reason = "QUARANTINED", "RK036_OWNER_STATE_INVALID"
    key = sha256_bytes(
        f"{relative_path}|{file_kind}|{digest}|{expected_package_id or ''}|{classification}".encode()
    )
    with kernel.db.transaction() as connection:
        existing = connection.execute(
            "SELECT id FROM package_orphan_inventory WHERE idempotency_key=?", (key,)
        ).fetchone()
        if existing is not None:
            return str(existing["id"])
        record_id = uuid.uuid4().hex
        transaction_id = str(package["package_transaction_id"]) if package is not None else None
        call_id = str(package["generation_call_id"]) if package is not None else None
        now = datetime.now(UTC).isoformat()
        connection.execute(
            "INSERT INTO package_orphan_inventory VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record_id,
                key,
                relative_path,
                file_kind,
                digest,
                size,
                expected_package_id if package is not None else None,
                transaction_id,
                call_id,
                classification,
                reason,
                now,
                now,
            ),
        )
        if package is not None:
            assert transaction_id is not None
            workflow_id, stage_id = kernel._workflow_for_transaction(connection, transaction_id)
            kernel._event(
                connection,
                workflow_id,
                stage_id,
                "PACKAGE_FILE_INVENTORIED",
                {
                    "inventory_id": record_id,
                    "classification": classification,
                    "reason_code": reason,
                },
            )
        return record_id
