"""Typed Stage 1 request, result and stable failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from audio_story.domain.enums import Profile


class Stage1Status(StrEnum):
    WAITING_INPUT = "WAITING_INPUT"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    PASS = "PASS"
    FAIL = "FAIL"


class Stage1Error(RuntimeError):
    """Stable, locator-bearing Stage 1 error."""

    def __init__(self, code: str, message: str, locator: str) -> None:
        self.code = code
        self.locator = locator
        super().__init__(f"{code} at {locator}: {message}")


@dataclass(frozen=True, slots=True)
class Stage1Request:
    profile: str | None
    language: str = "vi"
    duration_minutes: int | None = None
    duration_confirmed: bool = False
    seed: int = 0
    title: str = "Ngọn Đèn Sau Mưa"
    test_mode: bool = False


@dataclass(frozen=True, slots=True)
class ProfileContract:
    profile: Profile
    target_wpm: int
    min_minutes: int
    max_minutes: int
    min_script_items: int
    channel: str
    audience: str
    genre: str


@dataclass(frozen=True, slots=True)
class Stage1Result:
    status: Stage1Status
    workflow_id: str
    stage_id: str
    package_path: Path | None = None
    package_digest: str | None = None
    reason_code: str | None = None


def resolve_profile(value: str | None, language: str) -> ProfileContract:
    if value is None or not value.strip():
        raise Stage1Error("S101_MISSING_PROFILE", "one active profile is required", "$.profile")
    if "," in value or "+" in value:
        raise Stage1Error(
            "S103_CONFLICTING_PROFILE", "only one active profile is permitted", "$.profile"
        )
    try:
        profile = Profile(value)
    except ValueError as exc:
        raise Stage1Error("S102_INVALID_PROFILE", "profile is not canonical", "$.profile") from exc
    if language not in {"vi", "en"}:
        raise Stage1Error("S104_INVALID_LANGUAGE", "language must be vi or en", "$.language")
    if profile is Profile.YOUTH_SAFE:
        return ProfileContract(
            profile,
            200 if language == "vi" else 210,
            12,
            18,
            40,
            "Hộp Truyện Kỳ Diệu",
            "trẻ em và thiếu niên 7–10 tuổi",
            "children audio story",
        )
    if profile is Profile.ADULT_STANDARD:
        return ProfileContract(
            profile,
            220,
            25,
            38,
            60,
            "Dạ Khúc Trưởng Thành",
            "người trưởng thành từ 18 tuổi trở lên, nghe truyện audio ngắn và trung bình",
            "adult audio drama",
        )
    return ProfileContract(
        profile,
        220,
        35,
        50,
        70,
        "Dạ Đàm Kỳ Án",
        "người trưởng thành từ 18 tuổi trở lên, nghe truyện trinh thám audio nhiều episode",
        "serialized detective audio drama",
    )
