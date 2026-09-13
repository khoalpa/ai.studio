"""Backend-neutral, single-response local image adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import Event
from typing import Any


class ImageAdapterError(RuntimeError):
    """Stable local image transport or policy failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class DeliveryStatus:
    AUTHORITATIVE = "AUTHORITATIVE"
    DRAFT_ONLY = "DRAFT_ONLY"
    UNAVAILABLE = "UNAVAILABLE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    VISUAL_GATE_FAIL = "VISUAL_GATE_FAIL"


@dataclass(frozen=True, slots=True)
class ImageRequest:
    basename: str
    prompt_digest: str
    workflow_digest: str
    model_identity: str
    seed: int
    requested_output_count: int
    requested_width: int
    requested_height: int
    output_format: str
    timeout_seconds: float
    transaction_id: str
    generation_call_id: str
    commitment_context: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.requested_output_count != 1:
            raise ImageAdapterError(
                "IMG001_SINGLE_RESPONSE_REQUIRED", "authoritative image requires one output"
            )
        if self.requested_width <= 0 or self.requested_height <= 0:
            raise ImageAdapterError("IMG002_INVALID_CANVAS", "canvas dimensions must be positive")
        if self.timeout_seconds <= 0:
            raise ImageAdapterError("IMG003_INVALID_TIMEOUT", "timeout must be positive")


@dataclass(frozen=True, slots=True)
class ImageResponse:
    content: bytes
    model_identity: str
    adapter_version: str
    duration_ms: int
    workflow_digest: str
    seed: int
    termination_reason: str = "COMPLETED"


class LocalImageAdapter(ABC):
    """Local-only image API; implementations never fall back to cloud services."""

    @abstractmethod
    def generate_image(self, request: ImageRequest, cancellation: Event) -> ImageResponse: ...

    @abstractmethod
    def health(self) -> dict[str, str]: ...

    @abstractmethod
    def capabilities(self) -> dict[str, object]: ...

    @abstractmethod
    def cancel(self, generation_call_id: str) -> None: ...

    @abstractmethod
    def unload(self) -> None: ...
