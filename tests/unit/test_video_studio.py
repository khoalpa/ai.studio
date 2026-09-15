from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pytest

from audio_story.domain.video_studio import Stage4VideoInput, VideoRenderRequest, VideoStudioError
from audio_story.validation.video_studio import parse_srt, validate_probe
from audio_story.workflows.video_studio import plan_slideshow


def _source() -> Stage4VideoInput:
    story = OrderedDict(
        script=[
            OrderedDict(zone="OPENING", text="First exact line."),
            OrderedDict(zone="OPENING", text="Second exact line."),
            OrderedDict(zone="ENDING", text="Final exact line."),
        ]
    )
    assets = [
        OrderedDict(
            role="ZONE",
            zone="OPENING",
            landscape_image="landscape/opening.png",
            portrait_image="portrait/opening.png",
        ),
        OrderedDict(
            role="ZONE",
            zone="ENDING",
            landscape_image="landscape/ending.png",
            portrait_image="portrait/ending.png",
        ),
    ]
    members = OrderedDict(
        [
            ("story.json", b"story"),
            ("video_prompts.json", b"prompts"),
            ("landscape/opening.png", b"png"),
            ("landscape/ending.png", b"png"),
            ("portrait/opening.png", b"png"),
            ("portrait/ending.png", b"png"),
        ]
    )
    return Stage4VideoInput(
        Path("story.zip"),
        "a" * 64,
        "b" * 64,
        OrderedDict(),
        members,
        story,
        OrderedDict(resolved_mode="ZONE", assets=assets),
        OrderedDict(project=OrderedDict(total_story_duration_seconds=6.0)),
    )


def _srt() -> bytes:
    return (
        b"1\n00:00:00,000 --> 00:00:02,000\nFirst exact line.\n\n"
        b"2\n00:00:02,000 --> 00:00:04,000\nSecond exact line.\n\n"
        b"3\n00:00:04,000 --> 00:00:06,000\nFinal exact line.\n"
    )


def test_srt_and_zone_timeline_are_exact_and_contiguous() -> None:
    assert len(parse_srt(_srt())) == 3
    mode, segments, total = plan_slideshow(
        _source(), _srt(), VideoRenderRequest(slideshow_timeline_mode="ZONE")
    )
    assert mode == "ZONE"
    assert total == 6.0
    assert [(item.source_id, item.start_seconds, item.end_seconds) for item in segments] == [
        ("OPENING", 0.0, 4.0),
        ("ENDING", 4.0, 6.0),
    ]


def test_auto_falls_back_to_fixed_without_authoritative_scenes() -> None:
    mode, segments, _ = plan_slideshow(_source(), _srt(), VideoRenderRequest())
    assert mode == "FIXED"
    assert len(segments) == 2


def test_srt_rejects_overlap_and_story_mismatch() -> None:
    bad_time = _srt().replace(b"00:00:02,000 --> 00:00:04,000", b"00:00:01,000 --> 00:00:04,000")
    with pytest.raises(VideoStudioError, match="M10A022_SRT_TIMELINE"):
        parse_srt(bad_time)
    with pytest.raises(VideoStudioError, match="M10B002_SRT_BINDING"):
        plan_slideshow(
            _source(), _srt().replace(b"Second exact", b"Changed exact"), VideoRenderRequest()
        )


def test_scene_mode_fails_closed_without_scene_plan() -> None:
    with pytest.raises(VideoStudioError, match="M10B011_SCENE_PLAN"):
        plan_slideshow(_source(), _srt(), VideoRenderRequest(slideshow_timeline_mode="SCENE"))


def test_probe_gate_checks_streams_shape_rate_and_duration() -> None:
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p",
                "avg_frame_rate": "30/1",
            }
        ],
        "format": {"duration": "6.000"},
    }
    assert (
        validate_probe(
            probe,
            width=1920,
            height=1080,
            frame_rate=30,
            expected_duration=6.0,
            require_audio=False,
        )
        == 6.0
    )
    with pytest.raises(VideoStudioError, match="M10D002_STREAMS"):
        validate_probe(
            probe, width=1920, height=1080, frame_rate=30, expected_duration=6.0, require_audio=True
        )
