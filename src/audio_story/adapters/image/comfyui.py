"""Explicitly configured loopback ComfyUI HTTP transport."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
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
    workflow_path: Path | None = None
    poll_interval_seconds: float = 0.25

    def __post_init__(self) -> None:
        require_loopback_endpoint(self.endpoint)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")


class ComfyUIImageAdapter(LocalImageAdapter):
    def __init__(self, config: ComfyUIConfig) -> None:
        self.config = config
        self._cancelled: set[str] = set()
        self._prompt_ids: dict[str, str] = {}

    def generate_image(self, request: ImageRequest, cancellation: Event) -> ImageResponse:
        if cancellation.is_set() or request.generation_call_id in self._cancelled:
            raise ImageAdapterError("IMG004_CANCELLED", "image request cancelled")
        started = time.monotonic()
        if self.config.workflow_path is not None:
            return self._generate_api(request, cancellation, started)
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
        prompt_id = self._prompt_ids.get(generation_call_id)
        if prompt_id is not None:
            endpoint = require_loopback_endpoint(self.config.endpoint)
            body = json.dumps({"prompt_id": prompt_id}, separators=(",", ":")).encode()
            with contextlib.suppress(ImageAdapterError):
                self._http(
                    urllib.request.Request(
                        endpoint + "/interrupt",
                        data=body,
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    ),
                    min(5.0, self.config.timeout_seconds),
                )

    def unload(self) -> None:
        self._cancelled.clear()
        self._prompt_ids.clear()

    def _http(self, request: urllib.request.Request, timeout: float) -> bytes:
        try:
            with urllib.request.build_opener(_RejectRedirect()).open(
                request, timeout=timeout
            ) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as exc:
            raise ImageAdapterError(
                "IMG007_BACKEND_FAILURE", f"ComfyUI HTTP failure: {exc.code}"
            ) from exc
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise ImageAdapterError(
                "IMG008_TIMEOUT_OR_BACKEND", "ComfyUI local transport failed"
            ) from exc

    def _generate_api(
        self, request: ImageRequest, cancellation: Event, started: float
    ) -> ImageResponse:
        assert self.config.workflow_path is not None
        try:
            workflow_bytes = self.config.workflow_path.read_bytes()
            workflow = json.loads(workflow_bytes)
            if hashlib.sha256(workflow_bytes).hexdigest() != request.workflow_digest:
                raise ImageAdapterError("IMG013_WORKFLOW_DIGEST", "workflow digest mismatch")
            workflow["4"]["inputs"].update(
                width=request.requested_width, height=request.requested_height, batch_size=1
            )
            workflow["5"]["inputs"]["seed"] = request.seed
            workflow["7"]["inputs"]["filename_prefix"] = Path(request.basename).stem
        except ImageAdapterError:
            raise
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ImageAdapterError("IMG012_WORKFLOW_INVALID", "workflow is invalid") from exc

        endpoint = require_loopback_endpoint(self.config.endpoint)
        timeout = min(request.timeout_seconds, self.config.timeout_seconds)
        payload = json.dumps(
            {"prompt": workflow, "client_id": request.generation_call_id}, separators=(",", ":")
        ).encode()
        body = self._http(
            urllib.request.Request(
                endpoint + "/prompt",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            ),
            timeout,
        )
        try:
            prompt_id = json.loads(body)["prompt_id"]
            if not isinstance(prompt_id, str) or not prompt_id:
                raise TypeError
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ImageAdapterError("IMG014_PROMPT_ID", "ComfyUI returned no prompt_id") from exc
        self._prompt_ids[request.generation_call_id] = prompt_id

        deadline = started + timeout
        while time.monotonic() < deadline:
            if cancellation.is_set() or request.generation_call_id in self._cancelled:
                raise ImageAdapterError("IMG004_CANCELLED", "image request cancelled")
            try:
                history = json.loads(
                    self._http(
                        urllib.request.Request(
                            endpoint + "/history/" + urllib.parse.quote(prompt_id)
                        ),
                        min(5.0, max(0.1, deadline - time.monotonic())),
                    )
                )
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ImageAdapterError("IMG015_HISTORY_INVALID", "history is invalid") from exc
            entry = history.get(prompt_id) if isinstance(history, dict) else None
            if entry is None:
                time.sleep(self.config.poll_interval_seconds)
                continue
            images = [
                image
                for output in entry.get("outputs", {}).values()
                for image in output.get("images", [])
            ]
            if len(images) != 1:
                raise ImageAdapterError(
                    "IMG010_OUTPUT_CARDINALITY", "ComfyUI response must contain one image"
                )
            image = images[0]
            query = urllib.parse.urlencode(
                {
                    "filename": image["filename"],
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                }
            )
            content = self._http(
                urllib.request.Request(endpoint + "/view?" + query),
                min(30.0, max(0.1, deadline - time.monotonic())),
            )
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
        raise ImageAdapterError("IMG008_TIMEOUT_OR_BACKEND", "ComfyUI generation timed out")
