from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from audio_story.validation.archives import inspect_zip, safe_extract
from audio_story.validation.errors import ValidationError
from audio_story.validation.limits import ValidationLimits


def _zip(
    path: Path,
    names: list[str],
    payload: bytes = b"ok",
    compression: int = zipfile.ZIP_DEFLATED,
) -> Path:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name in names:
            archive.writestr(name, payload)
    return path


def _code(path: Path, **kwargs: object) -> str:
    with pytest.raises(ValidationError) as caught:
        inspect_zip(path, **kwargs)  # type: ignore[arg-type]
    return caught.value.finding.code


def test_safe_zip_inspects_and_extracts_under_new_root(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "safe.zip", ["story.json", "nested/item.txt"])
    assert len(inspect_zip(archive)) == 2
    root = safe_extract(archive, tmp_path / "extract")
    assert root.parent == (tmp_path / "extract").resolve()
    assert (root / "nested" / "item.txt").read_bytes() == b"ok"


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/drive", "//server/share"])
def test_unsafe_member_paths_are_rejected(tmp_path: Path, name: str) -> None:
    assert _code(_zip(tmp_path / "bad.zip", [name])) == "DZ011_UNSAFE_PATH"


def test_normalized_duplicate_is_rejected(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        archive = _zip(tmp_path / "duplicate.zip", ["a/b", "a\\b"])
    assert _code(archive) == "DZ003_DUPLICATE_PATH"


def test_symlink_and_directory_are_rejected(tmp_path: Path) -> None:
    symlink_zip = tmp_path / "link.zip"
    with zipfile.ZipFile(symlink_zip, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")
    assert _code(symlink_zip) == "DZ004_NON_REGULAR_MEMBER"
    assert _code(_zip(tmp_path / "dir.zip", ["folder/"])) == "DZ004_NON_REGULAR_MEMBER"


def test_fifo_special_member_is_rejected(tmp_path: Path) -> None:
    special_zip = tmp_path / "fifo.zip"
    with zipfile.ZipFile(special_zip, "w") as archive:
        info = zipfile.ZipInfo("pipe")
        info.create_system = 3
        info.external_attr = (stat.S_IFIFO | 0o600) << 16
        archive.writestr(info, b"")
    assert _code(special_zip) == "DZ004_NON_REGULAR_MEMBER"


def test_unsafe_extraction_never_writes_outside_destination(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "escape.zip", ["../outside.txt"])
    destination = tmp_path / "destination"
    with pytest.raises(ValidationError, match="DZ011_UNSAFE_PATH"):
        safe_extract(archive, destination)
    assert not (tmp_path / "outside.txt").exists()
    assert not destination.exists()


def test_resource_limits_reject_member_count_size_total_and_ratio(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "limits.zip", ["a", "b"], b"x" * 1000)
    cases = [
        ValidationLimits(max_zip_members=1),
        ValidationLimits(max_zip_member_bytes=10),
        ValidationLimits(max_zip_total_bytes=1500),
        ValidationLimits(max_zip_compression_ratio=1.0),
    ]
    codes = [
        "DZ002_MEMBER_LIMIT",
        "DZ006_MEMBER_SIZE_LIMIT",
        "DZ007_TOTAL_SIZE_LIMIT",
        "DZ008_COMPRESSION_RATIO",
    ]
    for limits, code in zip(cases, codes, strict=True):
        assert _code(archive, limits=limits) == code


def test_corrupted_crc_is_rejected(tmp_path: Path) -> None:
    archive = _zip(
        tmp_path / "crc.zip",
        ["payload.bin"],
        b"unique-payload-123",
        zipfile.ZIP_STORED,
    )
    data = bytearray(archive.read_bytes())
    position = data.find(b"unique-payload-123")
    assert position >= 0
    data[position] ^= 1
    archive.write_bytes(data)
    assert _code(archive) in {"DZ001_BAD_ZIP", "DZ009_CRC_ERROR"}
