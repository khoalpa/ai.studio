from __future__ import annotations

import base64
import json
import urllib.error
from hashlib import sha256
from threading import Event

import pytest

from audio_story.adapters.image import (
    ComfyUIConfig,
    DeterministicMockImageAdapter,
    ImageAdapterError,
    ImageRequest,
    gpu_job,
    recover_policy_prompt,
)
from audio_story.adapters.image.comfyui import ComfyUIImageAdapter, _RejectRedirect
from audio_story.adapters.ocr import (
    DeterministicMockOcr,
    LocalOcrAdapter,
    OcrAdapterError,
    OcrEvidence,
    OcrRequest,
    inspect_ocr,
    normalize_ocr_text,
    validate_ocr_evidence,
)
from audio_story.config import ConfigurationError
from audio_story.validation.images import validate_image_qa, validate_png
from audio_story.workflows.package_quarantine import ImageManifestEntry, validate_image_package
from audio_story.workflows.typography import (
    TypographyConfig,
    TypographyError,
    render_cover,
    render_verified_cover,
    validate_cover,
)


def request(**changes: object) -> ImageRequest:
    values: dict[str, object] = {
        "basename": "landscape_0001.png",
        "prompt_digest": "a" * 64,
        "workflow_digest": "b" * 64,
        "model_identity": "mock-model",
        "seed": 7,
        "requested_output_count": 1,
        "requested_width": 32,
        "requested_height": 16,
        "output_format": "PNG",
        "timeout_seconds": 1.0,
        "transaction_id": "tx-1",
        "generation_call_id": "call-1",
    }
    values.update(changes)
    return ImageRequest(**values)  # type: ignore[arg-type]


def test_mock_is_deterministic_and_png_roundtrips() -> None:
    adapter = DeterministicMockImageAdapter()
    first = adapter.generate_image(request(), Event())
    second = adapter.generate_image(request(), Event())
    assert first.content == second.content
    info = validate_png(
        first.content,
        "landscape_0001.png",
        expected_dimensions=(32, 16),
        required_metadata_key="audio_story",
    )
    assert info.metadata["audio_story"]["provenance"] == "TEST_ONLY_M6_MOCK"  # type: ignore[index]
    assert adapter.health()["backend"] == "deterministic-mock"
    assert adapter.capabilities()["network"] is False
    assert (
        validate_image_qa(
            first.content, "landscape_0001.png", expected_dimensions=(32, 16), expected_ratio=2.0
        ).sha256
        == info.sha256
    )
    with pytest.raises(Exception, match="IMG_QA002_RATIO"):
        validate_image_qa(
            first.content, "landscape_0001.png", expected_dimensions=(32, 16), expected_ratio=1.0
        )


def test_image_request_single_canvas_and_cancellation_guards() -> None:
    with pytest.raises(ImageAdapterError, match="IMG001_SINGLE_RESPONSE_REQUIRED"):
        request(requested_output_count=2)
    with pytest.raises(ImageAdapterError, match="IMG002_INVALID_CANVAS"):
        request(requested_width=0)
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ImageAdapterError, match="IMG004_CANCELLED"):
        DeterministicMockImageAdapter().generate_image(request(), cancelled)


def test_comfyui_config_is_loopback_only_and_mock_ocr_is_normalized() -> None:
    with pytest.raises(ConfigurationError):
        ComfyUIConfig("http://192.168.0.1:8188")
    evidence = DeterministicMockOcr().inspect(OcrRequest("a" * 64, (0, 0, 10, 10)), b"png")
    assert evidence.normalized_text == ""
    assert len(evidence.evidence_digest) == 64


def test_comfyui_redirect_is_rejected() -> None:
    with pytest.raises(ImageAdapterError, match="IMG006_REDIRECT_REJECTED"):
        _RejectRedirect().redirect_request()


