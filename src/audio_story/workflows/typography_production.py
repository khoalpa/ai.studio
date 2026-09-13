"""Digest-bound local production typography renderer."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from audio_story.workflows.typography import TypographyError


@dataclass(frozen=True, slots=True)
class ProductionTypographyConfig:
    font_path: Path
    font_sha256: str
    font_identity: str
    font_license: str
    font_size: int = 64
    safe_margin: int = 64

    def validate(self) -> None:
        if not self.font_path.is_file():
            raise TypographyError("TYPO002_FIXTURE_MISSING", "production font is missing")
        if sha256(self.font_path.read_bytes()).hexdigest() != self.font_sha256:
            raise TypographyError("TYPO006_FONT_DIGEST", "production font digest changed")
        if not self.font_identity.strip() or not self.font_license.strip() or self.font_size <= 0:
            raise TypographyError("TYPO002_FIXTURE_MISSING", "font provenance is incomplete")


def render_production_cover(
    base_image: bytes, text: str, config: ProductionTypographyConfig
) -> bytes:
    """Render centered text inside deterministic safe margins and return PNG bytes."""
    config.validate()
    try:
        image = Image.open(BytesIO(base_image)).convert("RGB")
        font = ImageFont.truetype(str(config.font_path), config.font_size)
    except Exception as exc:
        raise TypographyError("TYPO003_RENDERER_FAILURE", "production renderer failed") from exc
    draw = ImageDraw.Draw(image)
    box = draw.textbbox((0, 0), text, font=font)
    width, height = box[2] - box[0], box[3] - box[1]
    if (
        not text
        or width > image.width - 2 * config.safe_margin
        or height > image.height - 2 * config.safe_margin
    ):
        raise TypographyError("TYPO001_TEXT_LAYOUT", "text exceeds production safe margins")
    position = ((image.width - width) // 2, image.height - config.safe_margin - height)
    draw.text(
        position, text, font=font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0)
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def verify_production_repeatability(
    base_image: bytes, text: str, config: ProductionTypographyConfig
) -> str:
    first = render_production_cover(base_image, text, config)
    second = render_production_cover(base_image, text, config)
    if first != second:
        raise TypographyError("TYPO007_NOT_REPEATABLE", "production renderer is not repeatable")
    return sha256(first).hexdigest()
