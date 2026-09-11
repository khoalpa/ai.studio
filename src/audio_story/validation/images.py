"""Deterministic basic PNG structure, pixels and metadata validation."""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass

from audio_story.validation.canonical import sha256_bytes
from audio_story.validation.errors import ValidationError, ValidationFinding
from audio_story.validation.limits import DEFAULT_LIMITS, ValidationLimits

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True, slots=True)
class PngInfo:
    width: int
    height: int
    color_type: int
    sha256: str
    metadata: dict[str, object]


def validate_png(
    data: bytes,
    artifact_path: str,
    *,
    expected_dimensions: tuple[int, int] | None = None,
    required_metadata_key: str | None = None,
    limits: ValidationLimits = DEFAULT_LIMITS,
) -> PngInfo:
    if not data.startswith(PNG_SIGNATURE):
        _fail("DP001_PNG_SIGNATURE", "invalid PNG signature", artifact_path)
    offset = len(PNG_SIGNATURE)
    width = height = color_type = None
    compressed = bytearray()
    metadata: dict[str, object] = {}
    saw_end = False
    while offset < len(data):
        if offset + 12 > len(data):
            _fail("DP002_PNG_TRUNCATED", "truncated PNG chunk", artifact_path, offset)
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            _fail("DP002_PNG_TRUNCATED", "truncated PNG chunk data", artifact_path, offset)
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
            _fail("DP003_PNG_CRC", "PNG chunk CRC mismatch", artifact_path, offset)
        if chunk_type == b"IHDR":
            if length != 13:
                _fail("DP004_PNG_IHDR", "invalid IHDR length", artifact_path, offset)
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if width * height > limits.max_png_pixels:
                _fail("DP005_PNG_PIXEL_LIMIT", "PNG exceeds pixel limit", artifact_path, offset)
            if (
                bit_depth != 8
                or color_type not in {0, 2, 4, 6}
                or compression
                or filtering
                or interlace
            ):
                _fail(
                    "DP006_PNG_MODE",
                    "unsupported PNG mode for basic decoder",
                    artifact_path,
                    offset,
                )
        elif chunk_type == b"IDAT":
            compressed.extend(payload)
        elif chunk_type == b"tEXt":
            keyword, separator, text = payload.partition(b"\0")
            if separator and keyword:
                try:
                    metadata[keyword.decode("latin-1")] = json.loads(text.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    _fail(
                        "DP007_PNG_METADATA", "malformed JSON PNG metadata", artifact_path, offset
                    )
        elif chunk_type == b"IEND":
            saw_end = True
            offset = end
            break
        offset = end
    if not saw_end or offset != len(data) or width is None or height is None or color_type is None:
        _fail(
            "DP002_PNG_TRUNCATED", "PNG is incomplete or has trailing bytes", artifact_path, offset
        )
    assert width is not None and height is not None and color_type is not None
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    try:
        decoded = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        _fail("DP008_PNG_DECODE", f"PNG IDAT decode failed: {exc}", artifact_path)
    expected_size = height * (1 + width * channels)
    if len(decoded) != expected_size:
        _fail("DP008_PNG_DECODE", "decoded PNG scanline size mismatch", artifact_path)
    if expected_dimensions is not None and (width, height) != expected_dimensions:
        _fail(
            "DP009_PNG_DIMENSIONS",
            f"expected {expected_dimensions}, found {(width, height)}",
            artifact_path,
        )
    if required_metadata_key is not None and required_metadata_key not in metadata:
        _fail(
            "DP010_PNG_METADATA_MISSING", f"missing metadata {required_metadata_key}", artifact_path
        )
    return PngInfo(width, height, color_type, sha256_bytes(data), metadata)


def _fail(code: str, message: str, path: str, offset: int | None = None) -> None:
    raise ValidationError(ValidationFinding(code, message, path, byte_offset=offset))
