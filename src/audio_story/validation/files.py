"""Deterministic file-set checks independent of archive extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from audio_story.validation.errors import ValidationError, ValidationFinding


@dataclass(frozen=True, slots=True)
class FileSetContract:
    required: frozenset[str] = frozenset()
    forbidden: frozenset[str] = frozenset()
    allowed_pattern: str = r"^[^/]+(?:/[^/]+)*$"
    exact_count: int | None = None


def normalize_relative_path(path: str) -> str:
    return path.replace("\\", "/")


def validate_file_set(
    paths: list[str], contract: FileSetContract, artifact_path: str
) -> tuple[str, ...]:
    normalized = [normalize_relative_path(path) for path in paths]
    if len(set(normalized)) != len(normalized):
        _fail(
            "DF001_DUPLICATE_NORMALIZED_PATH", "duplicate normalized relative path", artifact_path
        )
    for path in normalized:
        pure = PurePosixPath(path)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or not re.fullmatch(contract.allowed_pattern, path)
        ):
            _fail("DF002_INVALID_RELATIVE_PATH", f"invalid relative path {path!r}", artifact_path)
    current = set(normalized)
    missing = contract.required - current
    extra_forbidden = contract.forbidden & current
    if missing:
        _fail("DF003_MISSING_FILE", f"missing files: {sorted(missing)}", artifact_path)
    if extra_forbidden:
        _fail("DF004_FORBIDDEN_FILE", f"forbidden files: {sorted(extra_forbidden)}", artifact_path)
    if contract.exact_count is not None and len(normalized) != contract.exact_count:
        _fail("DF005_FILE_COUNT", f"expected {contract.exact_count} files", artifact_path)
    return tuple(normalized)


def _fail(code: str, message: str, path: str) -> None:
    raise ValidationError(ValidationFinding(code, message, path))
