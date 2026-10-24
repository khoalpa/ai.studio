from __future__ import annotations

import io
from typing import Any


def render_cover_typography(data: bytes, title: str) -> tuple[bytes, dict[str, Any]]:
    """Render trusted title text after diffusion, inside a deterministic safe region."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.open(io.BytesIO(data)).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    font_size = max(36, image.width // 24)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()
    safe = (
        round(image.width * 0.06), round(image.height * 0.03),
        round(image.width * 0.94), round(image.height * 0.19),
    )
    draw.rounded_rectangle(safe, radius=max(12, font_size // 3), fill=(8, 15, 28, 178))
    max_width = safe[2] - safe[0] - font_size
    words, lines, current = title.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    y = safe[1] + font_size // 3
    for line in lines[:2]:
        draw.text((safe[0] + font_size // 2, y), line, font=font, fill=(255, 248, 230, 255), stroke_width=2, stroke_fill=(0, 0, 0, 210))
        y += font_size + font_size // 5
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), {
        "status": "PASS", "method": "CONTROLLED_POSTPROCESS",
        "safe_region": list(safe), "face_safe_boundary_y": round(image.height * 0.22),
        "text": title, "line_count": min(2, len(lines)),
    }
