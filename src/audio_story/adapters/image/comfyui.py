"""Explicitly configured loopback ComfyUI HTTP transport."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from threading import Event
from typing import Any

from audio_story.adapters.image.base import (
    ImageAdapterError,
    ImageRequest,
    ImageResponse,
    LocalImageAdapter,
)
from audio_story.config import require_loopback_endpoint


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ImageAdapterError("IMG006_REDIRECT_REJECTED", "HTTP redirects are forbidden")


@dataclass(frozen=True, slots=True)
class ComfyUIConfig:
    endpoint: str = "http://127.0.0.1:8188"
    timeout_seconds: float = 120.0
    adapter_version: str = "M6-COMFYUI-1.0"

    def __post_init__(self) -> None:
        require_loopback_endpoint(self.endpoint)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class ComfyUIImageAdapter(LocalImageAdapter):
    def __init__(self, config: ComfyUIConfig) -> None:
        self.config = config
        self._cancelled: set[str] = set()

    def generate_image(self, request: ImageRequest, cancellation: Event) -> ImageResponse:
        if cancellation.is_set() or request.generation_call_id in self._cancelled:
            raise ImageAdapterError("IMG004_CANCELLED", "image request cancelled")
        started = time.monotonic()
        payload = {
            "basename": request.basename,
            "prompt_digest": request.prompt_digest,
            "workflow_digest": request.workflow_digest,
            "seed": request.seed,
            "width": request.requested_width,
            "height": request.requested_height,
            "format": request.output_format,
            "output_count": request.requested_output_count,
        }
        data = json.dumps(payload, separators=(",", ":")).encode()
        req = urllib.request.Request(
            require_loopback_endpoint(self.config.endpoint) + "/prompt",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.build_opener(_RejectRedirect()).open(
                req, timeout=request.timeout_seconds
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise ImageAdapterError(
                "IMG007_BACKEND_FAILURE", f"ComfyUI HTTP failure: {exc.code}"
            ) from exc
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise ImageAdapterError(
                "IMG008_TIMEOUT_OR_BACKEND", "ComfyUI local transport failed"
            ) from exc
        if cancellation.is_set() or request.generation_call_id in self._cancelled:
            raise ImageAdapterError("IMG004_CANCELLED", "image request cancelled")
        if not body:
            raise ImageAdapterError("IMG009_EMPTY_OUTPUT", "ComfyUI returned empty output")
        content = body
        try:
            decoded = json.loads(body)
            outputs = decoded.get("images") if isinstance(decoded, dict) else None
            if outputs is not None:
                if (
                    not isinstance(outputs, list)
                    or len(outputs) != 1
                    or not isinstance(outputs[0], str)
                ):
                    raise ImageAdapterError(
                        "IMG010_OUTPUT_CARDINALITY", "ComfyUI response must contain one image"
                    )
                content = base64.b64decode(outputs[0], validate=True)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        except (ValueError, TypeError) as exc:
            raise ImageAdapterError(
                "IMG011_TRUNCATED_OUTPUT", "ComfyUI image payload is invalid"
            ) from exc
        if not content:
            raise ImageAdapterError("IMG009_EMPTY_OUTPUT", "ComfyUI returned empty image")
        return ImageResponse(
            content,
            request.model_identity,
            self.config.adapter_version,
            int((time.monotonic() - started) * 1000),
            request.workflow_digest,
            request.seed,
        )

    def health(self) -> dict[str, str]:
        return {"status": "CONFIGURED", "backend": "comfyui-loopback"}

    def capabilities(self) -> dict[str, object]:
        return {
            "backend": "comfyui-loopback",
            "gpu": True,
            "network": False,
            "single_response": True,
        }

    def cancel(self, generation_call_id: str) -> None:
        self._cancelled.add(generation_call_id)

    def unload(self) -> None:
        self._cancelled.clear()
