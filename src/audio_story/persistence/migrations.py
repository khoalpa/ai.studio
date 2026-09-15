"""Checksum-bound idempotent SQLite migrations."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


class MigrationError(RuntimeError):
    code = "RK002_MIGRATION_CHECKSUM_MISMATCH"


def migration_directory() -> Path:
    """Locate packaged migrations, with a source-checkout fallback for editable installs."""
    packaged = Path(__file__).parents[1] / "migrations"
    checkout = Path(__file__).parents[3] / "migrations"
    for candidate in (packaged, checkout):
        if any(candidate.glob("[0-9][0-9][0-9]_*.sql")):
            return candidate
    raise MigrationError("runtime migration resources are missing")


def apply_migrations(connection: sqlite3.Connection, directory: Path) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
        payload = path.read_bytes()
        checksum = hashlib.sha256(payload).hexdigest()
        version = path.name.split("_", 1)[0]
        row = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = ?", (version,)
        ).fetchone()
        if row:
            if row[0] != checksum:
                raise MigrationError(f"migration {version} checksum changed")
            continue
        with connection:
            connection.executescript(payload.decode("utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (version, checksum),
            )
