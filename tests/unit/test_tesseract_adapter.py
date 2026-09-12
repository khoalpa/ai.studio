from __future__ import annotations

import subprocess
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Event

import pytest

from audio_story.adapters.image import DeterministicMockImageAdapter, ImageRequest
from audio_story.adapters.ocr import (
    OcrAdapterError,
    OcrRequest,
    TesseractConfig,
    TesseractOcrAdapter,
    validate_ocr_evidence,
)


def _png() -> bytes:
    request = ImageRequest(
        "ocr.png", "a" * 64, "b" * 64, "mock", 1, 1, 32, 16, "PNG", 1, "tx", "call"
    )
    return DeterministicMockImageAdapter().generate_image(request, Event()).content


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _config(tmp_path: Path, **changes: object) -> TesseractConfig:
    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"exe")
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir(exist_ok=True)
    (tessdata / "eng.traineddata").write_bytes(b"eng")
    values: dict[str, object] = {
        "executable": executable,
        "executable_sha256": _digest(executable),
        "engine_version": "5.5.0",
        "tessdata_dir": tessdata,
        "language_model_digests": (("eng", _digest(tessdata / "eng.traineddata")),),
    }
    values.update(changes)
    return TesseractConfig(**values)  # type: ignore[arg-type]


def _request(image: bytes, **changes: object) -> OcrRequest:
    values: dict[str, object] = {
        "image_sha256": sha256(image).hexdigest(),
        "region": (0, 0, 32, 16),
        "image_dimensions": (32, 16),
        "page_identity": "cover.png",
        "languages": ("eng",),
        "timeout_seconds": 1.0,
    }
    values.update(changes)
    return OcrRequest(**values)  # type: ignore[arg-type]


def _tsv(*rows: str) -> bytes:
    header = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
        "left\ttop\twidth\theight\tconf\ttext"
    )
    return ("\n".join((header, *rows)) + "\n").encode()


class _Process:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode: int | None = returncode
        self.command: list[str] = []
        self.terminated = False
        self.killed = False

    def communicate(self, data: bytes | None, timeout: float) -> tuple[bytes, bytes]:
        return self.stdout, self.stderr

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float) -> int:
        return self.returncode or 0


def _install_process(
    monkeypatch: pytest.MonkeyPatch, process: _Process
) -> list[tuple[object, ...]]:
    calls: list[tuple[object, ...]] = []

    def popen(command: list[str], **kwargs: object) -> _Process:
        calls.append((command, kwargs))
        process.command = command
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    return calls


def test_tesseract_tsv_evidence_is_bound_and_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _png()
    process = _Process(
        _tsv(
            "5\t1\t1\t1\t1\t1\t2\t3\t8\t5\t90.0\tXin",
            "5\t1\t1\t1\t1\t2\t12\t3\t10\t5\t80.0\tchào",
        )
    )
    calls = _install_process(monkeypatch, process)
    adapter = TesseractOcrAdapter(_config(tmp_path))
    evidence = adapter.inspect(_request(image), image, Event())
    assert evidence.normalized_text == "Xin chào"
    assert evidence.confidence == pytest.approx(0.85)
    assert evidence.locator == (2, 3, 22, 8)
    assert evidence.engine_version == "5.5.0"
    assert evidence.language_model_digests[0][0] == "eng"
    assert evidence.page_identity == "cover.png"
    assert len(evidence.request_digest) == 64
    assert evidence.normalized_result_digest == sha256("Xin chào".encode()).hexdigest()
    assert len(evidence.evidence_digest) == 64
    validate_ocr_evidence(_request(image), evidence, image, minimum_confidence=0.8)
    with pytest.raises(OcrAdapterError, match="OCR004_EVIDENCE_DIGEST_INVALID"):
        validate_ocr_evidence(_request(image), replace(evidence, confidence=0.84), image)
    with pytest.raises(OcrAdapterError, match="OCR005_STALE_IMAGE_DIGEST"):
        validate_ocr_evidence(_request(image, region=(0, 0, 31, 16)), evidence, image)
    command, kwargs = calls[0]
    assert command[0].endswith("tesseract.exe")
    assert command[-1] == "tsv"
    assert kwargs["shell"] is False


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"", "OCR015_TSV_MALFORMED"),
        (b"wrong\theader\n", "OCR015_TSV_MALFORMED"),
        (_tsv("5\t1\t1"), "OCR015_TSV_MALFORMED"),
        (_tsv("5\t1\t1\t1\t1\t1\t1\t1\t2\t2\t90\tword\textra"), "OCR015_TSV_MALFORMED"),
        (b"\xff\xfe", "OCR015_TSV_MALFORMED"),
        (_tsv("5\t2\t1\t1\t1\t1\t1\t1\t2\t2\t90\tword"), "OCR016_PAGE_IDENTITY"),
        (_tsv("5\t1\t1\t1\t1\t1\t1\t1\t0\t2\t90\tword"), "OCR003_BOUNDING_BOX_INVALID"),
        (_tsv("5\t1\t1\t1\t1\t1\t31\t1\t2\t2\t90\tword"), "OCR003_BOUNDING_BOX_INVALID"),
        (_tsv("5\t1\t1\t1\t1\t1\t1\t1\t2\t2\t101\tword"), "OCR015_TSV_MALFORMED"),
    ],
)
def test_tesseract_rejects_malformed_tsv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes, code: str
) -> None:
    image = _png()
    _install_process(monkeypatch, _Process(body))
    with pytest.raises(OcrAdapterError, match=code):
        TesseractOcrAdapter(_config(tmp_path)).inspect(_request(image), image)


