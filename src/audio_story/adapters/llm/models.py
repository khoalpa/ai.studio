"""Typed values crossing the local LLM adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import Event
from typing import Any


class GenerationKind(StrEnum):
    STRUCTURED = "STRUCTURED"
    TEXT = "TEXT"
    SEMANTIC_ASSESSMENT = "SEMANTIC_ASSESSMENT"


class TerminationReason(StrEnum):
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    BACKEND_ERROR = "BACKEND_ERROR"
    NON_ZERO_EXIT = "NON_ZERO_EXIT"
    TRUNCATED_OUTPUT = "TRUNCATED_OUTPUT"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class PromptCapsule:
    canonical_bytes: bytes
    digest: str


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    capsule: PromptCapsule
    instruction: str
    kind: GenerationKind
    max_output_tokens: int
    schema_name: str | None = None
    schema_version: str | None = None
    field_order: tuple[str, ...] | None = None
    seed: int = 0
    json_schema: dict[str, Any] | None = None
    prompt_context: bytes | None = None
    temperature: float | None = None
    top_p: float | None = None


@dataclass(frozen=True, slots=True)
class GenerationResponse:
    content: bytes
    model_identity: str
    adapter_version: str
    duration_ms: int
    termination_reason: TerminationReason = TerminationReason.COMPLETED


@dataclass(frozen=True, slots=True)
class SemanticAssessment:
    label: str
    score: float
    evidence: dict[str, Any]


CancellationToken = Event
