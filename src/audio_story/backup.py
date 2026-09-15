"""Deterministic, fail-closed workspace backup and restore."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from audio_story.persistence.migrations import apply_migrations
from audio_story.validation.archives import inspect_zip, safe_extract
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes

BACKUP_SCHEMA_VERSION = "1.0"
MANIFEST_NAME = "backup_manifest.json"
DATABASE_MEMBER = "workspace/runtime.sqlite3"
CANONICAL_DIGEST = "4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27"
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class BackupError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class BackupResult:
    path: Path
    sha256: str
    content_digest: str
    member_count: int
    mode: str


def _fail(code: str, message: str) -> NoReturn:
    raise BackupError(code, message)


def _contained(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or ".." in pure.parts:
        _fail("M11B003_PATH", f"unsafe workspace path: {relative!r}")
    target = (root / Path(*pure.parts)).resolve()
    if root != target and root not in target.parents:
        _fail("M11B003_PATH", f"workspace path escapes root: {relative!r}")
    return target


def _database_checks(connection: sqlite3.Connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or integrity[0] != "ok":
        _fail("M11B004_DATABASE_INTEGRITY", "SQLite integrity_check did not pass")
    foreign = connection.execute("PRAGMA foreign_key_check").fetchone()
    if foreign is not None:
        _fail("M11B005_DATABASE_FOREIGN_KEY", "SQLite foreign_key_check found a violation")


def _migration_rows(connection: sqlite3.Connection) -> list[dict[str, str]]:
    try:
        rows = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        _fail("M11B006_MIGRATIONS", f"cannot read migration authority: {exc}")
    return [{"version": str(row[0]), "sha256": str(row[1])} for row in rows]


def _local_migrations(directory: Path) -> list[dict[str, str]]:
    return [
        {"version": path.name.split("_", 1)[0], "sha256": sha256_bytes(path.read_bytes())}
        for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    ]


def _referenced_paths(connection: sqlite3.Connection) -> list[str]:
    paths = {
        str(row[0])
        for row in connection.execute("SELECT relative_path FROM artifacts ORDER BY relative_path")
    }
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "image_packages" in tables:
        paths.update(
            str(row[0])
            for row in connection.execute(
                "SELECT published_relative_path FROM image_packages "
                "WHERE published_relative_path IS NOT NULL ORDER BY published_relative_path"
            )
        )
    return sorted(paths)


def _runtime_output_paths(root: Path) -> list[str]:
    outputs = root / "outputs"
    if not outputs.exists():
        return []
    paths: list[str] = []
    for path in sorted(outputs.rglob("*")):
        if path.is_symlink():
            _fail("M11B003_PATH", f"runtime output is a symlink: {path}")
        if path.is_file() and ".pending" not in path.parts:
            paths.append(path.relative_to(root).as_posix())
    return paths


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    descriptor, name = tempfile.mkstemp(suffix=".zip")
    os.close(descriptor)
    path = Path(name)
    try:
        with zipfile.ZipFile(
            path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for member_name, payload in members.items():
                info = zipfile.ZipInfo(member_name, _ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, payload)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def create_backup(workspace: Path, output: Path, *, mode: str = "FULL") -> BackupResult:
    """Create a digest-bound snapshot without copying live WAL/SHM files."""
    root = workspace.resolve()
    database_path = root / "runtime.sqlite3"
    if mode not in {"FULL", "STATE_ONLY"}:
        _fail("M11B001_MODE", "backup mode must be FULL or STATE_ONLY")
    if not database_path.is_file():
        _fail("M11B002_DATABASE_MISSING", "workspace runtime.sqlite3 is missing")
    output = output.resolve()
    if output == database_path or root == output or root in output.parents:
        _fail("M11B007_OUTPUT_SCOPE", "backup output must be outside the workspace")
    output.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(database_path, isolation_level=None)
    snapshot_path: Path | None = None
    lock_path = root / ".m11-backup.lock"
    lock_descriptor: int | None = None
    try:
        try:
            lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            _fail("M11B008_LEASE_CONFLICT", "workspace backup lock already exists")
        source.execute("PRAGMA foreign_keys=ON")
        now = source.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
        active = source.execute(
            "SELECT owner_id FROM workspace_leases WHERE expires_at>? LIMIT 1",
            (now,),
        ).fetchone()
        if active is not None:
            _fail("M11B008_LEASE_CONFLICT", "workspace has an active owner")
        descriptor, snapshot_name = tempfile.mkstemp(
            prefix="audio-story-backup-", suffix=".sqlite3", dir=output.parent
        )
        os.close(descriptor)
        snapshot_path = Path(snapshot_name)
        snapshot = sqlite3.connect(snapshot_path)
        try:
            source.backup(snapshot)
            _database_checks(snapshot)
            migrations = _migration_rows(snapshot)
            referenced = _referenced_paths(snapshot)
        finally:
            snapshot.close()

        payloads: dict[str, bytes] = {DATABASE_MEMBER: snapshot_path.read_bytes()}
        if mode == "FULL":
            for relative in sorted(set(referenced) | set(_runtime_output_paths(root))):
                path = _contained(root, relative)
                if not path.is_file() or path.is_symlink():
                    _fail("M11B009_REFERENCED_FILE", f"referenced file is missing: {relative}")
                payloads[f"workspace/{PurePosixPath(relative).as_posix()}"] = path.read_bytes()
        entries = [
            {"path": name, "size": len(data), "sha256": sha256_bytes(data)}
            for name, data in sorted(payloads.items())
        ]
        content_digest = sha256_bytes(canonical_json_bytes(entries))
        manifest: dict[str, Any] = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "mode": mode,
            "canonical_prompt_sha256": CANONICAL_DIGEST,
            "content_digest": content_digest,
            "migrations": migrations,
            "members": entries,
        }
        ordered = {MANIFEST_NAME: canonical_json_bytes(manifest)}
        ordered.update({name: payloads[name] for name in sorted(payloads)})
        archive_bytes = _zip_bytes(ordered)
        temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(archive_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            inspect_zip(temporary)
            if temporary.read_bytes() != archive_bytes:
                _fail("M11B010_REOPEN", "backup bytes changed after write")
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        return BackupResult(output, sha256_bytes(archive_bytes), content_digest, len(entries), mode)
    except sqlite3.DatabaseError as exc:
        _fail("M11B011_DATABASE", f"SQLite backup failed: {exc}")
    finally:
        source.close()
        if lock_descriptor is not None:
            os.close(lock_descriptor)
            lock_path.unlink(missing_ok=True)
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)


def _load_backup(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    members = inspect_zip(path)
    if not members or members[0].path != MANIFEST_NAME:
        _fail("M11C001_MANIFEST", "backup manifest must be the first member")
    with zipfile.ZipFile(path) as archive:
        payloads = {member.path: archive.read(member.path) for member in members}
    try:
        manifest = json.loads(payloads.pop(MANIFEST_NAME).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("M11C001_MANIFEST", f"invalid backup manifest: {exc}")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != BACKUP_SCHEMA_VERSION:
        _fail("M11C002_SCHEMA", "unsupported backup schema")
    expected = manifest.get("members")
    actual = [
        {"path": name, "size": len(data), "sha256": sha256_bytes(data)}
        for name, data in sorted(payloads.items())
    ]
    if expected != actual or manifest.get("content_digest") != sha256_bytes(
        canonical_json_bytes(actual)
    ):
        _fail("M11C003_DIGEST", "backup member manifest or content digest mismatch")
    if manifest.get("canonical_prompt_sha256") != CANONICAL_DIGEST:
        _fail("M11C004_CANONICAL", "backup canonical authority is incompatible")
    return manifest, payloads


def restore_backup(backup: Path, workspace: Path, migrations: Path) -> BackupResult:
    """Validate in staging and publish a restored workspace only after every gate passes."""
    backup = backup.resolve()
    destination = workspace.resolve()
    if destination.exists() and any(destination.iterdir()):
        _fail("M11C005_DESTINATION", "restore destination must be absent or empty")
    manifest, payloads = _load_backup(backup)
    if manifest.get("mode") != "FULL":
        _fail("M11C006_MODE", "standalone restore requires a FULL backup")
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = safe_extract(backup, parent)
    staged_workspace = staging / "workspace"
    database_path = staged_workspace / "runtime.sqlite3"
    try:
        connection = sqlite3.connect(database_path)
        try:
            _database_checks(connection)
            recorded = _migration_rows(connection)
            if recorded != manifest.get("migrations"):
                _fail("M11C007_MIGRATIONS", "database migration list differs from manifest")
            if recorded != _local_migrations(migrations):
                _fail("M11C007_MIGRATIONS", "backup migrations are incompatible with this runtime")
            apply_migrations(connection, migrations)
            _database_checks(connection)
            for relative in _referenced_paths(connection):
                path = _contained(staged_workspace.resolve(), relative)
                if not path.is_file() or path.is_symlink():
                    _fail("M11C008_CLOSURE", f"restored referenced file is missing: {relative}")
                row = connection.execute(
                    "SELECT sha256,byte_size FROM artifacts WHERE relative_path=?", (relative,)
                ).fetchone()
                if row is not None:
                    data = path.read_bytes()
                    if len(data) != row[1] or sha256_bytes(data) != row[0]:
                        _fail("M11C009_ARTIFACT", f"restored artifact mismatch: {relative}")
        finally:
            connection.close()
        if destination.exists():
            destination.rmdir()
        os.replace(staged_workspace, destination)
        shutil.rmtree(staging, ignore_errors=True)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    archive_bytes = backup.read_bytes()
    return BackupResult(
        backup,
        sha256_bytes(archive_bytes),
        str(manifest["content_digest"]),
        len(payloads),
        str(manifest["mode"]),
    )