def test_comfyui_single_output_transport_and_cardinality(monkeypatch: pytest.MonkeyPatch) -> None:
    png = DeterministicMockImageAdapter().generate_image(request(), Event()).content

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"images": [base64.b64encode(png).decode()]}).encode()

    class Opener:
        def open(self, request: object, timeout: float) -> Response:
            return Response()

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    adapter = ComfyUIImageAdapter(ComfyUIConfig(timeout_seconds=1))
    result = adapter.generate_image(request(), Event())
    assert result.content == png
    assert adapter.health()["backend"] == "comfyui-loopback"
    assert adapter.capabilities()["single_response"] is True
    adapter.cancel("call-1")
    with pytest.raises(ImageAdapterError, match="IMG004_CANCELLED"):
        adapter.generate_image(request(), Event())
    adapter.unload()


def test_comfyui_transport_rejects_empty_fanout_and_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.body

    class Opener:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def open(self, request: object, timeout: float) -> Response:
            return Response(self.body)

    png = DeterministicMockImageAdapter().generate_image(request(), Event()).content
    for body, code in (
        (b"", "IMG009_EMPTY_OUTPUT"),
        (json.dumps({"images": []}).encode(), "IMG010_OUTPUT_CARDINALITY"),
        (json.dumps({"images": ["not-base64"]}).encode(), "IMG011_TRUNCATED_OUTPUT"),
        (png, None),
    ):
        monkeypatch.setattr("urllib.request.build_opener", lambda *args, _body=body: Opener(_body))
        adapter = ComfyUIImageAdapter(ComfyUIConfig())
        if code is None:
            assert adapter.generate_image(request(), Event()).content == png
        else:
            with pytest.raises(ImageAdapterError, match=code):
                adapter.generate_image(request(), Event())

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener(b"{}"))
    cancellation = Event()
    cancellation.set()
    with pytest.raises(ImageAdapterError, match="IMG004_CANCELLED"):
        ComfyUIImageAdapter(ComfyUIConfig()).generate_image(request(), cancellation)
    with pytest.raises(ValueError, match="positive"):
        ComfyUIConfig(timeout_seconds=0)


def test_comfyui_http_and_backend_failures_are_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingOpener:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def open(self, request: object, timeout: float) -> object:
            raise self.error

    for error, code in (
        (
            urllib.error.HTTPError("http://127.0.0.1", 500, "fail", {}, None),
            "IMG007_BACKEND_FAILURE",
        ),
        (urllib.error.URLError("offline"), "IMG008_TIMEOUT_OR_BACKEND"),
    ):
        monkeypatch.setattr(
            "urllib.request.build_opener", lambda *args, _error=error: FailingOpener(_error)
        )
        with pytest.raises(ImageAdapterError, match=code):
            ComfyUIImageAdapter(ComfyUIConfig()).generate_image(request(), Event())


def test_policy_recovery_changes_risk_axis_and_exhausts() -> None:
    safe, evidence = recover_policy_prompt("cover.png", "portrait", attempt_index=0)
    assert safe != "portrait"
    assert evidence.changed_risk_axes == ("lighting",)
    blocked, terminal = recover_policy_prompt("cover.png", safe, attempt_index=2)
    assert blocked == safe
    assert terminal.outcome == "POLICY_BLOCKED"


def test_gpu_job_releases_semaphore_after_exception() -> None:
    with pytest.raises(RuntimeError), gpu_job():
        raise RuntimeError("oom")
    with gpu_job():
        pass
    assert normalize_ocr_text("  A\u0301   B ") == "Á B"


