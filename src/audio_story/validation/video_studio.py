"""M10 Stage 4 intake, subtitle validation and FFprobe gates."""

from __future__ import annotations

import re
import zipfile
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn, cast

from audio_story.domain.stage4 import Stage4PackageInput
from audio_story.domain.video_studio import Stage4VideoInput, VideoStudioError
from audio_story.validation.archives import inspect_zip
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage4 import validate_video_prompts_for_source
from audio_story.validation.strict_json import parse_json_bytes

_SRT_TIME = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})$")


def load_stage4_video_input(
    path: Path, *, expected_archive_sha256: str | None = None
) -> Stage4VideoInput:
    source = path.resolve(strict=True)
    archive_bytes = source.read_bytes()
    archive_sha = sha256_bytes(archive_bytes)
    if expected_archive_sha256 and archive_sha != expected_archive_sha256.lower():
        _fail("M10A001_ARCHIVE_AUTHORITY", "archive SHA-256 mismatch", str(source))
    names = [entry.path for entry in inspect_zip(source)]
    if not names or names[0] != "workflow_manifest.json" or "video_prompts.json" not in names:
        _fail("M10A002_FILE_SET", "Stage 4 manifest/video_prompts member missing", str(source))
    with zipfile.ZipFile(source) as archive:
        members = OrderedDict((name, archive.read(name)) for name in names)
    manifest = _object(members["workflow_manifest.json"], "workflow_manifest.json")
    if (
        manifest.get("package_stage") != "STAGE4"
        or manifest.get("package_purpose") != "VIDEO_PRODUCTION_RELEASE"
    ):
        _fail("M10A003_STAGE", "VIDEO_PRODUCTION_RELEASE Stage 4 package required", str(source))
    files = manifest.get("files")
    if not isinstance(files, list) or manifest.get("file_count") != len(members):
        _fail("M10A004_MANIFEST", "manifest cardinality mismatch", "workflow_manifest.json")
    declared: list[str] = []
    projection: list[dict[str, object]] = []
    for index, raw in enumerate(files):
        if not isinstance(raw, Mapping):
            _fail("M10A004_MANIFEST", "invalid file record", f"$.files[{index}]")
        name = raw.get("path")
        if not isinstance(name, str) or name not in members or name == "workflow_manifest.json":
            _fail("M10A004_MANIFEST", "declared member missing", f"$.files[{index}]")
        data = members[name]
        if raw.get("sha256") != sha256_bytes(data) or raw.get("size_bytes") != len(data):
            _fail("M10A005_MEMBER_DIGEST", "member digest/size mismatch", name)
        declared.append(name)
        projection.append(
            {key: raw[key] for key in ("path", "sha256", "size_bytes", "owner_stage")}
        )
    if declared != names[1:]:
        _fail("M10A004_MANIFEST", "archive and manifest order differ", str(source))
    package_digest = sha256_bytes(canonical_json_bytes(projection))
    if manifest.get("package_digest_sha256") != package_digest:
        _fail("M10A006_PACKAGE_DIGEST", "package digest mismatch", "workflow_manifest.json")
    required = {"story.json", "visual_plan.json", "video_prompts.json"}
    if not required.issubset(members):
        _fail("M10A002_FILE_SET", "render source members missing", str(source))
    story = _object(members["story.json"], "story.json")
    visual_plan = _object(members["visual_plan.json"], "visual_plan.json")
    stage4_source = Stage4PackageInput(
        source,
        archive_sha,
        package_digest,
        members["workflow_manifest.json"],
        OrderedDict(
            (key, value) for key, value in members.items() if key != "workflow_manifest.json"
        ),
        manifest,
        story,
        _object(members["story_validation.json"], "story_validation.json"),
        _object(members["package_quality_report.json"], "package_quality_report.json"),
    )
    video_prompts = validate_video_prompts_for_source(members["video_prompts.json"], stage4_source)
    return Stage4VideoInput(
        source, archive_sha, package_digest, manifest, members, story, visual_plan, video_prompts
    )


