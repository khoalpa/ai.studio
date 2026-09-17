"""Resolve an optional series title from the completed story content."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "các",
        "cho",
        "chuyện",
        "câu",
        "của",
        "đã",
        "để",
        "được",
        "in",
        "is",
        "là",
        "một",
        "những",
        "of",
        "or",
        "sau",
        "story",
        "the",
        "this",
        "to",
        "và",
        "về",
        "với",
    }
)


def resolve_series_title(
    provided_title: str | None,
    outline: Mapping[str, Any],
    script: Iterable[Mapping[str, Any]],
    language: str,
) -> str:
    """Keep an explicit title; otherwise derive a reusable name from story text."""
    if provided_title is not None and provided_title.strip():
        return provided_title.strip()

    content = list(outline.values()) + [item.get("text", "") for item in script]
    tokens = [
        token.casefold()
        for value in content
        if isinstance(value, str)
        for token in _TOKEN_RE.findall(value)
        if len(token) > 2 and token.casefold() not in _STOP_WORDS
    ]
    phrases = [" ".join(tokens[index : index + 2]) for index in range(len(tokens) - 1)]
    keyword = (
        Counter(phrases).most_common(1)[0][0]
        if phrases
        else Counter(tokens).most_common(1)[0][0]
        if tokens
        else None
    )
    if language == "vi":
        return f"Những Chuyện Về {keyword.title()}" if keyword else "Những Câu Chuyện Mới"
    return f"Stories of {keyword.title()}" if keyword else "New Story Collection"
