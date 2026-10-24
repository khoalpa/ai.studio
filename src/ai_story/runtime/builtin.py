from __future__ import annotations

from typing import Any

from ..errors import RuntimeCapabilityError
from .base import (
    CancellationToken,
    GenerationRequest,
    GenerationResult,
    HealthReport,
    RuntimeCapabilities,
)


class BuiltinRuntime:
    runtime_id = "builtin"

    def health(self) -> HealthReport:
        return HealthReport("PASS", self.runtime_id, "In-process deterministic providers")

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(cancellation=True)

    def generate_text(
        self, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> GenerationResult:
        raise RuntimeCapabilityError("builtin runtime does not expose generic text generation")

    def generate_json(
        self, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> dict[str, Any]:
        raise RuntimeCapabilityError("builtin runtime does not expose generic JSON generation")

    def generate_image(
        self, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> bytes:
        raise RuntimeCapabilityError("builtin runtime does not expose generic image generation")

    def assess_image(
        self, image: bytes, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> GenerationResult:
        raise RuntimeCapabilityError("builtin runtime does not expose image assessment")

    def unload(self) -> None:
        return None


class UnavailableRuntime(BuiltinRuntime):
    def __init__(self, runtime_id: str, detail: str) -> None:
        self.runtime_id = runtime_id
        self.detail = detail

    def health(self) -> HealthReport:
        return HealthReport("NOT_INSTALLED", self.runtime_id, self.detail)

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(cancellation=False)

    def generate_text(self, request, cancellation=None):
        raise RuntimeCapabilityError(self.detail)

    def generate_json(self, request, cancellation=None):
        raise RuntimeCapabilityError(self.detail)

    def generate_image(self, request, cancellation=None):
        raise RuntimeCapabilityError(self.detail)

    def assess_image(self, image, request, cancellation=None):
        raise RuntimeCapabilityError(self.detail)