def parse_srt(data: bytes) -> tuple[tuple[float, float, str], ...]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VideoStudioError(
            "M10A020_SRT_ENCODING", "SRT must be UTF-8", "subtitles.srt"
        ) from exc
    if text.startswith("\ufeff"):
        _fail("M10A020_SRT_ENCODING", "SRT BOM is forbidden", "subtitles.srt")
    blocks = re.split(r"\r?\n\r?\n", text.strip()) if text.strip() else []
    cues: list[tuple[float, float, str]] = []
    prior_end = 0.0
    for index, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0] != str(index):
            _fail("M10A021_SRT_STRUCTURE", "cue numbering/shape is invalid", f"cue[{index}]")
        match = _SRT_TIME.fullmatch(lines[1])
        if match is None:
            _fail("M10A021_SRT_STRUCTURE", "timestamp is invalid", f"cue[{index}]")
        assert match is not None
        values = [int(value) for value in match.groups()]
        start = _seconds(*values[:4])
        end = _seconds(*values[4:])
        cue_text = " ".join(line.strip() for line in lines[2:] if line.strip())
        if not cue_text or start < prior_end or end <= start:
            _fail(
                "M10A022_SRT_TIMELINE", "cue is empty, overlapping or non-positive", f"cue[{index}]"
            )
        cues.append((start, end, cue_text))
        prior_end = end
    if not cues:
        _fail("M10A021_SRT_STRUCTURE", "SRT must contain a cue", "subtitles.srt")
    return tuple(cues)


def validate_probe(
    probe: Mapping[str, Any],
    *,
    width: int,
    height: int,
    frame_rate: int,
    expected_duration: float,
    require_audio: bool,
    tolerance: float = 0.25,
) -> float:
    streams = probe.get("streams")
    if not isinstance(streams, list):
        _fail("M10D001_PROBE", "ffprobe streams missing", "output.mp4")
    typed_streams = cast(list[Mapping[str, Any]], streams)
    videos = [stream for stream in typed_streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in typed_streams if stream.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != (1 if require_audio else 0):
        _fail("M10D002_STREAMS", "unexpected video/audio stream count", "output.mp4")
    video = videos[0]
    if (video.get("width"), video.get("height"), video.get("pix_fmt")) != (
        width,
        height,
        "yuv420p",
    ):
        _fail("M10D003_VIDEO_SHAPE", "dimensions or pixel format mismatch", "output.mp4")
    rate = _rate(str(video.get("avg_frame_rate", "0/1")))
    duration = float(cast(Mapping[str, Any], probe.get("format", {})).get("duration", 0))
    if abs(rate - frame_rate) > 0.001 or abs(duration - expected_duration) > tolerance:
        _fail(
            "M10D004_TIMELINE",
            f"rate={rate}, duration={duration}, expected_rate={frame_rate}, "
            f"expected_duration={expected_duration}",
            "output.mp4",
        )
    return duration


def _object(data: bytes, name: str) -> Mapping[str, Any]:
    value = parse_json_bytes(data, name, engine_generated=True).value
    if not isinstance(value, Mapping):
        _fail("M10A007_JSON", "root must be an object", name)
    return cast(Mapping[str, Any], value)


def _seconds(hours: int, minutes: int, seconds: int, milliseconds: int) -> float:
    if minutes >= 60 or seconds >= 60:
        _fail("M10A021_SRT_STRUCTURE", "timestamp component out of range", "subtitles.srt")
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def _rate(value: str) -> float:
    try:
        numerator, denominator = value.split("/", 1)
        return int(numerator) / int(denominator)
    except (ValueError, ZeroDivisionError) as exc:
        raise VideoStudioError("M10D001_PROBE", "invalid frame rate", "output.mp4") from exc


def _fail(code: str, message: str, locator: str) -> NoReturn:
    raise VideoStudioError(code, message, locator)
