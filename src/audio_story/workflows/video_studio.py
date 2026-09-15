"""M10 deterministic slideshow planning, rendering and publication."""

from __future__ import annotations

import os
import tempfile
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from threading import Event
from typing import Any, cast

from audio_story.adapters.image.resource import gpu_job
from audio_story.adapters.video.ffmpeg import FFmpegAdapter
from audio_story.domain.stage4 import Stage4Config, Stage4PackageInput
from audio_story.domain.video_studio import (
    RenderResult,
    SlideshowSegment,
    Stage4VideoInput,
    VideoRenderRequest,
    VideoStudioError,
)
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.video_studio import parse_srt, validate_probe
from audio_story.workflows.stage4_planning import derive_timeline

_MODES = {"AUTO", "SCENE", "ZONE", "FIXED"}
_ORIENTATIONS = {"LANDSCAPE": (1920, 1080), "PORTRAIT": (1080, 1920)}


def derive_srt_bytes(source: Stage4VideoInput) -> bytes:
    """Derive one exact story-item cue from the canonical Stage 4 timing algorithm."""
    compatibility_source = Stage4PackageInput(
        source.source_path,
        source.archive_sha256,
        source.package_digest_sha256,
        source.members["workflow_manifest.json"],
        OrderedDict(
            (name, data)
            for name, data in source.members.items()
            if name != "workflow_manifest.json"
        ),
        source.manifest,
        source.story,
        source.video_prompts,
        source.video_prompts,
    )
    spans = derive_timeline(compatibility_source, Stage4Config())
    by_item: dict[int, list[Any]] = {}
    for span in spans:
        by_item.setdefault(span.item_index, []).append(span)
    script = cast(list[Mapping[str, Any]], source.story["script"])
    if set(by_item) != set(range(len(script))):
        raise VideoStudioError("M10A023_SRT_DERIVATION", "timeline does not cover every item")
    blocks = []
    for index, item in enumerate(script):
        item_spans = by_item[index]
        start = float(item_spans[0].start_time_seconds)
        end = float(item_spans[-1].end_time_seconds)
        blocks.append(
            f"{index + 1}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{item['text']}"
        )
    data = ("\n\n".join(blocks) + "\n").encode("utf-8")
    parse_srt(data)
    return data


def plan_slideshow(
    source: Stage4VideoInput, srt_bytes: bytes, request: VideoRenderRequest
) -> tuple[str, tuple[SlideshowSegment, ...], float]:
    if request.slideshow_timeline_mode not in _MODES or request.orientation not in _ORIENTATIONS:
        raise VideoStudioError("M10B001_CONFIG", "invalid timeline mode or orientation")
    cues = parse_srt(srt_bytes)
    script = cast(list[Mapping[str, Any]], source.story.get("script"))
    if len(cues) != len(script):
        raise VideoStudioError("M10B002_SRT_BINDING", "one exact SRT cue per script item required")
    for index, (cue, item) in enumerate(zip(cues, script, strict=True)):
        normalized_story = " ".join(str(item.get("text", "")).split())
        normalized_cue = " ".join(cue[2].split())
        if normalized_cue != normalized_story:
            raise VideoStudioError(
                "M10B002_SRT_BINDING", "SRT text differs from story", f"cue[{index + 1}]"
            )
    expected_total = float(
        cast(Mapping[str, Any], source.video_prompts["project"])["total_story_duration_seconds"]
    )
    total = cues[-1][1]
    if abs(total - expected_total) > 0.25:
        raise VideoStudioError("M10B003_DURATION", "SRT end does not match Stage 4 timeline")
    plan_mode = str(source.visual_plan.get("resolved_mode", ""))
    mode = request.slideshow_timeline_mode
    if mode == "AUTO":
        mode = "SCENE" if plan_mode == "SCENE" and _has_valid_scene_assets(source) else "FIXED"
    if mode == "SCENE":
        segments = _scene_segments(source, cues, request.orientation)
    elif mode == "ZONE":
        segments = _zone_segments(source, cues, request.orientation)
    else:
        segments = _fixed_segments(source, total, request.orientation)
    _validate_segments(segments, total, source)
    return mode, segments, total


