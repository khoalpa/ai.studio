"""Stable, locator-rich compiler errors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int


class CompilerError(ValueError):
    """A prompt compiler failure with a stable code and source locator."""

    def __init__(self, code: str, message: str, span: SourceSpan) -> None:
        self.code = code
        self.message = message
        self.span = span
        super().__init__(f"{code} at lines {span.start_line}-{span.end_line}: {message}")
