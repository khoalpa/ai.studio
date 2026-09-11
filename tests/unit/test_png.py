from __future__ import annotations

import json
import struct
import zlib

import pytest

from audio_story.validation.errors import ValidationError
from audio_story.validation.images import PNG_SIGNATURE, validate_png
from audio_story.validation.limits import ValidationLimits


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def make_png(width: int = 1, height: int = 1, metadata: bytes | None = None) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunks = [_chunk(b"IHDR", ihdr)]
    if metadata is not None:
        chunks.append(_chunk(b"tEXt", b"audio_story\0" + metadata))
    chunks.extend(
        [_chunk(b"IDAT", zlib.compress(b"\0" + b"\0\0\0" * width * height)), _chunk(b"IEND", b"")]
    )
    return PNG_SIGNATURE + b"".join(chunks)


def _code(data: bytes, **kwargs: object) -> str:
    with pytest.raises(ValidationError) as caught:
        validate_png(data, "image.png", **kwargs)  # type: ignore[arg-type]
    return caught.value.finding.code


def test_png_validates_pixels_hash_and_metadata() -> None:
    data = make_png(metadata=json.dumps({"schema_version": "1.0"}).encode())
    info = validate_png(
        data, "image.png", expected_dimensions=(1, 1), required_metadata_key="audio_story"
    )
    assert info.width == info.height == 1
    assert info.metadata["audio_story"] == {"schema_version": "1.0"}


def test_png_negative_paths() -> None:
    valid = make_png()
    assert _code(b"bad") == "DP001_PNG_SIGNATURE"
    assert _code(valid[:-5]) == "DP002_PNG_TRUNCATED"
    corrupt = bytearray(valid)
    corrupt[20] ^= 1
    assert _code(bytes(corrupt)) == "DP003_PNG_CRC"
    assert _code(valid, expected_dimensions=(2, 2)) == "DP009_PNG_DIMENSIONS"
    assert _code(valid, required_metadata_key="audio_story") == "DP010_PNG_METADATA_MISSING"
    assert _code(make_png(metadata=b"not-json")) == "DP007_PNG_METADATA"
    limits = ValidationLimits(max_png_pixels=0)
    assert _code(valid, limits=limits) == "DP005_PNG_PIXEL_LIMIT"
