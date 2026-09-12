"""Fail-closed local Tesseract TSV adapter."""

from __future__ import annotations

import csv
import io
import json
import subprocess
import time
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from threading import Event

from audio_story.adapters.ocr.base import (
    LocalOcrAdapter,
    OcrAdapterError,
    OcrEvidence,
    OcrRequest,
    compute_evidence_digest,
    normalize_ocr_text,
)
from audio_story.validation.errors import ValidationError
from audio_story.validation.images import validate_png

_TSV_FIELDS = (
    "level",
    "page_num",
    "block_num",
    "par_num",
    "line_num",
    "word_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
)


@dataclass(frozen=True, slots=True)
class TesseractConfig:
    executable: Path
    executable_sha256: str
    engine_version: str
    tessdata_dir: Path
    language_model_digests: tuple[tuple[str, str], ...]
    page_segmentation_mode: int = 6
    adapter_version: str = "M6B-TESSERACT-1.0"
    cleanup_timeout_seconds: float = 2.0
    stderr_limit_bytes: int = 16_384
    stdout_limit_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if not self.executable.is_file() or not self.tessdata_dir.is_dir():
            raise OcrAdapterError("OCR009_DEPENDENCY_MISSING", "Tesseract dependency is missing")
        if not _is_digest(self.executable_sha256) or not self.engine_version.strip():
            raise OcrAdapterError("OCR008_REQUEST_INVALID", "engine binding is invalid")
        if not self.language_model_digests:
            raise OcrAdapterError("OCR009_DEPENDENCY_MISSING", "language models are required")
        names = [name for name, _ in self.language_model_digests]
        if len(names) != len(set(names)) or any(
            not name or not _is_digest(digest) for name, digest in self.language_model_digests
        ):
            raise OcrAdapterError("OCR008_REQUEST_INVALID", "language model binding is invalid")
        if self.page_segmentation_mode < 0 or self.cleanup_timeout_seconds <= 0:
            raise OcrAdapterError("OCR008_REQUEST_INVALID", "Tesseract limits are invalid")
        if self.stderr_limit_bytes <= 0 or self.stdout_limit_bytes <= 0:
            raise OcrAdapterError("OCR008_REQUEST_INVALID", "output limit is invalid")


