from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..errors import WorkflowError
from ..hashing import sha256_bytes
from .config import stage4_config

WORD_PATTERN = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*", re.UNICODE)


def rounded(value: float) -> float:
    places = stage4_config()["timeline_decimal_places"]
    quantizer = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP))


def terminal_pause(text: str) -> float:
    stripped = text.rstrip()
    key = "OTHER"
    if stripped.endswith("...") or stripped.endswith("…"):
        key = "ELLIPSIS"
    elif stripped.endswith("?"):
        key = "QUESTION"
    elif stripped.endswith("!"):
        key = "EXCLAMATION"
    elif stripped.endswith("."):
        key = "PERIOD"
    return stage4_config()["pause_seconds"][key]


@dataclass(frozen=True)
class TimelineSegment:
    item_index: int
    start_word_offset: int
    end_word_offset: int
    start_time_seconds: float
    end_time_seconds: float
    usable_span_seconds: float
    duration_seconds: int
    text: str
    pause_only: bool
    segmentation_mode: str
    segmentation_reason: str
    group_id: str
    segment_index: int
    segment_count: int
    source_text_digest_sha256: str


def derive_timeline(story: dict[str, Any], profile: str) -> tuple[list[TimelineSegment], float]:
    config = stage4_config()
    wpm = config["target_wpm"][profile]
    segments: list[TimelineSegment] = []
    clock = 0.0
    group_ordinal = 0
    for item_index, item in enumerate(story["script"]):
        words = WORD_PATTERN.findall(unicodedata.normalize("NFC", item["text"]))
        if not words:
            raise WorkflowError(f"Script item {item_index} has no usable words")
        group_ordinal += 1
        group_id = f"utt_{group_ordinal:04d}"
        multiplier = config["speed_multiplier"][item["speed"]]
        seconds_per_word = 60.0 / (wpm * multiplier)
        pause = terminal_pause(item["text"])
        max_words = max(1, math.floor(config["sentence_usable_span_max_seconds"] / seconds_per_word))
        last_max_words = max(
            1,
            math.floor((config["sentence_usable_span_max_seconds"] - pause) / seconds_per_word),
        )
        spans: list[tuple[int, int]] = []
        cursor = 0
        remaining = len(words)
        while remaining > last_max_words:
            take = min(max_words, max(3, remaining - last_max_words))
            spans.append((cursor, cursor + take))
            cursor += take
            remaining -= take
        spans.append((cursor, len(words)))
        count = len(spans)
        item_start = clock
        for segment_index, (start, end) in enumerate(spans, 1):
            is_last = segment_index == count
            usable = (end - start) * seconds_per_word + (pause if is_last else 0.0)
            if usable > config["sentence_usable_span_max_seconds"]:
                raise WorkflowError("Unable to segment long utterance within usable span")
            duration = next((value for value in config["clip_duration_options"] if value >= usable), None)
            if duration is None:
                raise WorkflowError("No clip duration can contain the source span")
            start_time = item_start + start * seconds_per_word
            end_time = item_start + end * seconds_per_word + (pause if is_last else 0.0)
            token_slice = " ".join(words[start:end])
            digest_source = f"{item_index}\u001f{start}\u001f{end}\u001f{token_slice}\u001f{str(False).lower()}"
            segments.append(
                TimelineSegment(
                    item_index, start, end, rounded(start_time), rounded(end_time),
                    rounded(usable), duration, token_slice, False,
                    "NOT_REQUIRED" if count == 1 else "TOKEN_BOUNDARY_FALLBACK",
                    "NOT_REQUIRED" if count == 1 else "SOURCE_UTTERANCE_EXCEEDS_MAX_SECONDS",
                    group_id, segment_index, count, sha256_bytes(digest_source.encode("utf-8")),
                )
            )
        clock = item_start + len(words) * seconds_per_word + pause
    return segments, rounded(clock)
