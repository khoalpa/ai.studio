from __future__ import annotations

import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ai_story.errors import (
    CircuitOpenError,
    RuntimeCancelledError,
    RuntimeRequestTooLargeError,
    RuntimeTimeoutError,
    RuntimeUnavailableError,
)
from ai_story.runtime import (
    CancellationToken,
    GenerationRequest,
    GenerationResult,
    HealthReport,
    ProviderRuntimeRegistry,
    RuntimeCapabilities,
)
from ai_story.runtime.llama_cpp import LlamaCppRuntime


class FakeTextRuntime:
    runtime_id = "llama_cpp"

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0
        self.unloads = 0
        self.last_request = None

    def health(self):
        return HealthReport("PASS", self.runtime_id, loaded_model="fake.gguf")

    def capabilities(self):
        return RuntimeCapabilities(text=True, structured_json=True, model_unload=True)

    def generate_text(self, request, cancellation=None):
        self.last_request = request
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeUnavailableError("temporary failure")
        return GenerationResult("ok", request.model, self.runtime_id)

    def generate_json(self, request, cancellation=None):
        self.last_request = request
        self.calls += 1
        return json.loads('{"ok":true}')

    def generate_image(self, request, cancellation=None):
        raise AssertionError("not used")

    def assess_image(self, image, request, cancellation=None):
        raise AssertionError("not used")

    def unload(self):
        self.unloads += 1


