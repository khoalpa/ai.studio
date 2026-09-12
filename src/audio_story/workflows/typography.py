"""Deterministic, dependency-free cover typography fixture for M6-A."""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from audio_story.validation.images import validate_image_qa


@dataclass(frozen=True, slots=True)
class TypographyConfig:
    width: int = 256
    height: int = 256
    safe_margin: int = 16
    renderer_version: str = "M6A-TYPO-1"
    font_identity: str = "fixture-block-font-v1"


DEFAULT_TYPOGRAPHY = TypographyConfig()


class TypographyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def render_cover(text: str, *, config: TypographyConfig = DEFAULT_TYPOGRAPHY) -> bytes:
    """Render deterministic block glyphs; rejects overflow beyond safe margins."""
    if not text or len(text) * 8 > config.width - 2 * config.safe_margin:
        raise ValueError("TYPO001_TEXT_LAYOUT")
    rows = bytearray()
    for y in range(config.height):
        line = bytearray([0])
        for x in range(config.width):
            ink = (
                y >= config.height - config.safe_margin - 8
                and x < config.safe_margin + len(text) * 8
            )
            line.extend((32, 32, 32) if ink else (245, 245, 245))
        rows.extend(line)
    metadata = json.dumps(
        {"renderer": config.renderer_version, "font": config.font_identity, "text": text},
        separators=(",", ":"),
    ).encode()
    return _png(config.width, config.height, bytes(rows), metadata)


def validate_cover(data: bytes, *, config: TypographyConfig = DEFAULT_TYPOGRAPHY) -> str:
    info = validate_image_qa(data, "cover.png", expected_dimensions=(config.width, config.height))
    return info.sha256


def render_verified_cover(
    text: str,
    base_image: bytes,
    expected_base_digest: str,
    output_path: Path,
    *,
    config: TypographyConfig = DEFAULT_TYPOGRAPHY,
    renderer: Callable[..., bytes] = render_cover,
) -> str:
    """Render and reopen deterministic typography bound to exact base bytes."""
    if sha256(base_image).hexdigest() != expected_base_digest:
        raise TypographyError("TYPO005_STALE_BASE_IMAGE", "base image evidence is stale")
    if not config.font_identity or not config.renderer_version:
        raise TypographyError("TYPO002_FIXTURE_MISSING", "typography fixture is unavailable")
    try:
        rendered = renderer(text, config=config)
    except ValueError:
        raise
    except Exception as exc:
        raise TypographyError("TYPO003_RENDERER_FAILURE", "cover renderer failed") from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(rendered)
    reopened = output_path.read_bytes()
    if reopened != rendered:
        raise TypographyError("TYPO004_REOPEN_MISMATCH", "cover bytes changed after write")
    return validate_cover(reopened, config=config)


def _png(width: int, height: int, pixels: bytes, metadata: bytes) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"tEXt", b"audio_story\0" + metadata)
        + chunk(b"IDAT", zlib.compress(pixels, 9))
        + chunk(b"IEND", b"")
    )