def test_ocr_confidence_box_digest_and_stale_input_fail_closed() -> None:
    image = b"exact-image"
    request_value = OcrRequest(sha256(image).hexdigest(), (0, 0, 20, 10))
    valid = OcrEvidence("", 0.9, (1, 1, 19, 9), "fixture", "a" * 64)
    validate_ocr_evidence(request_value, valid, image, minimum_confidence=0.8)
    cases = (
        (valid, b"changed", 0.8, "OCR005_STALE_IMAGE_DIGEST"),
        (valid, image, 1.1, "OCR001_CONFIDENCE_POLICY"),
        (OcrEvidence("", 1.1, valid.locator, "fixture", "a" * 64), image, 0.8, "OCR002"),
        (OcrEvidence("", 0.2, valid.locator, "fixture", "a" * 64), image, 0.8, "OCR002"),
        (OcrEvidence("", 0.9, (4, 4, 3, 9), "fixture", "a" * 64), image, 0.8, "OCR003"),
        (OcrEvidence("", 0.9, (0, 0, 21, 9), "fixture", "a" * 64), image, 0.8, "OCR003"),
        (OcrEvidence("", 0.9, valid.locator, "fixture", "bad"), image, 0.8, "OCR004"),
        (
            OcrEvidence("A  B", 0.9, valid.locator, "fixture", "a" * 64),
            image,
            0.8,
            "OCR017",
        ),
        (
            OcrEvidence("", 0.9, valid.locator, "fixture", "a" * 64, page_identity="other"),
            image,
            0.8,
            "OCR016",
        ),
    )
    for evidence, content, minimum, code in cases:
        with pytest.raises(OcrAdapterError, match=code):
            validate_ocr_evidence(request_value, evidence, content, minimum_confidence=minimum)


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (TimeoutError("slow"), "OCR006_ENGINE_TIMEOUT"),
        (RuntimeError("boom"), "OCR007_ENGINE_FAILURE"),
    ],
)
def test_ocr_engine_timeout_and_exception_are_stable(failure: Exception, code: str) -> None:
    class FailingOcr(LocalOcrAdapter):
        def inspect(self, request: OcrRequest, image_bytes: bytes) -> OcrEvidence:
            raise failure

    image = b"image"
    with pytest.raises(OcrAdapterError, match=code):
        inspect_ocr(
            FailingOcr(),
            OcrRequest(sha256(image).hexdigest(), (0, 0, 10, 10)),
            image,
        )


def test_typography_failure_and_stale_evidence_corpus(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = b"base-image"
    digest = sha256(base).hexdigest()
    output = tmp_path / "cover.png"
    assert render_verified_cover("TEST", base, digest, output)
    with pytest.raises(ValueError, match="TYPO001_TEXT_LAYOUT"):
        render_verified_cover("TOO LONG", base, digest, output, config=TypographyConfig(width=32))
    with pytest.raises(TypographyError, match="TYPO002_FIXTURE_MISSING"):
        render_verified_cover(
            "TEST", base, digest, output, config=TypographyConfig(font_identity="")
        )

    def fail_renderer(text: str, *, config: TypographyConfig) -> bytes:
        raise RuntimeError("renderer failed")

    with pytest.raises(TypographyError, match="TYPO003_RENDERER_FAILURE"):
        render_verified_cover("TEST", base, digest, output, renderer=fail_renderer)
    with pytest.raises(TypographyError, match="TYPO005_STALE_BASE_IMAGE"):
        render_verified_cover("TEST", base + b"changed", digest, output)

    original_read = type(output).read_bytes

    def corrupt_reopen(path):  # type: ignore[no-untyped-def]
        value = original_read(path)
        return value + b"changed" if path == output else value

    monkeypatch.setattr(type(output), "read_bytes", corrupt_reopen)
    with pytest.raises(TypographyError, match="TYPO004_REOPEN_MISMATCH"):
        render_verified_cover("TEST", base, digest, output)


def test_deterministic_typography_and_package_quarantine() -> None:
    cover = render_cover("TEST")
    assert cover == render_cover("TEST")
    assert validate_cover(cover)
    entry = ImageManifestEntry(
        "a.png",
        "STAGE1",
        "char",
        "a" * 64,
        10,
        "AUTHORITATIVE",
        "images/a.png",
        transaction_id="tx",
        generation_call_id="call",
        evidence_digest="b" * 64,
    )
    validate_image_package((entry,), ("a.png",))
    with pytest.raises(ValueError, match="PKG003"):
        validate_image_package(
            (entry.__class__("a.png", "STAGE1", "char", "a" * 64, 10, "DRAFT_ONLY"),), ("a.png",)
        )