def render_video(
    source: Stage4VideoInput,
    srt_path: Path,
    output_path: Path,
    adapter: FFmpegAdapter,
    request: VideoRenderRequest | None = None,
    *,
    audio_path: Path | None = None,
    cancellation: Event | None = None,
) -> RenderResult:
    request = request or VideoRenderRequest()
    srt_bytes = srt_path.resolve(strict=True).read_bytes()
    audio_bytes = audio_path.resolve(strict=True).read_bytes() if audio_path else None
    mode, segments, total = plan_slideshow(source, srt_bytes, request)
    width, height = _ORIENTATIONS[request.orientation]
    request_record: dict[str, Any] = {
        "schema_version": "1.0",
        "stage4_archive_sha256": source.archive_sha256,
        "stage4_package_digest_sha256": source.package_digest_sha256,
        "video_prompts_sha256": sha256_bytes(source.members["video_prompts.json"]),
        "story_sha256": sha256_bytes(source.members["story.json"]),
        "srt_sha256": sha256_bytes(srt_bytes),
        "audio_sha256": sha256_bytes(audio_bytes) if audio_bytes is not None else None,
        "requested_mode": request.slideshow_timeline_mode,
        "resolved_mode": mode,
        "orientation": request.orientation,
        "frame_rate": request.frame_rate,
        "video_codec": request.video_codec,
        "pixel_format": request.pixel_format,
        "audio_codec": request.audio_codec if audio_path else None,
        "segments": [asdict(segment) for segment in segments],
    }
    request_digest = sha256_bytes(canonical_json_bytes(request_record))
    destination = output_path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="audio-story-m10-", dir=destination.parent
    ) as temporary_name:
        temporary = Path(temporary_name)
        image_paths: dict[str, Path] = {}
        for index, segment in enumerate(segments):
            image = temporary / f"frame-{index:04d}.png"
            image.write_bytes(source.members[segment.image_member])
            image_paths[segment.image_member] = image
        candidate = temporary / "output.mp4"
        args = ["-y"]
        for segment in segments:
            args.extend(
                (
                    "-loop",
                    "1",
                    "-framerate",
                    str(request.frame_rate),
                    "-t",
                    f"{segment.duration_seconds:.3f}",
                    "-i",
                    str(image_paths[segment.image_member]),
                )
            )
        if audio_path is not None:
            args.extend(("-i", str(audio_path.resolve(strict=True))))
        filters = [
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={request.frame_rate},"
            f"setsar=1[v{index}]"
            for index in range(len(segments))
        ]
        joined = "".join(f"[v{index}]" for index in range(len(segments)))
        filters.append(f"{joined}concat=n={len(segments)}:v=1:a=0[outv]")
        args.extend(
            (
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[outv]",
                "-c:v",
                request.video_codec,
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                request.pixel_format,
                "-r",
                str(request.frame_rate),
                "-fps_mode",
                "cfr",
            )
        )
        if audio_path is not None:
            args.extend(("-map", f"{len(segments)}:a:0", "-c:a", request.audio_codec, "-shortest"))
        else:
            args.append("-an")
        args.extend(("-movflags", "+faststart", str(candidate)))
        with gpu_job():
            adapter.render(args, timeout_seconds=request.timeout_seconds, cancellation=cancellation)
        probe = adapter.probe(candidate)
        duration = validate_probe(
            probe,
            width=width,
            height=height,
            frame_rate=request.frame_rate,
            expected_duration=total,
            require_audio=audio_path is not None,
        )
        output_bytes = candidate.read_bytes()
        output_digest = sha256_bytes(output_bytes)
        quality = OrderedDict(
            schema_version="1.0",
            status="PASS",
            deterministic_probe_status="PASS",
            output_sha256=output_digest,
            duration_seconds=round(duration, 3),
            width=width,
            height=height,
            frame_rate=request.frame_rate,
            audio_present=audio_path is not None,
            ffprobe=probe,
        )
        quality_bytes = canonical_json_bytes(quality)
        manifest = OrderedDict(
            schema_version="1.0",
            purpose="VIDEO_STUDIO_RESULT",
            request_digest_sha256=request_digest,
            stage4_archive_sha256=source.archive_sha256,
            stage4_package_digest_sha256=source.package_digest_sha256,
            video_prompts_sha256=sha256_bytes(source.members["video_prompts.json"]),
            story_sha256=sha256_bytes(source.members["story.json"]),
            srt_sha256=sha256_bytes(srt_bytes),
            audio_sha256=sha256_bytes(audio_bytes) if audio_bytes else None,
            renderer_identity=adapter.identity(),
            quality_report_sha256=sha256_bytes(quality_bytes),
            output_sha256=output_digest,
            output_size_bytes=len(output_bytes),
            status="PASS",
        )
        manifest_bytes = canonical_json_bytes(manifest)
        _atomic_publish(output_bytes, destination)
        quality_path = destination.with_suffix(".quality.json")
        manifest_path = destination.with_suffix(".manifest.json")
        _atomic_publish(quality_bytes, quality_path)
        _atomic_publish(manifest_bytes, manifest_path)
    if sha256_bytes(destination.read_bytes()) != output_digest:
        raise VideoStudioError("M10E001_REOPEN", "published MP4 digest mismatch", str(destination))
    if sha256_bytes(source.source_path.read_bytes()) != source.archive_sha256:
        raise VideoStudioError(
            "M10E002_SOURCE_MUTATION", "Stage 4 archive changed", str(source.source_path)
        )
    return RenderResult(
        destination,
        output_digest,
        len(output_bytes),
        request_digest,
        quality_path,
        manifest_path,
        duration,
        mode,
    )


