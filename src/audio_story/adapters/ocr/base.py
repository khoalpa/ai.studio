"""Backend-neutral local OCR evidence contract."""

from __future__ import annotations

import json
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256
from threading import Event


@dataclass(frozen=True, slots=True)
class OcrRequest:
    image_sha256: str
    region: tuple[int, int, int, int]
    image_dimensions: tuple[int, int] | None = None
    page_identity: str = "page-1"
    languages: tuple[str, ...] = ("eng",)
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if len(self.image_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.image_sha256
        ):
            raise OcrAdapterError("OCR008_REQUEST_INVALID", "image digest is invalid")
        x1, y1, x2, y2 = self.region
        if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
            raise OcrAdapterError("OCR008_REQUEST_INVALID", "OCR region is invalid")
        if self.image_dimensions is not None:
            width, height = self.image_dimensions
            if width <= 0 or height <= 0 or x2 > width or y2 > height:
                raise OcrAdapterError("OCR008_REQUEST_INVALID", "image dimensions are invalid")
        if not self.page_identity.strip():
            raise OcrAdapterError("OCR008_REQUEST_INVALID", "page identity is required")
        if not self.languages or any(
            not language or not all(c.isascii() and (c.isalnum() or c in "_-") for c in language)
            for language in self.languages
        ):
            raise OcrAdapterError("OCR008_REQUEST_INVALID", "OCR languages are invalid")
        if self.timeout_seconds <= 0:
            raise OcrAdapterError("OCR008_REQUEST_INVALID", "timeout must be positive")


@dataclass(frozen=True, slots=True)
class OcrEvidence:
    normalized_text: str
    confidence: float
    locator: tuple[int, int, int, int]
    engine_identity: str
    evidence_digest: str
    engine_version: str = ""
    language_model_digests: tuple[tuple[str, str], ...] = ()
    request_digest: str = ""
    normalized_result_digest: str = ""
    duration_ms: int = 0
    termination_reason: str = "COMPLETED"
    page_identity: str = "page-1"
    adapter_version: str = ""
    bound_image_sha256: str = ""
    bound_region: tuple[int, int, int, int] | None = None
    bound_languages: tuple[str, ...] = ()


class LocalOcrAdapter(ABC):
    @abstractmethod
    def inspect(
        self,
        request: OcrRequest,
        image_bytes: bytes,
        cancellation: Event | None = None,
    ) -> OcrEvidence: ...


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
    cancellation: Event | None = None,
) -> OcrEvidence:
    """Run a local OCR engine and validate all returned evidence."""
    try:
        if cancellation is None:
            evidence = adapter.inspect(request, image_bytes)
        else:
            evidence = adapter.inspect(request, image_bytes, cancellation)
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
    if evidence.page_identity != request.page_identity:
        raise OcrAdapterError("OCR016_PAGE_IDENTITY", "OCR evidence page identity changed")
    if evidence.normalized_text != normalize_ocr_text(evidence.normalized_text):
        raise OcrAdapterError("OCR017_NORMALIZATION_INVALID", "OCR text is not normalized")
    if evidence.normalized_result_digest and (
        not _is_digest(evidence.normalized_result_digest)
        or evidence.normalized_result_digest
        != sha256(evidence.normalized_text.encode("utf-8")).hexdigest()
    ):
        raise OcrAdapterError("OCR004_EVIDENCE_DIGEST_INVALID", "OCR result digest is invalid")
    if evidence.request_digest and not _is_digest(evidence.request_digest):
        raise OcrAdapterError("OCR004_EVIDENCE_DIGEST_INVALID", "OCR request digest is invalid")
    if any(
        not language or not _is_digest(digest)
        for language, digest in evidence.language_model_digests
    ):
        raise OcrAdapterError("OCR004_EVIDENCE_DIGEST_INVALID", "OCR model binding is invalid")
    if evidence.adapter_version:
        if (
            evidence.bound_image_sha256 != request.image_sha256
            or evidence.bound_region != request.region
            or evidence.bound_languages != request.languages
        ):
            raise OcrAdapterError("OCR005_STALE_IMAGE_DIGEST", "OCR evidence binding is stale")
        if evidence.evidence_digest != compute_evidence_digest(evidence):
            raise OcrAdapterError("OCR004_EVIDENCE_DIGEST_INVALID", "OCR evidence digest is stale")


def normalize_ocr_text(text: str) -> str:
    return unicodedata.normalize("NFC", " ".join(text.split()))


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def compute_evidence_digest(evidence: OcrEvidence) -> str:
    """Canonical digest for production evidence that carries complete bindings."""
    payload = {
        "adapter_version": evidence.adapter_version,
        "bound_image_sha256": evidence.bound_image_sha256,
        "bound_languages": list(evidence.bound_languages),
        "bound_region": list(evidence.bound_region) if evidence.bound_region else None,
        "confidence": evidence.confidence,
        "engine_identity": evidence.engine_identity,
        "engine_version": evidence.engine_version,
        "language_model_digests": list(evidence.language_model_digests),
        "locator": list(evidence.locator),
        "normalized_result_digest": evidence.normalized_result_digest,
        "page_identity": evidence.page_identity,
        "request_digest": evidence.request_digest,
        "termination_reason": evidence.termination_reason,
    }
    return sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
