from __future__ import annotations

import importlib.util
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, TypeVar

from ..errors import (
    CircuitOpenError,
    ConfigurationError,
    RuntimeCancelledError,
    RuntimeRequestTooLargeError,
    RuntimeTimeoutError,
    RuntimeUnavailableError,
)
from ..image_models import resolve_image_model_profile
from ..model_cache import image_model_status
from ..provider_config import PROVIDER_ROLES, load_provider_config
from .base import CancellationToken, GenerationRequest, ModelRuntime
from .builtin import BuiltinRuntime, UnavailableRuntime
from .diffusers_runtime import DiffusersRuntime
from .llama_cpp import LlamaCppRuntime

T = TypeVar("T")
TelemetrySink = Callable[[dict[str, Any]], None]
RolePreparer = Callable[[str, dict[str, Any]], None]


@dataclass
class CircuitBreaker:
    failure_threshold: int
    recovery_seconds: float
    failures: int = 0
    opened_at: float | None = None

    def before_call(self) -> None:
        if self.opened_at is None:
            return
        if time.monotonic() - self.opened_at >= self.recovery_seconds:
            self.failures = 0
            self.opened_at = None
            return
        raise CircuitOpenError("Provider circuit is open")

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()


class ProviderRuntimeRegistry:
    """Resolves role -> adapter -> runtime and enforces runtime policies."""

    def __init__(
        self,
        mode: str | None = None,
        *,
        runtime_overrides: dict[str, ModelRuntime] | None = None,
        telemetry: TelemetrySink | None = None,
        sleep: Callable[[float], None] = time.sleep,
        config: dict[str, Any] | None = None,
        role_preparer: RolePreparer | None = None,
    ) -> None:
        self.config = config or load_provider_config(mode)
        self.telemetry = telemetry
        self._metric_events: list[dict[str, Any]] = []
        self._sleep = sleep
        self._role_preparer = role_preparer
        self._lock = threading.RLock()
        self._active_runtime: str | None = None
        policy = self.config.get("policy", {})
        circuit = policy.get("circuit_breaker", {})
        self._retry_attempts = max(1, int(policy.get("retry_attempts", 1)))
        self._retry_backoff = max(0.0, float(policy.get("retry_backoff_seconds", 0.25)))
        self._default_timeout = max(0.1, float(policy.get("default_timeout_seconds", 120)))
        llama_settings = self.config.get("runtimes", {}).get("llama_cpp", {})
        self._minimum_generation_tokens_per_second = max(
            0.1, float(llama_settings.get("minimum_generation_tokens_per_second", 4.0))
        )
        self._generation_timeout_overhead = max(
            0.0, float(llama_settings.get("generation_timeout_overhead_seconds", 30.0))
        )
        self._maximum_generation_timeout = max(
            self._default_timeout,
            float(llama_settings.get("maximum_generation_timeout_seconds", 600.0)),
        )
        self._exclusive_gpu = bool(policy.get("exclusive_accelerator", True))
        self._breakers = {
            role: CircuitBreaker(
                max(1, int(circuit.get("failure_threshold", 3))),
                max(0.1, float(circuit.get("recovery_seconds", 30))),
            )
            for role in PROVIDER_ROLES
        }
        self._role_runtime_keys: dict[str, str] = {}
        self._runtimes = self._create_runtimes(runtime_overrides or {})

    def _create_runtimes(self, overrides: dict[str, ModelRuntime]) -> dict[str, ModelRuntime]:
        runtimes: dict[str, ModelRuntime] = {}
        runtime_config = self.config.get("runtimes", {})
        for role, adapter_name in self.config["selected"].items():
            adapter = self.config["adapters"][adapter_name]
            runtime_name = adapter["runtime"]
            runtime_key = runtime_name
            if runtime_name == "diffusers":
                profile = resolve_image_model_profile(self.config, adapter)
                runtime_key = f"diffusers:{profile.profile_id}:{profile.model_id}"
            self._role_runtime_keys[role] = runtime_key
            if runtime_key in runtimes:
                continue
            if runtime_name in overrides:
                runtimes[runtime_key] = overrides[runtime_name]
                continue
            if runtime_name == "builtin":
                runtimes[runtime_key] = BuiltinRuntime()
            elif runtime_name == "llama_cpp":
                settings = runtime_config.get(runtime_name, {})
                runtimes[runtime_key] = LlamaCppRuntime(
                    settings.get("endpoint", "http://127.0.0.1:8080"),
                    float(settings.get("timeout_seconds", self._default_timeout)),
                    max_context_tokens=int(settings.get("max_context_tokens", 16384)),
                    max_input_tokens=int(settings.get("max_input_tokens", 12000)),
                )
            elif runtime_name == "diffusers":
                profile = resolve_image_model_profile(self.config, adapter)
                settings = profile.settings(runtime_config.get(runtime_name, {}))
                runtimes[runtime_key] = DiffusersRuntime(settings, runtime_id=runtime_key)
            else:
                runtimes[runtime_key] = UnavailableRuntime(
                    runtime_name, f"Runtime '{runtime_name}' has no installed factory"
                )
        return runtimes

    def binding(self, role: str) -> dict[str, Any]:
        if role not in PROVIDER_ROLES:
            raise ConfigurationError(f"Unknown provider role: {role}")
        adapter_name = self.config["selected"][role]
        adapter = self.config["adapters"][adapter_name]
        return {"role": role, "adapter": adapter_name, **adapter}

    def runtime_for(self, role: str) -> ModelRuntime:
        try:
            return self._runtimes[self._role_runtime_keys[role]]
        except KeyError as exc:
            raise ConfigurationError(f"Runtime is unavailable for role '{role}'") from exc

    def image_settings(self, role: str) -> dict[str, Any]:
        binding = self.binding(role)
        if binding.get("runtime") != "diffusers":
            raise ConfigurationError(f"Role '{role}' is not bound to an image runtime")
        profile = resolve_image_model_profile(self.config, binding)
        return profile.settings(self.config["runtimes"]["diffusers"])

    def status(self, probe: bool = True) -> dict[str, Any]:
        runtime_status: dict[str, Any] = {}
        base_counts: dict[str, int] = {}
        for key in self._runtimes:
            base = key.split(":", 1)[0]
            base_counts[base] = base_counts.get(base, 0) + 1
        for name, runtime in self._runtimes.items():
            base = name.split(":", 1)[0]
            display_name = base if base_counts[base] == 1 else name
            runtime_status[display_name] = {
                "health": runtime.health().to_dict() if probe else {"status": "NOT_PROBED"},
                "capabilities": runtime.capabilities().to_dict(),
            }
        return {
            "mode": self.config["active_mode"],
            "roles": {
                role: {
                    key: value
                    for key, value in self.binding(role).items()
                    if key != "model_file"
                }
                for role in sorted(PROVIDER_ROLES)
            },
            "runtimes": runtime_status,
            "policy": self.config.get("policy", {}),
            "image_qa": self._image_qa_status(),
        }

    def _image_qa_status(self) -> dict[str, Any]:
        settings = self.config.get("runtimes", {}).get("diffusers", {}).get("qa", {})
        selected = any(
            self.config["adapters"][name]["runtime"] == "diffusers"
            for name in self.config["selected"].values()
        )
        if not selected:
            return {"status": "NOT_SELECTED"}
        ocr = settings.get("tesseract_path") or shutil.which("tesseract")
        dependencies = all(
            importlib.util.find_spec(name) is not None for name in ("PIL", "torch", "transformers")
        )
        ready = bool(
            dependencies
            and (ocr or not settings.get("require_ocr"))
            and (settings.get("semantic_model") or not settings.get("require_semantic"))
        )
        cache = image_model_status(self.config) if ready else {"status": "NOT_READY", "models": {}}
        return {
            "status": cache["status"] if ready else "NOT_READY",
            "ocr_available": bool(ocr),
            "semantic_model": settings.get("semantic_model"),
            "semantic_required": bool(settings.get("require_semantic")),
            "models": cache.get("models", {}),
        }

    def generate_text(
        self, role: str, request: GenerationRequest, cancellation: CancellationToken | None = None
    ):
        runtime = self.runtime_for(role)
        return self._execute(role, runtime, "generate_text", request, cancellation)

    def generate_json(
        self, role: str, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> dict[str, Any]:
        if request.json_schema is None:
            raise ConfigurationError("Structured generation requires json_schema")
        runtime = self.runtime_for(role)
        value = self._execute(role, runtime, "generate_json", request, cancellation)
        _validate_schema_subset(value, request.json_schema, "$")
        return value

    def generate_image(
        self, role: str, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> bytes:
        runtime = self.runtime_for(role)
        capabilities = runtime.capabilities()
        if not capabilities.image or not capabilities.image_text_to_image:
            raise ConfigurationError(f"Image runtime for '{role}' cannot generate images")
        if request.parameters.get("init_image") is not None and not capabilities.image_to_image:
            raise ConfigurationError(f"Image model for '{role}' does not support image-to-image")
        if request.parameters.get("outpaint_image") is not None and not capabilities.image_outpainting:
            raise ConfigurationError(f"Image model for '{role}' does not support outpainting")
        if (request.parameters.get("reference_images") or request.parameters.get("reference_inputs")) and not capabilities.image_reference:
            raise ConfigurationError(f"Image model for '{role}' does not support reference images")
        if request.parameters.get("control_inputs") and not capabilities.image_controlnet:
            raise ConfigurationError(f"Image model for '{role}' does not support ControlNet inputs")
        return self._execute(role, runtime, "generate_image", request, cancellation)

    def image_postprocess_metadata(self, role: str) -> dict[str, Any]:
        runtime = self.runtime_for(role)
        return dict(getattr(runtime, "last_image_metadata", {}))

    def close(self) -> None:
        for runtime in self._runtimes.values():
            runtime.unload()
        self._active_runtime = None

    def metrics(self) -> dict[str, Any]:
        return {
            "call_count": sum(item["status"] == "PASS" for item in self._metric_events),
            "attempt_count": len(self._metric_events),
            "retry_count": sum(item["attempt"] > 1 for item in self._metric_events),
            "failure_count": sum(item["status"] not in {"PASS", "CANCELLED"} for item in self._metric_events),
            "duration_ms": round(sum(float(item["duration_ms"]) for item in self._metric_events), 3),
            "estimated_cost_usd": 0.0,
            "cost_basis": "LOCAL_RUNTIME_NO_METERED_API",
            "roles": sorted({str(item["role"]) for item in self._metric_events}),
        }

    def _execute(
        self,
        role: str,
        runtime: ModelRuntime,
        operation: str,
        request: GenerationRequest,
        cancellation: CancellationToken | None,
    ) -> T:
        token = cancellation or CancellationToken()
        breaker = self._breakers[role]
        timeout_seconds = request.timeout_seconds or self._default_timeout
        max_tokens = request.parameters.get("max_tokens")
        if runtime.runtime_id == "llama_cpp" and max_tokens is not None:
            timeout_seconds = min(
                self._maximum_generation_timeout,
                max(
                    timeout_seconds,
                    float(max_tokens) / self._minimum_generation_tokens_per_second
                    + self._generation_timeout_overhead,
                ),
            )
        effective_request = GenerationRequest(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            model=request.model or self.binding(role).get("model_id"),
            parameters={**self.binding(role).get("parameters", {}), **request.parameters},
            json_schema=request.json_schema,
            timeout_seconds=timeout_seconds,
            request_id=request.request_id,
        )
        for attempt in range(1, self._retry_attempts + 1):
            started = time.monotonic()
            token.raise_if_cancelled()
            try:
                breaker.before_call()
            except CircuitOpenError:
                if self._role_preparer is None:
                    raise
                recovery_binding = self.binding(role)
                recovery_binding["recovery_reason"] = "CIRCUIT_OPEN"
                self._role_preparer(role, recovery_binding)
                # A successful preparer call means the supervised runtime is
                # healthy again. Close the stale circuit immediately instead of
                # making a checkpointed workflow wait for a wall-clock cooldown.
                breaker.success()
            try:
                with self._runtime_session(runtime):
                    if self._role_preparer is not None:
                        self._role_preparer(role, self.binding(role))
                    result = getattr(runtime, operation)(effective_request, token)
            except RuntimeCancelledError:
                self._emit(role, runtime.runtime_id, operation, attempt, started, "CANCELLED")
                raise
            except RuntimeRequestTooLargeError:
                self._emit(role, runtime.runtime_id, operation, attempt, started, "REQUEST_TOO_LARGE")
                raise
            except (RuntimeUnavailableError, RuntimeTimeoutError) as exc:
                breaker.failure()
                self._emit(role, runtime.runtime_id, operation, attempt, started, "RETRYABLE_ERROR")
                if attempt >= self._retry_attempts:
                    raise
                if isinstance(exc, RuntimeTimeoutError) and self._role_preparer is not None:
                    recovery_binding = self.binding(role)
                    recovery_binding["recovery_reason"] = "HARD_TIMEOUT"
                    self._role_preparer(role, recovery_binding)
                token.raise_if_cancelled()
                self._sleep(self._retry_backoff * attempt)
            else:
                breaker.success()
                self._emit(role, runtime.runtime_id, operation, attempt, started, "PASS")
                return result
        raise RuntimeUnavailableError("Runtime request exhausted retry policy")

    @contextmanager
    def _runtime_session(self, runtime: ModelRuntime) -> Iterator[None]:
        lock = self._lock if self._exclusive_gpu else _NullLock()
        with lock:
            if self._active_runtime and self._active_runtime != runtime.runtime_id:
                self._runtimes[self._active_runtime].unload()
            self._active_runtime = runtime.runtime_id
            yield

    def _emit(
        self, role: str, runtime: str, operation: str, attempt: int, started: float, status: str
    ) -> None:
        record = {
                "event": "MODEL_RUNTIME_CALL",
                "role": role,
                "runtime": runtime,
                "operation": operation,
                "attempt": attempt,
                "status": status,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
            }
        self._metric_events.append(record)
        if self.telemetry:
            # Deliberately exclude prompts, responses, headers, model paths and environment values.
            self.telemetry(record)


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def _validate_schema_subset(value: Any, schema: dict[str, Any], locator: str) -> None:
    """Validate the JSON-schema subset used by local structured generation."""
    expected = schema.get("type")
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected in checks and not checks[expected](value):
        raise RuntimeUnavailableError(f"Structured response violates schema type at {locator}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise RuntimeUnavailableError(
                    f"Structured response is missing required property {locator}.{key}"
                )
        properties = schema.get("properties", {})
        for key, child in properties.items():
            if key in value and isinstance(child, dict):
                _validate_schema_subset(value[key], child, f"{locator}.{key}")
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                raise RuntimeUnavailableError(
                    f"Structured response contains unknown properties at {locator}: {sorted(extra)}"
                )
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            _validate_schema_subset(item, schema["items"], f"{locator}[{index}]")
