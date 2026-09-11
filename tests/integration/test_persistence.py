from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from audio_story.persistence import Database
from audio_story.persistence.migrations import MigrationError

ROOT = Path(__file__).parents[2]
MIGRATIONS = ROOT / "migrations"


def test_new_database_wal_foreign_keys_tables_and_idempotent_migration(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3", MIGRATIONS)
    assert database.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert database.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    names = {
        row[0]
        for row in database.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    required = {
        "workflow_runs",
        "stage_runs",
        "asset_transactions",
        "generation_calls",
        "artifacts",
        "artifact_bindings",
        "gate_results",
        "events",
        "schema_migrations",
    }
    assert required <= names
    database.close()
    reopened = Database(tmp_path / "state.sqlite3", MIGRATIONS)
    assert reopened.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2
    call_columns = {
        row[1] for row in reopened.connection.execute("PRAGMA table_info(generation_calls)")
    }
    assert {
        "model_identity",
        "adapter_version",
        "duration_ms",
        "termination_reason",
    } <= call_columns
    reopened.close()


def test_migration_checksum_change_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, copied)
    database = Database(tmp_path / "state.sqlite3", copied)
    database.close()
    path = copied / "001_workflow_kernel.sql"
    path.write_text(path.read_text(encoding="utf-8") + "\n-- changed", encoding="utf-8")
    with pytest.raises(MigrationError):
        Database(tmp_path / "state.sqlite3", copied)


def test_m3_database_upgrades_to_migration_002(tmp_path: Path) -> None:
    copied = tmp_path / "migrations"
    copied.mkdir()
    shutil.copy2(MIGRATIONS / "001_workflow_kernel.sql", copied)
    database = Database(tmp_path / "state.sqlite3", copied)
    assert database.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    database.close()

    shutil.copy2(MIGRATIONS / "002_llm_call_metadata.sql", copied)
    upgraded = Database(tmp_path / "state.sqlite3", copied)
    assert upgraded.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2
    columns = {row[1] for row in upgraded.connection.execute("PRAGMA table_info(generation_calls)")}
    assert "model_identity" in columns
    upgraded.close()


def test_foreign_key_and_unique_constraint_are_final_guards(tmp_path: Path) -> None:
    database = Database(tmp_path / "state.sqlite3", MIGRATIONS)
    with pytest.raises(sqlite3.IntegrityError), database.transaction() as connection:
        connection.execute(
            "INSERT INTO stage_runs VALUES ('s','missing','STAGE1','PREFLIGHT',?, 'x','x')",
            ("a" * 64,),
        )
    database.close()
