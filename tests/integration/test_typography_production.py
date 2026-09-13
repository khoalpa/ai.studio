from hashlib import sha256
from pathlib import Path

import pytest

from audio_story.adapters.image import DeterministicMockImageAdapter, ImageRequest
from audio_story.workflows.typography import TypographyError
from audio_story.workflows.typography_production import (
    ProductionTypographyConfig,
    render_production_cover,
    verify_production_repeatability,
)

FONT = Path(r"C:\Windows\Fonts\DejaVuSans.ttf")
FONT_DIGEST = "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954"


@pytest.mark.skipif(not FONT.is_file(), reason="pinned production font is unavailable")
def test_pinned_font_renderer_is_repeatable() -> None:
    request = ImageRequest(
        "base.png", "a" * 64, "b" * 64, "mock", 1, 1, 256, 256, "PNG", 1, "tx", "call"
    )
    base = (
        DeterministicMockImageAdapter()
        .generate_image(request, __import__("threading").Event())
        .content
    )
    config = ProductionTypographyConfig(
        FONT, FONT_DIGEST, "DejaVu Sans OS-installed", "USER_ATTESTED_OS_FONT", 20, 24
    )
    digest = verify_production_repeatability(base, "Chuyện kể", config)
    assert digest == sha256(render_production_cover(base, "Chuyện kể", config)).hexdigest()


def test_production_font_digest_drift_is_rejected(tmp_path: Path) -> None:
    missing = ProductionTypographyConfig(tmp_path / "missing.ttf", "0" * 64, "font", "license")
    with pytest.raises(TypographyError, match="TYPO002_FIXTURE_MISSING"):
        missing.validate()

    fake = tmp_path / "font.ttf"
    fake.write_bytes(b"not-a-font")
    drift = ProductionTypographyConfig(fake, "0" * 64, "font", "license")
    with pytest.raises(TypographyError, match="TYPO006_FONT_DIGEST"):
        drift.validate()


@pytest.mark.skipif(not FONT.is_file(), reason="pinned production font is unavailable")
def test_production_renderer_rejects_bad_image_and_layout() -> None:
    config = ProductionTypographyConfig(
        FONT, FONT_DIGEST, "DejaVu Sans OS-installed", "USER_ATTESTED_OS_FONT", 64, 64
    )
    with pytest.raises(TypographyError, match="TYPO003_RENDERER_FAILURE"):
        render_production_cover(b"not-png", "Title", config)

    request = ImageRequest(
        "base.png", "a" * 64, "b" * 64, "mock", 1, 1, 256, 256, "PNG", 1, "tx", "call"
    )
    base = (
        DeterministicMockImageAdapter()
        .generate_image(request, __import__("threading").Event())
        .content
    )
    with pytest.raises(TypographyError, match="TYPO001_TEXT_LAYOUT"):
        render_production_cover(base, "A title that cannot possibly fit", config)
