"""Deterministic OCR adapter for test-only image gates."""

from __future__ import annotations

import hashlib

from audio_story.adapters.ocr.base import (
    LocalOcrAdapter,
    OcrEvidence,
    OcrRequest,
    normalize_ocr_text,
)


class DeterministicMockOcr(LocalOcrAdapter):
    def inspect(self, request: OcrRequest, image_bytes: bytes) -> OcrEvidence:
        digest = hashlib.sha256(request.image_sha256.encode() + image_bytes).hexdigest()
        return OcrEvidence(normalize_ocr_text(""), 1.0, request.region, "mock-ocr-1.0", digest)
