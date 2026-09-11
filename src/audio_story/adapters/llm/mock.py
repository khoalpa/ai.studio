"""Deterministic in-memory adapter for default tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from audio_story.adapters.llm.base import LLMAdapterError, LocalLLMAdapter
from audio_story.adapters.llm.models import (
    CancellationToken,
    GenerationRequest,
    GenerationResponse,
    SemanticAssessment,
    TerminationReason,
)


@dataclass(slots=True)
class DeterministicMockAdapter(LocalLLMAdapter):
    responses: list[bytes] = field(default_factory=list)
    failures: list[LLMAdapterError] = field(default_factory=list)
    model_identity: str = "mock-local-deterministic"
    adapter_version: str = "1.0"

    def _generate(
        self, request: GenerationRequest, cancellation: CancellationToken
    ) -> GenerationResponse:
        if cancellation.is_set():
            raise LLMAdapterError("LLM004_CANCELLED", TerminationReason.CANCELLED)
        if self.failures:
            raise self.failures.pop(0)
        if self.responses:
            content = self.responses.pop(0)
        else:
            digest = hashlib.sha256(
                request.capsule.digest.encode()
                + request.instruction.encode("utf-8")
                + str(request.seed).encode()
            ).hexdigest()
            content = json.dumps({"digest": digest}, sort_keys=True, separators=(",", ":")).encode()
        return GenerationResponse(content, self.model_identity, self.adapter_version, 0)

    def generate_structured(
        self, request: GenerationRequest, cancellation: CancellationToken
    ) -> GenerationResponse:
        return self._generate(request, cancellation)

    def generate_text(
        self, request: GenerationRequest, cancellation: CancellationToken
    ) -> GenerationResponse:
        return self._generate(request, cancellation)

    def assess_semantic(
        self, request: GenerationRequest, cancellation: CancellationToken
    ) -> SemanticAssessment:
        response = self._generate(request, cancellation)
        return SemanticAssessment(
            "MOCK_REVIEW", 1.0, {"response_sha256": hashlib.sha256(response.content).hexdigest()}
        )

    def health(self) -> dict[str, str]:
        return {"status": "READY", "model_identity": self.model_identity}

    def capabilities(self) -> dict[str, object]:
        return {"structured_output": True, "model_identity": self.model_identity}
