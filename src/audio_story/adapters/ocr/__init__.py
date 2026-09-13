"""Local OCR adapter API."""

from audio_story.adapters.ocr.base import (
    LocalOcrAdapter,
    OcrAdapterError,
    OcrEvidence,
    OcrRequest,
    compute_evidence_digest,
    inspect_ocr,
    normalize_ocr_text,
    residual_text_detected,
    validate_ocr_evidence,
)
from audio_story.adapters.ocr.mock import DeterministicMockOcr
from audio_story.adapters.ocr.tesseract import TesseractConfig, TesseractOcrAdapter

__all__ = [
    "DeterministicMockOcr",
    "LocalOcrAdapter",
    "OcrAdapterError",
    "OcrEvidence",
    "OcrRequest",
    "compute_evidence_digest",
    "TesseractConfig",
    "TesseractOcrAdapter",
    "inspect_ocr",
    "normalize_ocr_text",
    "residual_text_detected",
    "validate_ocr_evidence",
]
