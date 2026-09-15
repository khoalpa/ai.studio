from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from audio_story.backup import BackupError, create_backup, restore_backup
from audio_story.workflows import WorkflowKernel

ROOT = Path(__file__).parents[2]
MIGRATIONS = ROOT / "migrations"


def _workspace(path: Path) -> tuple[Path, bytes]:
    kernel = WorkflowKernel(path)
    try:
        stored = kernel.store.put(b"authoritative artifact")
        kernel.db.connection.execute(
            "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "artifact",
                stored.digest,
                stored.relative_path,
                stored.byte_size,
                "application/octet-stream",
                "ARCHIVE",
                "STAGE1",
                "COMMITTED",
                "READ_ONLY",
                None,
                "2026-01-01T00:00:00Z",
            ),
        )
        kernel.db.connection.commit()
        return path, b"authoritative artifact"
    finally:
        kernel.close()


def test_full_backup_is_deterministic_and_restore_reconciles(tmp_path: Path) -> None:
    source, artifact = _workspace(tmp_path / "source")
    output = source / "outputs" / "workflow" / "story.zip"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"published package")
    first = create_backup(source, tmp_path / "first.asbackup")
    second = create_backup(source, tmp_path / "second.asbackup")
    assert first.sha256 == second.sha256
    assert first.content_digest == second.content_digest

    destination = tmp_path / "restored"
    restored = restore_backup(first.path, destination, MIGRATIONS)
    assert restored.content_digest == first.content_digest
    connection = sqlite3.connect(destination / "runtime.sqlite3")
    try:
        relative = connection.execute("SELECT relative_path FROM artifacts").fetchone()[0]
    finally:
        connection.close()
    assert (destination / relative).read_bytes() == artifact
    assert (destination / "outputs" / "workflow" / "story.zip").read_bytes() == b"published package"
    assert not (destination / "runtime.sqlite3-wal").exists()


def test_backup_rejects_missing_reference_and_restore_rejects_nonempty(tmp_path: Path) -> None:
    source, _ = _workspace(tmp_path / "source")
    connection = sqlite3.connect(source / "runtime.sqlite3")
    relative = connection.execute("SELECT relative_path FROM artifacts").fetchone()[0]
    connection.close()
    (source / relative).unlink()
    with pytest.raises(BackupError) as missing:
        create_backup(source, tmp_path / "broken.asbackup")
    assert missing.value.code == "M11B009_REFERENCED_FILE"

    clean, _ = _workspace(tmp_path / "clean")
    backup = create_backup(clean, tmp_path / "valid.asbackup")
    destination = tmp_path / "occupied"
    destination.mkdir()
    (destination / "user.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(BackupError) as occupied:
        restore_backup(backup.path, destination, MIGRATIONS)
    assert occupied.value.code == "M11C005_DESTINATION"
    assert (destination / "user.txt").read_text(encoding="utf-8") == "keep"


def test_restore_rejects_tampered_manifest_before_publication(tmp_path: Path) -> None:
    source, _ = _workspace(tmp_path / "source")
    original = create_backup(source, tmp_path / "valid.asbackup")
    tampered = tmp_path / "tampered.asbackup"
    with zipfile.ZipFile(original.path) as archive:
        names = archive.namelist()
        payloads = {name: archive.read(name) for name in names}
    manifest = json.loads(payloads["backup_manifest.json"])
    manifest["content_digest"] = "0" * 64
    payloads["backup_manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(tampered, "w") as archive:
        for name in names:
            archive.writestr(name, payloads[name])
    destination = tmp_path / "not-created"
    with pytest.raises(BackupError) as changed:
        restore_backup(tampered, destination, MIGRATIONS)
    assert changed.value.code == "M11C003_DIGEST"
    assert not destination.exists()


def test_state_only_backup_cannot_be_restored_standalone(tmp_path: Path) -> None:
    source, _ = _workspace(tmp_path / "source")
    backup = create_backup(source, tmp_path / "state.asbackup", mode="STATE_ONLY")
    with pytest.raises(BackupError) as error:
        restore_backup(backup.path, tmp_path / "restored", MIGRATIONS)
    assert error.value.code == "M11C006_MODE"