def test_tesseract_ignores_words_outside_region_and_reports_zero_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _png()
    body = _tsv("5\t1\t1\t1\t1\t1\t20\t2\t5\t4\t88\toutside")
    _install_process(monkeypatch, _Process(body))
    request = _request(image, region=(0, 0, 10, 10))
    evidence = TesseractOcrAdapter(_config(tmp_path)).inspect(request, image)
    assert evidence.normalized_text == ""
    assert evidence.confidence == 1.0
    assert evidence.locator == request.region


@pytest.mark.parametrize(
    ("stderr", "returncode", "code"),
    [
        (b"boom", 2, "OCR013_NON_ZERO_EXIT"),
        (b"x" * 20, 0, "OCR012_OUTPUT_LIMIT"),
    ],
)
def test_tesseract_process_failure_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stderr: bytes,
    returncode: int,
    code: str,
) -> None:
    image = _png()
    _install_process(monkeypatch, _Process(_tsv(), stderr, returncode))
    config = _config(tmp_path, stderr_limit_bytes=10)
    with pytest.raises(OcrAdapterError, match=code):
        TesseractOcrAdapter(config).inspect(_request(image), image)


def test_tesseract_stdout_limit_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _png()
    _install_process(monkeypatch, _Process(_tsv("5\t1\t1\t1\t1\t1\t1\t1\t2\t2\t90\tword")))
    with pytest.raises(OcrAdapterError, match="OCR012_OUTPUT_LIMIT"):
        TesseractOcrAdapter(_config(tmp_path, stdout_limit_bytes=10)).inspect(
            _request(image), image
        )


def test_tesseract_cancellation_terminates_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _png()
    cancellation = Event()
    process = _Process(_tsv())

    def communicate(data: bytes | None, timeout: float) -> tuple[bytes, bytes]:
        cancellation.set()
        raise subprocess.TimeoutExpired("tesseract", timeout)

    process.returncode = None
    process.communicate = communicate  # type: ignore[method-assign]
    _install_process(monkeypatch, process)
    with pytest.raises(OcrAdapterError, match="OCR010_CANCELLED"):
        TesseractOcrAdapter(_config(tmp_path)).inspect(_request(image), image, cancellation)
    assert process.terminated


def test_tesseract_cancellation_after_response_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _png()
    cancellation = Event()
    process = _Process(_tsv())

    def communicate(data: bytes | None, timeout: float) -> tuple[bytes, bytes]:
        cancellation.set()
        return process.stdout, process.stderr

    process.communicate = communicate  # type: ignore[method-assign]
    _install_process(monkeypatch, process)
    with pytest.raises(OcrAdapterError, match="OCR010_CANCELLED"):
        TesseractOcrAdapter(_config(tmp_path)).inspect(_request(image), image, cancellation)


