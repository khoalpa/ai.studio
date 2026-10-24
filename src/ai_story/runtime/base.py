from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from ..errors import RuntimeCancelledError


@dataclass(frozen=True)
class RuntimeCapabilities:
    text: bool = False
    structured_json: bool = False
    image: bool = False
    vision: bool = False
    cancellation: bool = True
    model_unload: bool = False
    image_text_to_image: bool = False
    image_to_image: bool = False
    image_reference: bool = False
    image_inpainting: bool = False
    image_outpainting: bool = False
    image_controlnet: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True)
class HealthReport:
    status: str
    runtime: str
    detail: str | None = None
    loaded_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    system_prompt: str | None = None
    model: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    json_schema: dict[str, Any] | None = None
    timeout_seconds: float | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str | None
    runtime: str
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeCancelledError("Model request was cancelled")


class ModelRuntime(Protocol):
    runtime_id: str

    def health(self) -> HealthReport: ...

    def capabilities(self) -> RuntimeCapabilities: ...

    def generate_text(
        self, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> GenerationResult: ...

    def generate_json(
        self, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> dict[str, Any]: ...

    def generate_image(
        self, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> bytes: ...

    def assess_image(
        self, image: bytes, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> GenerationResult: ...

    def unload(self) -> None: ...
