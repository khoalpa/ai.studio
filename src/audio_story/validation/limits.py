"""Configurable local resource limits."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValidationLimits:
    max_json_bytes: int = 16 * 1024 * 1024
    max_json_depth: int = 128
    max_png_pixels: int = 100_000_000
    max_zip_members: int = 2_000
    max_zip_member_bytes: int = 512 * 1024 * 1024
    max_zip_total_bytes: int = 4 * 1024 * 1024 * 1024
    max_zip_compression_ratio: float = 200.0
    copy_chunk_bytes: int = 1024 * 1024


DEFAULT_LIMITS = ValidationLimits()