def test_tesseract_timeout_kills_when_terminate_does_not_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _png()
    process = _Process(_tsv())
    process.returncode = None

    def communicate(data: bytes | None, timeout: float) -> tuple[bytes, bytes]:
        raise subprocess.TimeoutExpired("tesseract", timeout)

    waits = 0

    def wait(timeout: float) -> int:
        nonlocal waits
        waits += 1
        if waits == 1:
            raise subprocess.TimeoutExpired("tesseract", timeout)
        return -9

    process.communicate = communicate  # type: ignore[method-assign]
    process.wait = wait  # type: ignore[method-assign]
    _install_process(monkeypatch, process)
    with pytest.raises(OcrAdapterError, match="OCR006_ENGINE_TIMEOUT"):
        TesseractOcrAdapter(_config(tmp_path)).inspect(
            _request(image, timeout_seconds=0.001), image
        )
    assert process.terminated and process.killed


def test_tesseract_cleanup_failure_has_stable_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _png()
    cancellation = Event()
    process = _Process(_tsv())
    process.returncode = None

    def communicate(data: bytes | None, timeout: float) -> tuple[bytes, bytes]:
        cancellation.set()
        raise subprocess.TimeoutExpired("tesseract", timeout)

    def terminate() -> None:
        raise OSError("denied")

    process.communicate = communicate  # type: ignore[method-assign]
    process.terminate = terminate  # type: ignore[method-assign]
    _install_process(monkeypatch, process)
    with pytest.raises(OcrAdapterError, match="OCR018_PROCESS_CLEANUP"):
        TesseractOcrAdapter(_config(tmp_path)).inspect(_request(image), image, cancellation)


def test_tesseract_dependency_and_image_bindings_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _png()
    config = _config(tmp_path)
    adapter = TesseractOcrAdapter(config)
    (config.tessdata_dir / "eng.traineddata").write_bytes(b"changed-model")
    with pytest.raises(OcrAdapterError, match="OCR011_DEPENDENCY_DIGEST"):
        adapter.inspect(_request(image), image)

    config = _config(tmp_path)
    adapter = TesseractOcrAdapter(config)
    config.executable.write_bytes(b"changed")
    with pytest.raises(OcrAdapterError, match="OCR011_DEPENDENCY_DIGEST"):
        adapter.inspect(_request(image), image)

    config = _config(tmp_path)
    adapter = TesseractOcrAdapter(config)
    with pytest.raises(OcrAdapterError, match="OCR005_STALE_IMAGE_DIGEST"):
        adapter.inspect(_request(image), image + b"changed")
    with pytest.raises(OcrAdapterError, match="OCR014_IMAGE_INVALID"):
        adapter.inspect(_request(image, image_dimensions=(33, 16)), image)
    with pytest.raises(OcrAdapterError, match="OCR009_DEPENDENCY_MISSING"):
        adapter.inspect(_request(image, languages=("vie",)), image)
    _install_process(monkeypatch, _Process(_tsv()))


def test_tesseract_configuration_and_request_guards(tmp_path: Path) -> None:
    image = _png()
    with pytest.raises(OcrAdapterError, match="OCR009_DEPENDENCY_MISSING"):
        TesseractConfig(tmp_path / "missing", "a" * 64, "5", tmp_path, (("eng", "b" * 64),))
    config = _config(tmp_path)
    with pytest.raises(OcrAdapterError, match="OCR008_REQUEST_INVALID"):
        OcrRequest("bad", (0, 0, 1, 1))
    with pytest.raises(OcrAdapterError, match="OCR008_REQUEST_INVALID"):
        _request(image, region=(0, 0, 33, 16))
    with pytest.raises(OcrAdapterError, match="OCR008_REQUEST_INVALID"):
        _request(image, languages=("eng+vie",))
    with pytest.raises(OcrAdapterError, match="OCR008_REQUEST_INVALID"):
        TesseractConfig(
            config.executable,
            "bad",
            "5",
            config.tessdata_dir,
            config.language_model_digests,
        )
