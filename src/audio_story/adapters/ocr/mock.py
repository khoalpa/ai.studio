"""Deterministic OCR adapter for test-only image gates."""

from __future__ import annotations

import hashlib
from threading import Event

from audio_story.adapters.ocr.base import (
    LocalOcrAdapter,
    OcrEvidence,
    OcrRequest,
    normalize_ocr_text,
)


class DeterministicMockOcr(LocalOcrAdapter):
    def inspect(
        self,
        request: OcrRequest,
        image_bytes: bytes,
        cancellation: Event | None = None,
    ) -> OcrEvidence:
        if cancellation is not None and cancellation.is_set():
            raise TimeoutError("mock OCR cancelled")
        digest = hashlib.sha256(request.image_sha256.encode() + image_bytes).hexdigest()
        return OcrEvidence(
            normalize_ocr_text(""),
            1.0,
            request.region,
            "mock-ocr-1.0",
            digest,
            engine_version="1.0",
            request_digest=digest,
            normalized_result_digest=hashlib.sha256(b"").hexdigest(),
            page_identity=request.page_identity,
        )
