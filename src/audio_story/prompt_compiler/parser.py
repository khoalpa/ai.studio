"""Byte-preserving parser for canonical physical blocks and extractable units."""

from __future__ import annotations

import hashlib
import json
import re

from audio_story.domain.enums import BlockKind, MarkerEdge, UnitKind
from audio_story.domain.errors import CompilerError, SourceSpan
from audio_story.domain.models import ParsedPrompt, PhysicalBlock, PromptUnit, RegistryBinding

MARKER = re.compile(rb"^===== (MODULE|OVERLAY):([A-Z][A-Z0-9_]*) (BEGIN|END) =====$")
RULE_HEADING = re.compile(rb"^([A-Z][A-Z0-9.-]*-[A-Z0-9.-]+):(?: .*)?$")
REGISTRY_HEADING = re.compile(rb"^([A-Z][A-Z0-9_]*_JSON):$")
OUTPUT_HEADING = re.compile(rb"^([A-Z][A-Z0-9 -]*):$")


def _span(line_no: int, start: int, end: int) -> SourceSpan:
    return SourceSpan(line_no, line_no, start, end)


def _lines(source: bytes) -> list[tuple[int, bytes, int, int]]:
    result = []
    offset = 0
    for number, raw in enumerate(source.splitlines(keepends=True), 1):
        content = raw.rstrip(b"\r\n")
        result.append((number, content, offset, offset + len(raw)))
        offset += len(raw)
    if not result or offset < len(source):
        result.append((len(result) + 1, source[offset:], offset, len(source)))
    return result


def parse_prompt(source: bytes) -> ParsedPrompt:
    """Parse exact source bytes without decoding or normalizing the source."""
    lines = _lines(source)
    blocks: list[PhysicalBlock] = []
    open_marker: tuple[BlockKind, str, int, int, int] | None = None
    seen_blocks: set[tuple[BlockKind, str]] = set()

    for line_no, line, start, end in lines:
        if line.startswith(b"=====") and not (match := MARKER.fullmatch(line)):
            raise CompilerError(
                "PC001_MALFORMED_MARKER", "invalid marker grammar", _span(line_no, start, end)
            )
        if not line.startswith(b"====="):
            continue
        assert match is not None
        kind = BlockKind(match.group(1).decode("ascii"))
        identifier = match.group(2).decode("ascii")
        edge = MarkerEdge(match.group(3).decode("ascii"))
        if edge is MarkerEdge.BEGIN:
            if open_marker is not None:
                raise CompilerError(
                    "PC003_NESTED_MARKER",
                    f"{identifier} begins inside {open_marker[1]}",
                    _span(line_no, start, end),
                )
            key = (kind, identifier)
            if key in seen_blocks:
                raise CompilerError(
                    "PC005_DUPLICATE_PHYSICAL_BLOCK",
                    f"duplicate {kind}:{identifier}",
                    _span(line_no, start, end),
                )
            open_marker = (kind, identifier, line_no, start, end)
            seen_blocks.add(key)
        elif open_marker is None:
            raise CompilerError(
                "PC002_UNMATCHED_MARKER",
                f"unexpected END for {kind}:{identifier}",
                _span(line_no, start, end),
            )
        else:
            open_kind, open_id, open_line, open_start, body_start = open_marker
            if (kind, identifier) != (open_kind, open_id):
                raise CompilerError(
                    "PC004_CROSSED_MARKER",
                    f"expected END for {open_kind}:{open_id}",
                    _span(line_no, start, end),
                )
            blocks.append(
                PhysicalBlock(
                    kind,
                    identifier,
                    SourceSpan(open_line, line_no, open_start, end),
                    body_start,
                    start,
                )
            )
            open_marker = None
    if open_marker is not None:
        kind, identifier, line_no, start, end = open_marker
        raise CompilerError(
            "PC002_UNMATCHED_MARKER",
            f"missing END for {kind}:{identifier}",
            _span(line_no, start, end),
        )

    units, registries = _extract_units(source, lines, blocks)
    return ParsedPrompt(
        hashlib.sha256(source).hexdigest(),
        len(source),
        tuple(blocks),
        tuple(units),
        tuple(registries),
    )


def _extract_units(
    source: bytes,
    lines: list[tuple[int, bytes, int, int]],
    blocks: list[PhysicalBlock],
) -> tuple[list[PromptUnit], list[RegistryBinding]]:
    units: list[PromptUnit] = []
    registries: list[RegistryBinding] = []
    owners: dict[str, SourceSpan] = {}
    for block in blocks:
        block_lines = [
            item for item in lines if block.body_start_byte <= item[2] < block.body_end_byte
        ]
        headings: list[tuple[int, str, UnitKind, int, int]] = []
        for index, (_line_no, line, start, end) in enumerate(block_lines):
            registry_match = REGISTRY_HEADING.fullmatch(line)
            rule_match = RULE_HEADING.fullmatch(line)
            output_match = OUTPUT_HEADING.fullmatch(line) if b"OUTPUT" in line else None
            if registry_match:
                identifier = registry_match.group(1).decode("ascii")
                headings.append((index, identifier, UnitKind.REGISTRY_DECLARATION_LINE, start, end))
            elif rule_match:
                identifier = rule_match.group(1).decode("ascii")
                kind = (
                    UnitKind.NAMED_GATE_BLOCK
                    if "GATE" in identifier
                    else UnitKind.CANONICAL_RULE_BLOCK
                )
                headings.append((index, identifier, kind, start, end))
            elif output_match:
                identifier = output_match.group(1).decode("ascii").replace(" ", "_")
                headings.append((index, identifier, UnitKind.OUTPUT_TEMPLATE_BLOCK, start, end))

        for position, (index, identifier, kind, start, _) in enumerate(headings):
            end = headings[position + 1][3] if position + 1 < len(headings) else block.body_end_byte
            start_line = block_lines[index][0]
            end_line = next(
                (item[0] - 1 for item in block_lines if item[2] == end), block.span.end_line - 1
            )
            span = SourceSpan(start_line, end_line, start, end)
            if identifier in owners:
                raise CompilerError(
                    "PC006_DUPLICATE_CANONICAL_OWNER", f"duplicate owner for {identifier}", span
                )
            owners[identifier] = span
            content = source[start:end]
            units.append(
                PromptUnit(
                    identifier,
                    kind,
                    block.identifier,
                    span,
                    content,
                    hashlib.sha256(content).hexdigest(),
                )
            )
            if kind is UnitKind.REGISTRY_DECLARATION_LINE:
                registries.append(_parse_registry(identifier, content, span))
    return units, registries


def _parse_registry(identifier: str, content: bytes, span: SourceSpan) -> RegistryBinding:
    match = re.search(rb"```json\r?\n(.+?)\r?\n```", content, re.DOTALL)
    if match is None:
        raise CompilerError(
            "PC007_INVALID_REGISTRY_JSON", f"{identifier} has no fenced JSON value", span
        )
    raw_json = match.group(1)
    try:
        value = json.loads(raw_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompilerError("PC007_INVALID_REGISTRY_JSON", f"{identifier}: {exc}", span) from exc
    return RegistryBinding(identifier, value, span, hashlib.sha256(raw_json).hexdigest())
