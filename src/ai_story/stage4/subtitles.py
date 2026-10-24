from __future__ import annotations

from dataclasses import dataclass

from .timeline import rounded


@dataclass(frozen=True)
class SubtitleEntry:
    index: int
    clip_id: str
    start_seconds: float
    end_seconds: float
    text: str

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "clip_id": self.clip_id,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "text": self.text,
        }


def derive_subtitles(clips: list[dict]) -> list[SubtitleEntry]:
    entries = []
    cursor = 0.0
    for index, clip in enumerate(clips, 1):
        text = " ".join(segment["text"] for segment in clip["voice_plan"]["segments"])
        start = rounded(cursor)
        end = rounded(cursor + min(clip["usable_span_seconds"], clip["duration_seconds"]))
        entries.append(SubtitleEntry(index, clip["clip_id"], start, end, text))
        cursor += clip["duration_seconds"]
    return entries


def render_srt(entries: list[SubtitleEntry]) -> bytes:
    blocks = []
    for entry in entries:
        blocks.append(
            f"{entry.index}\n{_timestamp(entry.start_seconds, ',')} --> "
            f"{_timestamp(entry.end_seconds, ',')}\n{entry.text}"
        )
    return ("\n\n".join(blocks) + "\n").encode("utf-8")


def render_webvtt(entries: list[SubtitleEntry]) -> bytes:
    blocks = ["WEBVTT"]
    for entry in entries:
        blocks.append(
            f"{entry.clip_id}\n{_timestamp(entry.start_seconds, '.')} --> "
            f"{_timestamp(entry.end_seconds, '.')}\n{entry.text}"
        )
    return ("\n\n".join(blocks) + "\n").encode("utf-8")


def _timestamp(seconds: float, separator: str) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{millis:03d}"
