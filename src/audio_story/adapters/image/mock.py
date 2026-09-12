"""Deterministic test-only local image backend."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from threading import Event

from audio_story.adapters.image.base import (
    ImageAdapterError,
    ImageRequest,
    ImageResponse,
    LocalImageAdapter,
)


class DeterministicMockImageAdapter(LocalImageAdapter):
    adapter_version = "M6-MOCK-1.0"

    def generate_image(self, request: ImageRequest, cancellation: Event) -> ImageResponse:
        if cancellation.is_set():
            raise ImageAdapterError("IMG004_CANCELLED", "image request cancelled")
        if request.output_format.upper() != "PNG":
            raise ImageAdapterError("IMG005_FORMAT_UNSUPPORTED", "mock supports PNG only")
        color = hashlib.sha256(f"{request.prompt_digest}:{request.seed}".encode()).digest()[:3]
        row = b"\x00" + color * request.requested_width
        raw = row * request.requested_height
        metadata = json.dumps(
            {"provenance": "TEST_ONLY_M6_MOCK", "basename": request.basename},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        png = (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(
                b"IHDR",
                struct.pack(
                    ">IIBBBBB", request.requested_width, request.requested_height, 8, 2, 0, 0, 0
                ),
            )
            + _chunk(b"tEXt", b"audio_story\x00" + metadata)
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b"")
        )
        return ImageResponse(
            png,
            request.model_identity,
            self.adapter_version,
            0,
            request.workflow_digest,
            request.seed,
        )

    def health(self) -> dict[str, str]:
        return {"status": "READY", "backend": "deterministic-mock"}

    def capabilities(self) -> dict[str, object]:
        return {
            "backend": "deterministic-mock",
            "gpu": False,
            "network": False,
            "single_response": True,
        }

    def cancel(self, generation_call_id: str) -> None:
        return None

    def unload(self) -> None:
        return None


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
