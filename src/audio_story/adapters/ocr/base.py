"""Backend-neutral local OCR evidence contract."""

from __future__ import annotations

import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class OcrRequest:
    image_sha256: str
    region: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class OcrEvidence:
    normalized_text: str
    confidence: float
    locator: tuple[int, int, int, int]
    engine_identity: str
    evidence_digest: str


class LocalOcrAdapter(ABC):
    @abstractmethod
    def inspect(self, request: OcrRequest, image_bytes: bytes) -> OcrEvidence: ...


class OcrAdapterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def inspect_ocr(
    adapter: LocalOcrAdapter,
    request: OcrRequest,
    image_bytes: bytes,
    *,
    minimum_confidence: float = 0.0,
) -> OcrEvidence:
    """Run a local OCR engine and validate all returned evidence."""
    try:
        evidence = adapter.inspect(request, image_bytes)
    except TimeoutError as exc:
        raise OcrAdapterError("OCR006_ENGINE_TIMEOUT", "local OCR timed out") from exc
    except OcrAdapterError:
        raise
    except Exception as exc:
        raise OcrAdapterError("OCR007_ENGINE_FAILURE", "local OCR failed") from exc
    validate_ocr_evidence(
        request,
        evidence,
        image_bytes,
        minimum_confidence=minimum_confidence,
    )
    return evidence


def validate_ocr_evidence(
    request: OcrRequest,
    evidence: OcrEvidence,
    image_bytes: bytes,
    *,
    minimum_confidence: float = 0.0,
) -> None:
    """Fail closed on stale bytes, malformed boxes, confidence or digests."""
    if sha256(image_bytes).hexdigest() != request.image_sha256:
        raise OcrAdapterError("OCR005_STALE_IMAGE_DIGEST", "OCR input digest is stale")
    if not 0.0 <= minimum_confidence <= 1.0:
        raise OcrAdapterError("OCR001_CONFIDENCE_POLICY", "confidence policy is invalid")
    if not 0.0 <= evidence.confidence <= 1.0 or evidence.confidence < minimum_confidence:
        raise OcrAdapterError("OCR002_CONFIDENCE_INVALID", "OCR confidence is outside policy")
    x1, y1, x2, y2 = evidence.locator
    rx1, ry1, rx2, ry2 = request.region
    if x1 < rx1 or y1 < ry1 or x2 > rx2 or y2 > ry2 or x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
        raise OcrAdapterError("OCR003_BOUNDING_BOX_INVALID", "OCR locator is malformed")
    if len(evidence.evidence_digest) != 64 or any(
        character not in "0123456789abcdef" for character in evidence.evidence_digest
    ):
        raise OcrAdapterError("OCR004_EVIDENCE_DIGEST_INVALID", "OCR evidence digest is invalid")


def normalize_ocr_text(text: str) -> str:
    return unicodedata.normalize("NFC", " ".join(text.split()))
