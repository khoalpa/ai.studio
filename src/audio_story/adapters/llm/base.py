"""Stable backend-neutral Local LLM interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from audio_story.adapters.llm.models import (
    CancellationToken,
    GenerationRequest,
    GenerationResponse,
    SemanticAssessment,
)


class LLMAdapterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class LocalLLMAdapter(ABC):
    """Local-only generation API; implementations may not cloud-fallback."""

    @abstractmethod
    def generate_structured(
        self, request: GenerationRequest, cancellation: CancellationToken
    ) -> GenerationResponse: ...

    @abstractmethod
    def generate_text(
        self, request: GenerationRequest, cancellation: CancellationToken
    ) -> GenerationResponse: ...

    @abstractmethod
    def assess_semantic(
        self, request: GenerationRequest, cancellation: CancellationToken
    ) -> SemanticAssessment: ...

    def health(self) -> dict[str, str]:
        return {"status": "UNKNOWN"}

    def capabilities(self) -> dict[str, object]:
        return {}

    def unload(self) -> None:
        """Release local model resources before another GPU-heavy worker starts."""

        return None
