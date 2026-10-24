from __future__ import annotations

import hashlib
import math
import struct
import zlib
from functools import lru_cache

from ..errors import ArtifactError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(name: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))


def solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> tuple[bytes, str]:
    pixel_row = bytes(rgb) * width
    raw_row = b"\x00" + pixel_row
    compressor = zlib.compressobj(level=9)
    compressed = bytearray()
    pixel_digest = hashlib.sha256()
    for _ in range(height):
        compressed.extend(compressor.compress(raw_row))
        pixel_digest.update(pixel_row)
    compressed.extend(compressor.flush())
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    content = PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", bytes(compressed)) + _chunk(b"IEND", b"")
    return content, pixel_digest.hexdigest()


def _mix(left: tuple[int, int, int], right: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(round(left[index] * (1 - amount) + right[index] * amount) for index in range(3))


def _span(row: bytearray, width: int, start: int, end: int, color: tuple[int, int, int]) -> None:
    left = max(0, min(width, start))
    right = max(left, min(width, end))
    row[left * 3:right * 3] = bytes(color) * (right - left)


def _circle_span(
    row: bytearray,
    width: int,
    y: int,
    center_x: int,
    center_y: int,
    radius: int,
    color: tuple[int, int, int],
) -> None:
    delta = y - center_y
    if abs(delta) > radius:
        return
    half = round(math.sqrt(max(0, radius * radius - delta * delta)))
    _span(row, width, center_x - half, center_x + half + 1, color)


@lru_cache(maxsize=32)
def character_card_png(
    width: int,
    height: int,
    seed_rgb: tuple[int, int, int],
    primary: tuple[int, int, int],
    presentation: str,
) -> tuple[bytes, str]:
    """Render a text-free, deterministic storybook character reference card."""
    background_top = _mix((238, 244, 250), seed_rgb, 0.16)
    background_bottom = _mix((255, 239, 218), seed_rgb, 0.10)
    panel = (250, 247, 239)
    outline = _mix((42, 48, 58), seed_rgb, 0.12)
    skin = _mix((222, 158, 111), seed_rgb, 0.08)
    hair = _mix((35, 27, 28), seed_rgb, 0.10)
    accent = _mix(primary, (255, 255, 255), 0.28)
    shadow = (190, 187, 181)
    center = width // 2
    panel_margin = width // 10
    head_y, head_radius = height * 33 // 100, width * 13 // 100
    shoulder_y, waist_y, hem_y = height * 46 // 100, height * 67 // 100, height * 78 // 100
    compressor = zlib.compressobj(level=9)
    compressed = bytearray()
    pixel_digest = hashlib.sha256()
    for y in range(height):
        amount = y / max(1, height - 1)
        background = _mix(background_top, background_bottom, amount)
        row = bytearray(bytes(background) * width)
        if height // 18 <= y < height * 17 // 18:
            _span(row, width, panel_margin, width - panel_margin, panel)
        if y >= height * 82 // 100:
            _span(row, width, panel_margin, width - panel_margin, _mix(panel, primary, 0.08))

        shadow_y = height * 83 // 100
        shadow_radius_y = max(1, height // 35)
        shadow_delta = (y - shadow_y) / shadow_radius_y
        if abs(shadow_delta) <= 1:
            half = round(width * 17 // 100 * math.sqrt(1 - shadow_delta * shadow_delta))
            _span(row, width, center - half, center + half, shadow)

        leg_width = width * 5 // 100
        if hem_y <= y < height * 84 // 100:
            _span(row, width, center - width * 8 // 100, center - width * 8 // 100 + leg_width, outline)
            _span(row, width, center + width * 3 // 100, center + width * 3 // 100 + leg_width, outline)

        if shoulder_y <= y < hem_y:
            progress = (y - shoulder_y) / max(1, hem_y - shoulder_y)
            half = round(width * (0.15 + 0.07 * progress))
            _span(row, width, center - half - 3, center + half + 3, outline)
            _span(row, width, center - half, center + half, primary)
            if waist_y <= y < waist_y + height // 40:
                _span(row, width, center - half, center + half, accent)

        if shoulder_y + height // 40 <= y < waist_y:
            arm_offset = width * 17 // 100
            arm_width = width * 4 // 100
            _span(row, width, center - arm_offset - arm_width, center - arm_offset, skin)
            _span(row, width, center + arm_offset, center + arm_offset + arm_width, skin)

        _circle_span(row, width, y, center, head_y, head_radius + 5, outline)
        _circle_span(row, width, y, center, head_y, head_radius, skin)
        if y <= head_y:
            _circle_span(row, width, y, center, head_y - head_radius // 5, head_radius, hair)
        side_length = head_radius if presentation == "FEMININE" else head_radius * 2 // 3
        if head_y - head_radius // 3 <= y < head_y + side_length:
            side_width = max(4, head_radius // 5)
            _span(row, width, center - head_radius, center - head_radius + side_width, hair)
            _span(row, width, center + head_radius - side_width, center + head_radius, hair)
        eye_y = head_y + head_radius // 10
        if eye_y <= y < eye_y + max(3, height // 180):
            eye_width = max(3, width // 85)
            eye_gap = width * 5 // 100
            _span(row, width, center - eye_gap - eye_width, center - eye_gap + eye_width, outline)
            _span(row, width, center + eye_gap - eye_width, center + eye_gap + eye_width, outline)
        mouth_y = head_y + head_radius * 2 // 5
        if mouth_y <= y < mouth_y + max(2, height // 300):
            _span(row, width, center - width // 35, center + width // 35, _mix((150, 62, 67), seed_rgb, 0.08))

        pixel_row = bytes(row)
        compressed.extend(compressor.compress(b"\x00" + pixel_row))
        pixel_digest.update(pixel_row)
    compressed.extend(compressor.flush())
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    content = PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", bytes(compressed)) + _chunk(b"IEND", b"")
    return content, pixel_digest.hexdigest()


def png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ArtifactError("Invalid PNG signature or IHDR")
    return struct.unpack(">II", data[16:24])


def png_visual_statistics(data: bytes, sample_limit: int = 4096) -> dict[str, int]:
    """Return inexpensive pixel-diversity signals for an 8-bit RGB/RGBA PNG."""
    width, height = png_dimensions(data)
    bit_depth, color_type = data[24], data[25]
    channels = {2: 3, 6: 4}.get(color_type)
    if bit_depth != 8 or channels is None:
        raise ArtifactError("Unsupported PNG format for visual QA")
    position = 8
    compressed = bytearray()
    while position + 12 <= len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        payload = data[position + 8:position + 8 + length]
        if kind == b"IDAT":
            compressed.extend(payload)
        position += 12 + length
        if kind == b"IEND":
            break
    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise ArtifactError("Invalid PNG image data") from exc
    stride = width * channels
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise ArtifactError("Unexpected PNG scanline size")

    previous = bytearray(stride)
    colors: set[bytes] = set()
    minima = [255, 255, 255]
    maxima = [0, 0, 0]
    sample_step = max(1, (width * height) // sample_limit)
    pixel_index = 0
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        encoded = raw[offset + 1:offset + 1 + stride]
        offset += stride + 1
        row = bytearray(stride)
        for index, value in enumerate(encoded):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                prediction = 0
            elif filter_type == 1:
                prediction = left
            elif filter_type == 2:
                prediction = above
            elif filter_type == 3:
                prediction = (left + above) // 2
            elif filter_type == 4:
                estimate = left + above - upper_left
                distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
                prediction = (left, above, upper_left)[distances.index(min(distances))]
            else:
                raise ArtifactError("Unsupported PNG filter")
            row[index] = (value + prediction) & 0xFF
        for index in range(0, stride, channels):
            if pixel_index % sample_step == 0:
                rgb = bytes(row[index:index + 3])
                colors.add(rgb)
                for channel, value in enumerate(rgb):
                    minima[channel] = min(minima[channel], value)
                    maxima[channel] = max(maxima[channel], value)
            pixel_index += 1
        previous = row
    return {
        "sampled_unique_colors": len(colors),
        "sampled_channel_range": max(maxima[channel] - minima[channel] for channel in range(3)),
    }
