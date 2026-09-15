from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from audio_story.release import ReleaseError, build_release_bundle, verify_release_bundle


def _wheel(directory: Path, distribution: str, version: str) -> None:
    filename = f"{distribution.replace('-', '_')}-{version}-py3-none-any.whl"
    metadata = f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\nLicense: Test\n"
    with zipfile.ZipFile(directory / filename, "w") as archive:
        archive.writestr(f"{distribution}-{version}.dist-info/METADATA", metadata)
        if distribution == "audio-story-offline":
            migrations = Path(__file__).parents[2] / "migrations"
            for migration in sorted(migrations.glob("[0-9][0-9][0-9]_*.sql")):
                archive.writestr(f"audio_story/migrations/{migration.name}", migration.read_bytes())


def test_build_and_verify_offline_bundle(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "input"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "audio-story-offline", "1.0.0")
    _wheel(wheelhouse, "Pillow", "11.3.0")
    output = tmp_path / "release"
    manifest = build_release_bundle(
        wheelhouse,
        output,
        external_inventory=[{"name": "ffmpeg", "required": False, "sha256": "a" * 64}],
    )
    assert manifest["network_policy"] == "OFFLINE_ONLY"
    assert "--require-hashes" in (output / "install.ps1").read_text(encoding="utf-8")
    assert "Pillow==11.3.0 --hash=sha256:" in (output / "requirements-runtime.lock").read_text()
    assert verify_release_bundle(output) == manifest


def test_release_rejects_incomplete_wheelhouse_and_tampering(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "input"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "audio-story-offline", "1.0.0")
    with pytest.raises(ReleaseError, match="Pillow"):
        build_release_bundle(wheelhouse, tmp_path / "incomplete")
    _wheel(wheelhouse, "Pillow", "11.3.0")
    output = tmp_path / "release"
    build_release_bundle(wheelhouse, output)
    (output / "install.ps1").write_text("tampered", encoding="utf-8")
    with pytest.raises(ReleaseError, match="mismatch"):
        verify_release_bundle(output)


def test_release_rejects_application_wheel_without_migrations(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "input"
    wheelhouse.mkdir()
    _wheel(wheelhouse, "Pillow", "11.3.0")
    metadata = "Metadata-Version: 2.1\nName: audio-story-offline\nVersion: 1.0.0\n"
    with zipfile.ZipFile(wheelhouse / "audio_story_offline-1.0.0-py3-none-any.whl", "w") as archive:
        archive.writestr("audio_story_offline-1.0.0.dist-info/METADATA", metadata)
    with pytest.raises(ReleaseError, match="migration resources"):
        build_release_bundle(wheelhouse, tmp_path / "release")