class TesseractOcrAdapter(LocalOcrAdapter):
    """Run a pinned Tesseract executable without a shell or network access."""

    def __init__(self, config: TesseractConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[bytes] | None = None

    def inspect(
        self,
        request: OcrRequest,
        image_bytes: bytes,
        cancellation: Event | None = None,
    ) -> OcrEvidence:
        token = cancellation or Event()
        if token.is_set():
            raise OcrAdapterError("OCR010_CANCELLED", "local OCR cancelled")
        self._verify_dependencies(request.languages)
        if sha256(image_bytes).hexdigest() != request.image_sha256:
            raise OcrAdapterError("OCR005_STALE_IMAGE_DIGEST", "OCR input digest is stale")
        try:
            png = validate_png(image_bytes, request.page_identity)
        except ValidationError as exc:
            raise OcrAdapterError("OCR014_IMAGE_INVALID", "OCR input PNG is invalid") from exc
        if (
            request.image_dimensions is not None
            and (png.width, png.height) != request.image_dimensions
        ):
            raise OcrAdapterError("OCR014_IMAGE_INVALID", "OCR image dimensions changed")
        if request.region[2] > png.width or request.region[3] > png.height:
            raise OcrAdapterError("OCR014_IMAGE_INVALID", "OCR region exceeds image dimensions")

        configured_models = dict(self.config.language_model_digests)
        selected_models = tuple(
            (language, configured_models[language]) for language in request.languages
        )
        request_digest = _request_digest(request, self.config, selected_models)
        started = time.monotonic()
        stdout = self._run(image_bytes, request, token)
        if token.is_set():
            raise OcrAdapterError("OCR010_CANCELLED", "local OCR cancelled")
        text, confidence, locator = _parse_tsv(stdout, request, (png.width, png.height))
        normalized = normalize_ocr_text(text)
        result_digest = sha256(normalized.encode("utf-8")).hexdigest()
        provisional = OcrEvidence(
            normalized,
            confidence,
            locator,
            f"tesseract:{self.config.executable_sha256}",
            "",
            engine_version=self.config.engine_version,
            language_model_digests=selected_models,
            request_digest=request_digest,
            normalized_result_digest=result_digest,
            duration_ms=int((time.monotonic() - started) * 1000),
            page_identity=request.page_identity,
            adapter_version=self.config.adapter_version,
            bound_image_sha256=request.image_sha256,
            bound_region=request.region,
            bound_languages=request.languages,
        )
        return replace(provisional, evidence_digest=compute_evidence_digest(provisional))

    def _verify_dependencies(self, languages: tuple[str, ...]) -> None:
        if _file_digest(self.config.executable) != self.config.executable_sha256:
            raise OcrAdapterError("OCR011_DEPENDENCY_DIGEST", "Tesseract executable changed")
        configured = dict(self.config.language_model_digests)
        if any(language not in configured for language in languages):
            raise OcrAdapterError("OCR009_DEPENDENCY_MISSING", "requested language is not pinned")
        for language in languages:
            model = self.config.tessdata_dir / f"{language}.traineddata"
            if not model.is_file():
                raise OcrAdapterError("OCR009_DEPENDENCY_MISSING", "language model is missing")
            if _file_digest(model) != configured[language]:
                raise OcrAdapterError("OCR011_DEPENDENCY_DIGEST", "language model changed")

    def _run(self, image_bytes: bytes, request: OcrRequest, cancellation: Event) -> bytes:
        command = [
            str(self.config.executable),
            "stdin",
            "stdout",
            "--tessdata-dir",
            str(self.config.tessdata_dir),
            "-l",
            "+".join(request.languages),
            "--psm",
            str(self.config.page_segmentation_mode),
            "tsv",
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            deadline = time.monotonic() + request.timeout_seconds
            process_input: bytes | None = image_bytes
            while True:
                if cancellation.is_set():
                    self._cleanup()
                    raise OcrAdapterError("OCR010_CANCELLED", "local OCR cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._cleanup()
                    raise OcrAdapterError("OCR006_ENGINE_TIMEOUT", "local OCR timed out")
                try:
                    stdout, stderr = self._process.communicate(
                        process_input, timeout=min(0.05, remaining)
                    )
                    break
                except subprocess.TimeoutExpired:
                    process_input = None
            if (
                len(stderr) > self.config.stderr_limit_bytes
                or len(stdout) > self.config.stdout_limit_bytes
            ):
                raise OcrAdapterError("OCR012_OUTPUT_LIMIT", "Tesseract output exceeded limit")
            if self._process.returncode:
                raise OcrAdapterError("OCR013_NON_ZERO_EXIT", "Tesseract exited unsuccessfully")
            if not stdout:
                raise OcrAdapterError("OCR015_TSV_MALFORMED", "Tesseract TSV is empty")
            return stdout
        except OcrAdapterError:
            raise
        except OSError as exc:
            raise OcrAdapterError("OCR007_ENGINE_FAILURE", "Tesseract process failed") from exc
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        process = self._process
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.config.cleanup_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.config.cleanup_timeout_seconds)
        except (OSError, subprocess.SubprocessError) as exc:
            raise OcrAdapterError("OCR018_PROCESS_CLEANUP", "Tesseract cleanup failed") from exc
        finally:
            self._process = None


def _parse_tsv(
    data: bytes,
    request: OcrRequest,
    image_dimensions: tuple[int, int],
) -> tuple[str, float, tuple[int, int, int, int]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OcrAdapterError("OCR015_TSV_MALFORMED", "Tesseract TSV is not UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    if tuple(reader.fieldnames or ()) != _TSV_FIELDS:
        raise OcrAdapterError("OCR015_TSV_MALFORMED", "Tesseract TSV header is invalid")
    words: list[str] = []
    confidences: list[float] = []
    boxes: list[tuple[int, int, int, int]] = []
    try:
        for row in reader:
            if None in row or any(row[field] is None for field in _TSV_FIELDS):
                raise ValueError("truncated row")
            page = int(row["page_num"])
            level = int(row["level"])
            confidence = float(row["conf"])
            left = int(row["left"])
            top = int(row["top"])
            width = int(row["width"])
            height = int(row["height"])
            if page != 1:
                raise OcrAdapterError("OCR016_PAGE_IDENTITY", "unexpected Tesseract page")
            value = normalize_ocr_text(row["text"])
            if level != 5 or not value:
                continue
            if not 0.0 <= confidence <= 100.0:
                raise ValueError("invalid word evidence")
            if width <= 0 or height <= 0:
                raise OcrAdapterError("OCR003_BOUNDING_BOX_INVALID", "Tesseract box is invalid")
            box = (left, top, left + width, top + height)
            rx1, ry1, rx2, ry2 = request.region
            image_width, image_height = image_dimensions
            if box[0] < 0 or box[1] < 0 or box[2] > image_width or box[3] > image_height:
                raise OcrAdapterError("OCR003_BOUNDING_BOX_INVALID", "Tesseract box exceeds image")
            if box[0] < rx1 or box[1] < ry1 or box[2] > rx2 or box[3] > ry2:
                continue
            words.append(value)
            confidences.append(confidence / 100.0)
            boxes.append(box)
    except (KeyError, TypeError, ValueError) as exc:
        raise OcrAdapterError("OCR015_TSV_MALFORMED", "Tesseract TSV row is invalid") from exc
    if not words:
        return "", 1.0, request.region
    locator = (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
    return " ".join(words), sum(confidences) / len(confidences), locator


def _request_digest(
    request: OcrRequest,
    config: TesseractConfig,
    selected_models: tuple[tuple[str, str], ...],
) -> str:
    payload = {
        "adapter_version": config.adapter_version,
        "engine_sha256": config.executable_sha256,
        "image_dimensions": list(request.image_dimensions) if request.image_dimensions else None,
        "image_sha256": request.image_sha256,
        "language_model_digests": list(selected_models),
        "languages": list(request.languages),
        "page_identity": request.page_identity,
        "region": list(request.region),
    }
    return sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
