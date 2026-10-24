from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from ..errors import (
    RuntimeCapabilityError,
    RuntimeRequestTooLargeError,
    RuntimeTimeoutError,
    RuntimeUnavailableError,
)
from .base import (
    CancellationToken,
    GenerationRequest,
    GenerationResult,
    HealthReport,
    RuntimeCapabilities,
)


class LlamaCppRuntime:
    """Small stdlib client for llama.cpp's OpenAI-compatible HTTP server."""

    runtime_id = "llama_cpp"

    def __init__(
        self,
        endpoint: str,
        default_timeout: float = 120.0,
        *,
        max_context_tokens: int = 16384,
        max_input_tokens: int = 12000,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.default_timeout = default_timeout
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeUnavailableError("llama.cpp endpoint must use HTTP on the loopback interface")
        if default_timeout <= 0:
            raise RuntimeUnavailableError("llama.cpp timeout must be positive")
        if max_input_tokens <= 0 or max_context_tokens <= max_input_tokens:
            raise RuntimeUnavailableError("llama.cpp context budgets are invalid")
        self.max_context_tokens = max_context_tokens
        self.max_input_tokens = max_input_tokens

    def health(self) -> HealthReport:
        try:
            value = self._request("GET", "/health", None, min(self.default_timeout, 5.0))
        except (RuntimeUnavailableError, RuntimeTimeoutError) as exc:
            return HealthReport("UNAVAILABLE", self.runtime_id, str(exc))
        return HealthReport(
            "PASS",
            self.runtime_id,
            str(value.get("status", "ok")),
            value.get("model") or value.get("model_path"),
        )

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            text=True, structured_json=True, cancellation=True, model_unload=False
        )

    def generate_text(
        self, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> GenerationResult:
        if cancellation:
            cancellation.raise_if_cancelled()
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        estimated_input_tokens = self._estimate_input_tokens(request)
        if estimated_input_tokens > self.max_input_tokens:
            raise RuntimeRequestTooLargeError(
                "REQUEST_TOO_LARGE: estimated input "
                f"{estimated_input_tokens} tokens exceeds budget {self.max_input_tokens}"
            )
        requested_output_tokens = int(request.parameters.get("max_tokens", 0) or 0)
        if estimated_input_tokens + requested_output_tokens > self.max_context_tokens:
            raise RuntimeRequestTooLargeError(
                "REQUEST_TOO_LARGE: estimated input plus requested output "
                f"({estimated_input_tokens} + {requested_output_tokens}) exceeds context "
                f"{self.max_context_tokens}"
            )
        payload: dict[str, Any] = {
            "model": request.model or "local-model",
            "messages": messages,
            "stream": False,
            **request.parameters,
        }
        if request.json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": request.json_schema},
            }
        value = self._request(
            "POST", "/v1/chat/completions", payload, request.timeout_seconds or self.default_timeout
        )
        if cancellation:
            cancellation.raise_if_cancelled()
        try:
            choice = value["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeUnavailableError("llama.cpp returned an invalid completion payload") from exc
        return GenerationResult(
            text=str(text),
            model=value.get("model") or request.model,
            runtime=self.runtime_id,
            finish_reason=choice.get("finish_reason"),
            usage=value.get("usage") or {},
        )

    def generate_json(
        self, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> dict[str, Any]:
        if request.json_schema is None:
            raise RuntimeCapabilityError("Structured generation requires json_schema")
        result = self.generate_text(request, cancellation)
        raw = result.text.strip()
        candidates = [raw]
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            candidates.append(fenced.group(1).strip())
        first, last = raw.find("{"), raw.rfind("}")
        if first >= 0 and last > first:
            candidates.append(raw[first:last + 1])
        for candidate in candidates:
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        preview = raw[:500].replace("\n", "\\n")
        raise RuntimeUnavailableError(
            f"Runtime returned invalid JSON (finish_reason={result.finish_reason!r}, "
            f"preview={preview!r})"
        )

    def generate_image(
        self, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> bytes:
        raise RuntimeCapabilityError("llama.cpp runtime does not generate images")

    def assess_image(
        self, image: bytes, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> GenerationResult:
        raise RuntimeCapabilityError("Vision input is not enabled for this runtime adapter")

    def unload(self) -> None:
        return None

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None, timeout: float
    ) -> dict[str, Any]:
        if method == "POST":
            return self._request_with_hard_deadline(path, payload, timeout)
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            deadline = time.monotonic() + timeout
            with urllib.request.urlopen(request, timeout=timeout) as response:
                chunks: list[bytes] = []
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeTimeoutError(
                            f"llama.cpp request exceeded {timeout:g}s total deadline"
                        )
                    transport = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                    if transport is not None:
                        transport.settimeout(max(0.1, remaining))
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                raw = b"".join(chunks)
        except RuntimeTimeoutError:
            raise
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeTimeoutError(f"llama.cpp request exceeded {timeout:g}s total deadline") from exc
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            if exc.code == 400 and re.search(
                r"request .*? tokens|exceeds the available context|context size|too (?:large|long)",
                body,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                raise RuntimeRequestTooLargeError(
                    f"REQUEST_TOO_LARGE: llama.cpp rejected the request: {body}"
                ) from exc
            raise RuntimeUnavailableError(
                f"llama.cpp request failed: HTTP {exc.code}: {body or exc.reason}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeUnavailableError(f"llama.cpp request failed: {exc}") from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeUnavailableError("llama.cpp returned a non-JSON response") from exc
        if not isinstance(value, dict):
            raise RuntimeUnavailableError("llama.cpp response root must be an object")
        return value

    def _request_with_hard_deadline(
        self, path: str, payload: dict[str, Any] | None, timeout: float
    ) -> dict[str, Any]:
        """Run generation in a killable child process so the deadline is truly hard."""
        executable = shutil.which("curl.exe") or shutil.which("curl")
        if not executable:
            raise RuntimeUnavailableError(
                "curl is required to enforce the llama.cpp hard request deadline"
            )
        body = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))
        command = [
            executable, "--silent", "--show-error", "--fail-with-body",
            "--max-time", f"{timeout:g}", "--header", "Content-Type: application/json",
            "--data-binary", body, self.endpoint + path,
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=timeout + 5.0, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeTimeoutError(
                f"llama.cpp request exceeded {timeout:g}s hard deadline"
            ) from exc
        raw = result.stdout
        if result.returncode == 28:
            raise RuntimeTimeoutError(
                f"llama.cpp request exceeded {timeout:g}s hard deadline"
            )
        if result.returncode != 0:
            detail = (raw + result.stderr).decode("utf-8", errors="replace")[:1000]
            if re.search(
                r"request .*? tokens|exceeds the available context|context size|too (?:large|long)",
                detail, flags=re.IGNORECASE | re.DOTALL,
            ):
                raise RuntimeRequestTooLargeError(
                    f"REQUEST_TOO_LARGE: llama.cpp rejected the request: {detail}"
                )
            raise RuntimeUnavailableError(
                f"llama.cpp request failed (curl exit {result.returncode}): {detail}"
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeUnavailableError("llama.cpp returned a non-JSON response") from exc
        if not isinstance(value, dict):
            raise RuntimeUnavailableError("llama.cpp response root must be an object")
        return value

    @staticmethod
    def _estimate_input_tokens(request: GenerationRequest) -> int:
        """Conservative tokenizer-free guard for multilingual local prompts."""
        text = f"{request.system_prompt or ''}\n{request.prompt}"
        schema = json.dumps(
            request.json_schema or {}, ensure_ascii=False, separators=(",", ":")
        )
        byte_count = len(text.encode("utf-8")) + len(schema.encode("utf-8"))
        return max(1, (byte_count + 2) // 3)
