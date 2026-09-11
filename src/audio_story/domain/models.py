"""Typed immutable models shared by prompt compiler components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audio_story.domain.enums import BlockKind, FindingSeverity, Profile, Route, Stage, UnitKind
from audio_story.domain.errors import SourceSpan


@dataclass(frozen=True, slots=True)
class PhysicalBlock:
    kind: BlockKind
    identifier: str
    span: SourceSpan
    body_start_byte: int
    body_end_byte: int


@dataclass(frozen=True, slots=True)
class PromptUnit:
    identifier: str
    kind: UnitKind
    owner_block: str
    span: SourceSpan
    content: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class RegistryBinding:
    symbol: str
    value: Any
    span: SourceSpan
    sha256: str


@dataclass(frozen=True, slots=True)
class CompilerFinding:
    code: str
    severity: FindingSeverity
    message: str
    spans: tuple[SourceSpan, ...]


@dataclass(frozen=True, slots=True)
class ParsedPrompt:
    source_sha256: str
    source_size: int
    blocks: tuple[PhysicalBlock, ...]
    units: tuple[PromptUnit, ...]
    registries: tuple[RegistryBinding, ...]


@dataclass(frozen=True, slots=True)
class CompileRequest:
    stage: Stage
    profile: Profile
    route: Route = Route.CREATE
    activation_guards: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ActiveStageCapsule:
    document: dict[str, Any]
    canonical_bytes: bytes
    digest: str
