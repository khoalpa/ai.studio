"""Preflighted ZIP inspection and no-extractall safe extraction."""

from __future__ import annotations

import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from audio_story.validation.errors import ValidationError, ValidationFinding
from audio_story.validation.files import normalize_relative_path
from audio_story.validation.limits import DEFAULT_LIMITS, ValidationLimits


@dataclass(frozen=True, slots=True)
class ZipMember:
    path: str
    size: int
    compressed_size: int
    crc: int


def inspect_zip(path: Path, *, limits: ValidationLimits = DEFAULT_LIMITS) -> tuple[ZipMember, ...]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        _fail("DZ001_BAD_ZIP", f"cannot open ZIP: {exc}", path)
    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_zip_members:
            _fail("DZ002_MEMBER_LIMIT", "ZIP member count exceeds limit", path)
        seen: set[str] = set()
        total = 0
        members = []
        for info in infos:
            normalized = _safe_member_name(info.filename, path)
            if normalized in seen:
                _fail("DZ003_DUPLICATE_PATH", f"duplicate normalized path {normalized}", path)
            seen.add(normalized)
            if info.is_dir():
                _fail("DZ004_NON_REGULAR_MEMBER", "directory entries are forbidden", path)
            mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            if file_type and not stat.S_ISREG(mode):
                _fail("DZ004_NON_REGULAR_MEMBER", "link or special member is forbidden", path)
            if info.flag_bits & 0x1:
                _fail("DZ005_ENCRYPTED_MEMBER", "encrypted ZIP member is unsupported", path)
            if info.file_size > limits.max_zip_member_bytes:
                _fail("DZ006_MEMBER_SIZE_LIMIT", "ZIP member exceeds size limit", path)
            total += info.file_size
            if total > limits.max_zip_total_bytes:
                _fail("DZ007_TOTAL_SIZE_LIMIT", "ZIP total size exceeds limit", path)
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > limits.max_zip_compression_ratio:
                _fail("DZ008_COMPRESSION_RATIO", "suspicious ZIP compression ratio", path)
            members.append(ZipMember(normalized, info.file_size, info.compress_size, info.CRC))
        try:
            bad = archive.testzip()
        except (OSError, RuntimeError, zipfile.BadZipFile, zlib_error()) as exc:
            _fail("DZ009_CRC_ERROR", f"ZIP CRC/decode failure: {exc}", path)
        if bad is not None:
            _fail("DZ009_CRC_ERROR", f"CRC mismatch in {bad}", path)
        return tuple(members)


def safe_extract(
    path: Path, destination_parent: Path, *, limits: ValidationLimits = DEFAULT_LIMITS
) -> Path:
    members = inspect_zip(path, limits=limits)
    destination_parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="audio-story-", dir=destination_parent)).resolve()
    try:
        with zipfile.ZipFile(path) as archive:
            for member in members:
                target = (root / Path(*PurePosixPath(member.path).parts)).resolve()
                if root not in target.parents:
                    _fail("DZ010_EXTRACT_ESCAPE", "resolved extraction path escapes root", path)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member.path) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, limits.copy_chunk_bytes)
                mode = target.lstat().st_mode
                if not stat.S_ISREG(mode) or target.is_symlink():
                    _fail("DZ004_NON_REGULAR_MEMBER", "extracted member is not regular", path)
        return root
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def _safe_member_name(name: str, archive_path: Path) -> str:
    normalized = normalize_relative_path(name)
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith(("/", "//"))
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in pure.parts
        or any(part in {"", "."} for part in pure.parts)
    ):
        _fail("DZ011_UNSAFE_PATH", f"unsafe ZIP member path {name!r}", archive_path)
    return normalized


def zlib_error() -> type[Exception]:
    import zlib

    return zlib.error


def _fail(code: str, message: str, path: Path) -> None:
    raise ValidationError(ValidationFinding(code, message, str(path)))
