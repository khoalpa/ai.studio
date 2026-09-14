"""Loopback HTTP and explicitly configured local-process llama.cpp backend."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from audio_story.adapters.llm.base import LLMAdapterError, LocalLLMAdapter
from audio_story.adapters.llm.models import (
    CancellationToken,
    GenerationRequest,
    GenerationResponse,
    SemanticAssessment,
    TerminationReason,
)
from audio_story.config import require_loopback_endpoint


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise LLMAdapterError("LLM001_NON_LOOPBACK_ENDPOINT", "HTTP redirects are forbidden")


def _open_local(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.build_opener(_RejectRedirect()).open(request, timeout=timeout)


@dataclass(frozen=True, slots=True)
class LlamaCppConfig:
    endpoint: str | None = "http://127.0.0.1:8080"
    command: tuple[str, ...] | None = None
    timeout_seconds: float = 120.0
    adapter_version: str = "1.0"

    def __post_init__(self) -> None:
        if (self.endpoint is None) == (self.command is None):
            raise ValueError("configure exactly one of endpoint or command")
        if self.endpoint is not None:
            require_loopback_endpoint(self.endpoint)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class LlamaCppAdapter(LocalLLMAdapter):
    def __init__(self, config: LlamaCppConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[bytes] | None = None

    def generate_structured(
        self, request: GenerationRequest, cancellation: CancellationToken
    ) -> GenerationResponse:
        return self._generate(request, cancellation, json_mode=True)

    def generate_text(
        self, request: GenerationRequest, cancellation: CancellationToken
    ) -> GenerationResponse:
        return self._generate(request, cancellation, json_mode=False)

    def assess_semantic(
        self, request: GenerationRequest, cancellation: CancellationToken
    ) -> SemanticAssessment:
        response = self._generate(request, cancellation, json_mode=True)
        try:
            value = json.loads(response.content)
            return SemanticAssessment(
                str(value["label"]), float(value["score"]), dict(value.get("evidence", {}))
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMAdapterError("LLM011_SEMANTIC_RESPONSE", "invalid semantic response") from exc

    def health(self) -> dict[str, str]:
        if self.config.endpoint is None:
            return {"status": "CONFIGURED", "transport": "subprocess"}
        payload = self._http_json("GET", "/health", None)
        return {"status": str(payload.get("status", "UNKNOWN")), "transport": "loopback-http"}

    def capabilities(self) -> dict[str, object]:
        if self.config.endpoint is None:
            return {"transport": "subprocess", "structured_output": True}
        payload = self._http_json("GET", "/props", None)
        return {
            "transport": "loopback-http",
            "structured_output": True,
            "model_path": payload.get("model_path"),
            "context_size": payload.get("n_ctx"),
        }

    def unload(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        self._process = None

    def _generate(
        self, request: GenerationRequest, cancellation: CancellationToken, *, json_mode: bool
    ) -> GenerationResponse:
        if cancellation.is_set():
            raise LLMAdapterError("LLM004_CANCELLED", TerminationReason.CANCELLED)
        started = time.monotonic()
        prompt = (
            (request.prompt_context or request.capsule.canonical_bytes).decode("utf-8")
            + "\n\n<|im_start|>user\n"
            + request.instruction
            + "\n<|im_end|>\n<|im_start|>assistant\n"
        )
        payload: dict[str, Any] = {
            "prompt": prompt,
            "n_predict": request.max_output_tokens,
            "seed": request.seed,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if json_mode:
            schema = request.json_schema or {"type": "object"}
            _validate_local_json_schema(schema)
            payload["json_schema"] = schema
        if self.config.endpoint is not None:
            value = self._http_json("POST", "/completion", payload)
            if cancellation.is_set():
                raise LLMAdapterError("LLM004_CANCELLED", TerminationReason.CANCELLED)
            content = value.get("content")
            if not isinstance(content, str):
                raise LLMAdapterError("LLM008_TRUNCATED_OUTPUT", "missing completion content")
            model = str(value.get("model", "llama.cpp-local"))
            reason = str(value.get("stop_reason", value.get("stop_type", "COMPLETED")))
            if reason in {"length", "limit"}:
                raise LLMAdapterError("LLM008_TRUNCATED_OUTPUT", "backend reached output limit")
            output = content.encode("utf-8")
        else:
            output = self._run_process(json.dumps(payload).encode(), cancellation)
            model = "llama.cpp-subprocess"
        elapsed = int((time.monotonic() - started) * 1000)
        return GenerationResponse(output, model, self.config.adapter_version, elapsed)

    def _http_json(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        endpoint = require_loopback_endpoint(self.config.endpoint or "")
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            endpoint + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with _open_local(request, self.config.timeout_seconds) as response:
                result = json.loads(response.read())
        except TimeoutError as exc:
            raise LLMAdapterError("LLM003_TIMEOUT", TerminationReason.TIMEOUT) from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise LLMAdapterError("LLM006_BACKEND_FAILURE", "local backend failed") from exc
        if not isinstance(result, dict):
            raise LLMAdapterError("LLM006_BACKEND_FAILURE", "backend response must be an object")
        return result

    def _run_process(self, payload: bytes, cancellation: CancellationToken) -> bytes:
        command = self.config.command
        if command is None:
            raise LLMAdapterError("LLM006_BACKEND_FAILURE", "subprocess command is absent")
        try:
            self._process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            deadline = time.monotonic() + self.config.timeout_seconds
            process_input: bytes | None = payload
            while True:
                if cancellation.is_set():
                    self.unload()
                    raise LLMAdapterError("LLM004_CANCELLED", TerminationReason.CANCELLED)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.unload()
                    raise LLMAdapterError("LLM003_TIMEOUT", TerminationReason.TIMEOUT)
                try:
                    stdout, _ = self._process.communicate(
                        process_input, timeout=min(0.05, remaining)
                    )
                    break
                except subprocess.TimeoutExpired:
                    process_input = None
                    continue
            if self._process.returncode:
                raise LLMAdapterError("LLM007_NON_ZERO_EXIT", TerminationReason.NON_ZERO_EXIT)
            if not stdout:
                raise LLMAdapterError("LLM008_TRUNCATED_OUTPUT", "empty subprocess output")
            return stdout
        except OSError as exc:
            raise LLMAdapterError("LLM006_BACKEND_FAILURE", "local process failed") from exc
        finally:
            self.unload()


def _validate_local_json_schema(schema: dict[str, Any]) -> None:
    if schema.get("type") != "object":
        raise LLMAdapterError("LLM015_JSON_SCHEMA", "structured schema root must be object")
    try:
        encoded = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise LLMAdapterError("LLM015_JSON_SCHEMA", "schema is not JSON serializable") from exc
    if len(encoded) > 65536 or '"$ref"' in encoded:
        raise LLMAdapterError(
            "LLM015_JSON_SCHEMA", "schema refs or oversized schemas are forbidden"
        )
