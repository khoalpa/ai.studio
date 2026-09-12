"""Local OCR adapter API."""

from audio_story.adapters.ocr.base import (
    LocalOcrAdapter,
    OcrAdapterError,
    OcrEvidence,
    OcrRequest,
    inspect_ocr,
    normalize_ocr_text,
    validate_ocr_evidence,
)
from audio_story.adapters.ocr.mock import DeterministicMockOcr

__all__ = [
    "DeterministicMockOcr",
    "LocalOcrAdapter",
    "OcrAdapterError",
    "OcrEvidence",
    "OcrRequest",
    "inspect_ocr",
    "normalize_ocr_text",
    "validate_ocr_evidence",
]
