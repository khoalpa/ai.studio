from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class Profile(StringEnum):
    YOUTH_SAFE = "YOUTH_SAFE"
    ADULT_STANDARD = "ADULT_STANDARD"
    SERIAL_DETECTIVE = "SERIAL_DETECTIVE"


class Stage(StringEnum):
    STAGE1 = "STAGE1"
    STAGE2 = "STAGE2"
    STAGE3 = "STAGE3"
    STAGE4 = "STAGE4"


class Operation(StringEnum):
    CREATE = "CREATE"
    REPAIR = "REPAIR"


@dataclass(frozen=True)
class ArtifactRecord:
    path: str
    owner_stage: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PackageResult:
    archive_path: str
    archive_sha256: str
    package_digest_sha256: str
    file_count: int
    package_stage: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
