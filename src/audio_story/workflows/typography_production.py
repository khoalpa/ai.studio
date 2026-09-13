"""Digest-bound local production typography renderer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from audio_story.validation.images import validate_image_qa
from audio_story.workflows.typography import TypographyError


@dataclass(frozen=True, slots=True)
class ProductionTypographyConfig:
    font_path: Path
    font_sha256: str
    font_identity: str
    font_license: str
    font_size: int = 64
    safe_margin: int = 64
    renderer_version: str = "M6B-PILLOW-1.0"

    def validate(self) -> None:
        if not self.font_path.is_file():
            raise TypographyError("TYPO002_FIXTURE_MISSING", "production font is missing")
        if sha256(self.font_path.read_bytes()).hexdigest() != self.font_sha256:
            raise TypographyError("TYPO006_FONT_DIGEST", "production font digest changed")
        if (
            not self.font_identity.strip()
            or not self.font_license.strip()
            or not self.renderer_version.strip()
            or self.font_size <= 0
        ):
            raise TypographyError("TYPO002_FIXTURE_MISSING", "font provenance is incomplete")


@dataclass(frozen=True, slots=True)
class ProductionTypographyEvidence:
    base_sha256: str
    font_sha256: str
    text_sha256: str
    final_sha256: str
    width: int
    height: int
    renderer_version: str


def _provenance(base_image: bytes, text: str, config: ProductionTypographyConfig) -> dict[str, str]:
    return {
        "base_sha256": sha256(base_image).hexdigest(),
        "font_identity": config.font_identity,
        "font_license": config.font_license,
        "font_sha256": config.font_sha256,
        "renderer_version": config.renderer_version,
        "text_sha256": sha256(text.encode("utf-8")).hexdigest(),
    }


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
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text(
        "audio_story",
        json.dumps(_provenance(base_image, text, config), sort_keys=True, separators=(",", ":")),
    )
    image.save(output, format="PNG", optimize=False, compress_level=9, pnginfo=pnginfo)
    return output.getvalue()


def verify_production_repeatability(
    base_image: bytes, text: str, config: ProductionTypographyConfig
) -> str:
    first = render_production_cover(base_image, text, config)
    second = render_production_cover(base_image, text, config)
    if first != second:
        raise TypographyError("TYPO007_NOT_REPEATABLE", "production renderer is not repeatable")
    return sha256(first).hexdigest()


def render_verified_production_cover(
    base_image: bytes,
    expected_base_sha256: str,
    text: str,
    output_path: Path,
    config: ProductionTypographyConfig,
) -> ProductionTypographyEvidence:
    """Render, persist, reopen and validate an exact digest-bound production PNG."""
    base_sha256 = sha256(base_image).hexdigest()
    if base_sha256 != expected_base_sha256:
        raise TypographyError("TYPO005_STALE_BASE_IMAGE", "base image digest changed")
    try:
        with Image.open(BytesIO(base_image)) as source:
            dimensions = source.size
        rendered = render_production_cover(base_image, text, config)
        if rendered != render_production_cover(base_image, text, config):
            raise TypographyError("TYPO007_NOT_REPEATABLE", "production renderer is not repeatable")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(rendered)
        reopened = output_path.read_bytes()
        if reopened != rendered:
            raise TypographyError("TYPO004_POSTWRITE_MISMATCH", "persisted PNG bytes changed")
        info = validate_image_qa(reopened, output_path.name, expected_dimensions=dimensions)
    except TypographyError:
        raise
    except Exception as exc:
        raise TypographyError("TYPO004_POSTWRITE_MISMATCH", "production gate failed") from exc
    provenance = _provenance(base_image, text, config)
    if info.metadata.get("audio_story") != provenance:
        raise TypographyError("TYPO008_PROVENANCE_MISMATCH", "PNG provenance metadata changed")
    return ProductionTypographyEvidence(
        base_sha256=base_sha256,
        font_sha256=config.font_sha256,
        text_sha256=provenance["text_sha256"],
        final_sha256=info.sha256,
        width=info.width,
        height=info.height,
        renderer_version=config.renderer_version,
    )
