"""Stable deterministic-validator findings and exceptions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    message: str
    artifact_path: str
    json_path: str | None = None
    byte_offset: int | None = None
    line: int | None = None
    column: int | None = None
    detector_class: str = "DETERMINISTIC"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ValidationError(ValueError):
    def __init__(self, finding: ValidationFinding) -> None:
        self.finding = finding
        super().__init__(f"{finding.code}: {finding.message}")