class RuntimeRegistryTests(unittest.TestCase):
    def test_llama_rejects_oversized_input_before_http(self) -> None:
        runtime = LlamaCppRuntime(
            "http://127.0.0.1:8080", max_context_tokens=100, max_input_tokens=60
        )
        request = GenerationRequest(
            "x" * 1000,
            json_schema={"type": "object"},
            parameters={"max_tokens": 10},
        )
        with patch("ai_story.runtime.llama_cpp.urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(RuntimeRequestTooLargeError, "REQUEST_TOO_LARGE"):
                runtime.generate_json(request)
            urlopen.assert_not_called()

    def test_llama_rejects_combined_input_and_output_over_context(self) -> None:
        runtime = LlamaCppRuntime(
            "http://127.0.0.1:8080", max_context_tokens=100, max_input_tokens=80
        )
        request = GenerationRequest(
            "x" * 90,
            parameters={"max_tokens": 75},
            json_schema={"type": "object"},
        )
        with patch("ai_story.runtime.llama_cpp.urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(RuntimeRequestTooLargeError, "input plus requested output"):
                runtime.generate_json(request)
            urlopen.assert_not_called()

    def test_request_too_large_is_not_retried(self) -> None:
        class TooLargeRuntime(FakeTextRuntime):
            def generate_json(self, request, cancellation=None):
                self.calls += 1
                raise RuntimeRequestTooLargeError("REQUEST_TOO_LARGE")

        runtime = TooLargeRuntime()
        events = []
        registry = ProviderRuntimeRegistry(
            "local", runtime_overrides={"llama_cpp": runtime},
            telemetry=events.append, sleep=lambda _: None,
        )
        try:
            with self.assertRaises(RuntimeRequestTooLargeError):
                registry.generate_json(
                    "story",
                    GenerationRequest(
                        "large", json_schema={"type": "object"}
                    ),
                )
            self.assertEqual(runtime.calls, 1)
            self.assertEqual(events[0]["status"], "REQUEST_TOO_LARGE")
        finally:
            registry.close()

    def test_llama_structured_generation_accepts_fenced_json(self) -> None:
        runtime = LlamaCppRuntime("http://127.0.0.1:8080")
        with patch.object(
            runtime,
            "generate_text",
            return_value=GenerationResult(
                '```json\n{"ok": true}\n```', "fake", runtime.runtime_id
            ),
        ):
            value = runtime.generate_json(
                GenerationRequest("json", json_schema={"type": "object"})
            )
        self.assertEqual(value, {"ok": True})

    def test_llama_structured_generation_accepts_json_with_leading_text(self) -> None:
        runtime = LlamaCppRuntime("http://127.0.0.1:8080")
        with patch.object(
            runtime,
            "generate_text",
            return_value=GenerationResult(
                'Result: {"ok": true}', "fake", runtime.runtime_id
            ),
        ):
            value = runtime.generate_json(
                GenerationRequest("json", json_schema={"type": "object"})
            )
        self.assertEqual(value, {"ok": True})

    def test_llama_http_body_uses_total_deadline(self) -> None:
        class Response:
            fp = None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size):
                return b"partial"

        runtime = LlamaCppRuntime("http://127.0.0.1:8080")
        with patch("ai_story.runtime.llama_cpp.urllib.request.urlopen", return_value=Response()), patch(
            "ai_story.runtime.llama_cpp.time.monotonic", side_effect=[0.0, 0.5, 2.0]
        ):
            with self.assertRaises(RuntimeTimeoutError):
                runtime._request("GET", "/health", None, 1.0)

    def test_llama_post_uses_killable_hard_deadline(self) -> None:
        runtime = LlamaCppRuntime("http://127.0.0.1:8080")
        with patch("ai_story.runtime.llama_cpp.shutil.which", return_value="curl.exe"), patch(
            "ai_story.runtime.llama_cpp.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["curl.exe"], 6.0),
        ) as run:
            with self.assertRaisesRegex(RuntimeTimeoutError, "hard deadline"):
                runtime._request("POST", "/v1/chat/completions", {"prompt": "x"}, 1.0)
        self.assertEqual(run.call_args.kwargs["timeout"], 6.0)

    def test_llama_post_maps_curl_timeout_exit(self) -> None:
        runtime = LlamaCppRuntime("http://127.0.0.1:8080")
        result = SimpleNamespace(returncode=28, stdout=b"", stderr=b"timed out")
        with patch("ai_story.runtime.llama_cpp.shutil.which", return_value="curl.exe"), patch(
            "ai_story.runtime.llama_cpp.subprocess.run", return_value=result
        ):
            with self.assertRaises(RuntimeTimeoutError):
                runtime._request("POST", "/v1/chat/completions", {}, 2.0)

    def test_local_role_resolves_runtime_and_capabilities(self) -> None:
        runtime = FakeTextRuntime()
        registry = ProviderRuntimeRegistry(
            "local", runtime_overrides={"llama_cpp": runtime}, sleep=lambda _: None
        )
        try:
            status = registry.status()
            self.assertEqual(status["roles"]["story"]["adapter"], "local_text")
            self.assertTrue(status["runtimes"]["llama_cpp"]["capabilities"]["structured_json"])
            self.assertIn(
                status["runtimes"]["diffusers"]["health"]["status"],
                {"PASS", "NOT_INSTALLED", "UNAVAILABLE", "DOWNLOAD_REQUIRED"},
            )
        finally:
            registry.close()

    def test_retry_and_redacted_telemetry(self) -> None:
        runtime = FakeTextRuntime(failures=1)
        events = []
        registry = ProviderRuntimeRegistry(
            "text_local",
            runtime_overrides={"llama_cpp": runtime},
            telemetry=events.append,
            sleep=lambda _: None,
        )
        try:
            result = registry.generate_text(
                "story", GenerationRequest("SECRET PROMPT", request_id="request-secret")
            )
            self.assertEqual(result.text, "ok")
            self.assertEqual(runtime.calls, 2)
            serialized = json.dumps(events)
            self.assertNotIn("SECRET PROMPT", serialized)
            self.assertNotIn("request-secret", serialized)
            self.assertEqual([item["status"] for item in events], ["RETRYABLE_ERROR", "PASS"])
        finally:
            registry.close()

    def test_cancelled_request_never_reaches_runtime(self) -> None:
        runtime = FakeTextRuntime()
        registry = ProviderRuntimeRegistry(
            "local", runtime_overrides={"llama_cpp": runtime}, sleep=lambda _: None
        )
        token = CancellationToken()
        token.cancel()
        try:
            with self.assertRaises(RuntimeCancelledError):
                registry.generate_text("story", GenerationRequest("ignored"), token)
            self.assertEqual(runtime.calls, 0)
        finally:
            registry.close()

    def test_structured_generation_keeps_schema(self) -> None:
        runtime = FakeTextRuntime()
        registry = ProviderRuntimeRegistry(
            "local", runtime_overrides={"llama_cpp": runtime}, sleep=lambda _: None
        )
        try:
            result = registry.generate_json(
                "story",
                GenerationRequest(
                    "return JSON",
                    json_schema={
                        "type": "object",
                        "required": ["ok"],
                        "properties": {"ok": {"type": "boolean"}},
                    },
                ),
            )
            self.assertEqual(result, {"ok": True})
        finally:
            registry.close()

    def test_llama_timeout_scales_with_generation_budget(self) -> None:
        runtime = FakeTextRuntime()
        registry = ProviderRuntimeRegistry(
            "local", runtime_overrides={"llama_cpp": runtime}, sleep=lambda _: None
        )
        try:
            registry.generate_text(
                "story", GenerationRequest("long response", parameters={"max_tokens": 2048})
            )
            self.assertEqual(runtime.last_request.timeout_seconds, 542.0)
        finally:
            registry.close()

    def test_llama_timeout_is_capped_for_large_generation_budget(self) -> None:
        runtime = FakeTextRuntime()
        registry = ProviderRuntimeRegistry(
            "local", runtime_overrides={"llama_cpp": runtime}, sleep=lambda _: None
        )
        try:
            registry.generate_text(
                "story", GenerationRequest("long response", parameters={"max_tokens": 8192})
            )
            self.assertEqual(runtime.last_request.timeout_seconds, 600.0)
        finally:
            registry.close()

    def test_role_preparer_runs_before_each_runtime_call(self) -> None:
        runtime = FakeTextRuntime()
        prepared = []
        registry = ProviderRuntimeRegistry(
            "text_local",
            runtime_overrides={"llama_cpp": runtime},
            role_preparer=lambda role, binding: prepared.append(
                (role, binding["adapter"])
            ),
            sleep=lambda _: None,
        )
        try:
            registry.generate_text("story", GenerationRequest("story"))
            registry.generate_text("safety", GenerationRequest("safety"))
            self.assertEqual(
                prepared,
                [("story", "local_text"), ("safety", "local_safety")],
            )
        finally:
            registry.close()

    def test_timeout_requests_runtime_recovery_before_retry(self) -> None:
        class TimeoutOnceRuntime(FakeTextRuntime):
            def generate_text(self, request, cancellation=None):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeTimeoutError("deadline")
                return GenerationResult("ok", request.model, self.runtime_id)

        runtime = TimeoutOnceRuntime()
        prepared = []
        registry = ProviderRuntimeRegistry(
            "local",
            runtime_overrides={"llama_cpp": runtime},
            role_preparer=lambda role, binding: prepared.append(
                (role, binding.get("recovery_reason"))
            ),
            sleep=lambda _: None,
        )
        try:
            self.assertEqual(
                registry.generate_text("story", GenerationRequest("story")).text, "ok"
            )
            self.assertEqual(
                prepared,
                [("story", None), ("story", "HARD_TIMEOUT"), ("story", None)],
            )
        finally:
            registry.close()

    def test_structured_generation_rejects_schema_violation(self) -> None:
        runtime = FakeTextRuntime()
        registry = ProviderRuntimeRegistry(
            "local", runtime_overrides={"llama_cpp": runtime}, sleep=lambda _: None
        )
        try:
            with self.assertRaisesRegex(RuntimeUnavailableError, "missing required"):
                registry.generate_json(
                    "story",
                    GenerationRequest(
                        "return JSON",
                        json_schema={
                            "type": "object",
                            "required": ["title"],
                            "properties": {"title": {"type": "string"}},
                        },
                    ),
                )
        finally:
            registry.close()

    def test_circuit_opens_after_repeated_runtime_failures(self) -> None:
        runtime = FakeTextRuntime(failures=20)
        registry = ProviderRuntimeRegistry(
            "local", runtime_overrides={"llama_cpp": runtime}, sleep=lambda _: None
        )
        try:
            with self.assertRaises(RuntimeUnavailableError):
                registry.generate_text("story", GenerationRequest("first"))
            with self.assertRaises(CircuitOpenError):
                registry.generate_text("story", GenerationRequest("second"))
        finally:
            registry.close()

    def test_open_circuit_requests_supervisor_recovery_on_next_call(self) -> None:
        runtime = FakeTextRuntime(failures=3)
        prepared = []
        registry = ProviderRuntimeRegistry(
            "local",
            runtime_overrides={"llama_cpp": runtime},
            role_preparer=lambda role, binding: prepared.append(
                (role, binding.get("recovery_reason"))
            ),
            sleep=lambda _: None,
        )
        try:
            with self.assertRaises(RuntimeUnavailableError):
                registry.generate_text("story", GenerationRequest("first"))

            result = registry.generate_text("story", GenerationRequest("second"))

            self.assertEqual(result.text, "ok")
            self.assertIn(("story", "CIRCUIT_OPEN"), prepared)
            self.assertEqual(runtime.calls, 4)
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