def _zone_segments(
    source: Stage4VideoInput, cues: tuple[tuple[float, float, str], ...], orientation: str
) -> tuple[SlideshowSegment, ...]:
    assets = _asset_map(source, orientation, "ZONE")
    script = cast(list[Mapping[str, Any]], source.story["script"])
    result: list[SlideshowSegment] = []
    for cue, item in zip(cues, script, strict=True):
        zone = str(item["zone"])
        image = assets.get(zone)
        if image is None:
            raise VideoStudioError("M10B010_ZONE_ASSET", "zone image missing", zone)
        if result and result[-1].image_member == image:
            previous = result.pop()
            result.append(SlideshowSegment(image, previous.start_seconds, cue[1], "ZONE", zone))
        else:
            result.append(SlideshowSegment(image, cue[0], cue[1], "ZONE", zone))
    return tuple(result)


def _scene_segments(
    source: Stage4VideoInput, cues: tuple[tuple[float, float, str], ...], orientation: str
) -> tuple[SlideshowSegment, ...]:
    result = []
    assets = [
        item
        for item in cast(list[Mapping[str, Any]], source.visual_plan.get("assets", []))
        if item.get("role") == "SCENE"
    ]
    assets.sort(key=lambda item: int(item.get("ordinal", 0)))
    for ordinal, item in enumerate(assets, 1):
        start, end = item.get("script_item_start"), item.get("script_item_end")
        if (
            item.get("ordinal") != ordinal
            or not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start <= end < len(cues)
        ):
            raise VideoStudioError("M10B011_SCENE_PLAN", "scene ordinal/span invalid")
        member = _oriented_member(item, orientation)
        result.append(
            SlideshowSegment(
                member, cues[start][0], cues[end][1], "SCENE", str(item.get("scene_id"))
            )
        )
    if not result:
        raise VideoStudioError("M10B011_SCENE_PLAN", "SCENE mode has no authoritative scenes")
    return tuple(result)


def _fixed_segments(
    source: Stage4VideoInput, total: float, orientation: str
) -> tuple[SlideshowSegment, ...]:
    members = list(_asset_map(source, orientation, "ZONE").values())
    if not members:
        raise VideoStudioError("M10B012_FIXED_ASSET", "no fixed slideshow images")
    result = []
    for index, member in enumerate(members):
        start = round(total * index / len(members), 3)
        end = total if index == len(members) - 1 else round(total * (index + 1) / len(members), 3)
        result.append(SlideshowSegment(member, start, end, "FIXED", f"fixed_{index + 1:04d}"))
    return tuple(result)


def _asset_map(source: Stage4VideoInput, orientation: str, role: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in cast(list[Mapping[str, Any]], source.visual_plan.get("assets", [])):
        role_matches = item.get("role") == role or (
            role == "ZONE" and item.get("role") in {"GREETING", "FAREWELL"}
        )
        if role_matches and isinstance(item.get("zone"), str):
            result[str(item["zone"])] = _oriented_member(item, orientation)
    return result


def _oriented_member(item: Mapping[str, Any], orientation: str) -> str:
    key = "landscape_image" if orientation == "LANDSCAPE" else "portrait_image"
    member = item.get(key)
    if not isinstance(member, str):
        raise VideoStudioError("M10B013_ORIENTATION", "orientation asset missing")
    return member


def _has_valid_scene_assets(source: Stage4VideoInput) -> bool:
    return any(
        item.get("role") == "SCENE"
        for item in cast(list[Mapping[str, Any]], source.visual_plan.get("assets", []))
    )


def _validate_segments(
    segments: tuple[SlideshowSegment, ...], total: float, source: Stage4VideoInput
) -> None:
    if (
        not segments
        or abs(segments[0].start_seconds) > 0.001
        or abs(segments[-1].end_seconds - total) > 0.001
    ):
        raise VideoStudioError("M10B020_COVERAGE", "timeline does not cover the complete SRT")
    previous = 0.0
    for index, segment in enumerate(segments):
        if (
            segment.image_member not in source.members
            or segment.duration_seconds <= 0
            or abs(segment.start_seconds - previous) > 0.001
        ):
            raise VideoStudioError(
                "M10B020_COVERAGE", "timeline gap, overlap or missing image", f"segment[{index}]"
            )
        previous = segment.end_seconds


def _atomic_publish(data: bytes, destination: Path) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary = Path(name)
        if temporary.read_bytes() != data:
            raise VideoStudioError("M10E003_TEMP_REOPEN", "temporary output mismatch")
        os.replace(temporary, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def _srt_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"
