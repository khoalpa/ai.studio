from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

import pytest

from audio_story.adapters.ocr import OcrRequest, TesseractConfig, TesseractOcrAdapter, inspect_ocr
from audio_story.validation.images import validate_png


@pytest.mark.local_ocr
def test_pinned_local_tesseract_fixture() -> None:
    """Explicit production smoke; skips unless every binding is supplied."""
    names = (
        "AUDIO_STORY_TESSERACT_SMOKE_EXE",
        "AUDIO_STORY_TESSERACT_SMOKE_EXE_SHA256",
        "AUDIO_STORY_TESSERACT_SMOKE_VERSION",
        "AUDIO_STORY_TESSERACT_SMOKE_TESSDATA",
        "AUDIO_STORY_TESSERACT_SMOKE_MODEL_DIGESTS",
        "AUDIO_STORY_TESSERACT_SMOKE_FIXTURE",
        "AUDIO_STORY_TESSERACT_SMOKE_FIXTURE_SHA256",
        "AUDIO_STORY_TESSERACT_SMOKE_EXPECTED_TEXT",
    )
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.skip("local OCR smoke is not configured: " + ", ".join(missing))
    executable = Path(os.environ[names[0]])
    tessdata = Path(os.environ[names[3]])
    fixture = Path(os.environ[names[5]])
    image = fixture.read_bytes()
    assert sha256(image).hexdigest() == os.environ[names[6]]
    info = validate_png(image, fixture.name)
    model_digests = tuple(
        sorted(
            (str(name), str(digest)) for name, digest in json.loads(os.environ[names[4]]).items()
        )
    )
    config = TesseractConfig(
        executable,
        os.environ[names[1]],
        os.environ[names[2]],
        tessdata,
        model_digests,
    )
    request = OcrRequest(
        info.sha256,
        (0, 0, info.width, info.height),
        (info.width, info.height),
        fixture.name,
        tuple(name for name, _ in model_digests if name != "osd"),
    )
    evidence = inspect_ocr(config_adapter := TesseractOcrAdapter(config), request, image)
    assert config_adapter.config.executable == executable
    assert evidence.normalized_text == os.environ[names[7]]
    assert evidence.engine_version == os.environ[names[2]]
    assert evidence.language_model_digests == tuple(
        binding for binding in model_digests if binding[0] != "osd"
    )
    assert len(evidence.request_digest) == 64
    assert len(evidence.normalized_result_digest) == 64
