from __future__ import annotations

import json
import subprocess
import sys
from threading import Event, Timer

import pytest

from audio_story.adapters.llm import (
    DeterministicMockAdapter,
    GenerationRequest,
    LlamaCppAdapter,
    LlamaCppConfig,
    LLMAdapterError,
    PromptCapsule,
)
from audio_story.adapters.llm.llama_cpp import _RejectRedirect
from audio_story.adapters.llm.models import GenerationKind
from audio_story.config import ConfigurationError, require_loopback_endpoint


def _request() -> GenerationRequest:
    return GenerationRequest(
        PromptCapsule(b'{"capsule":true}', "a" * 64),
        "Return JSON",
        GenerationKind.STRUCTURED,
        64,
        seed=7,
    )


def test_mock_is_deterministic_and_implements_all_surfaces() -> None:
    first = DeterministicMockAdapter()
    second = DeterministicMockAdapter()
    request = _request()
    assert first.generate_structured(request, Event()) == second.generate_structured(
        request, Event()
    )
    assert first.generate_text(request, Event()).content
    assert first.assess_semantic(request, Event()).label == "MOCK_REVIEW"
    assert first.health()["status"] == "READY"
    assert first.capabilities()["structured_output"] is True
    first.unload()


def test_mock_failure_and_cancellation_never_become_success() -> None:
    cancelled = Event()
    cancelled.set()
    with pytest.raises(LLMAdapterError) as caught:
        DeterministicMockAdapter().generate_text(_request(), cancelled)
    assert caught.value.code == "LLM004_CANCELLED"
    failure = LLMAdapterError("LLM006_BACKEND_FAILURE", "crash")
    with pytest.raises(LLMAdapterError) as caught:
        DeterministicMockAdapter(failures=[failure]).generate_structured(_request(), Event())
    assert caught.value is failure


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.openai.com/v1",
        "http://192.168.1.8:8080",
        "file:///tmp/model",
        "http://127.0.0.1.evil.example",
    ],
)
def test_non_loopback_endpoints_are_rejected(endpoint: str) -> None:
    with pytest.raises(ConfigurationError) as caught:
        require_loopback_endpoint(endpoint)
    assert caught.value.code == "LLM001_NON_LOOPBACK_ENDPOINT"


def test_http_redirect_is_rejected_before_following_target() -> None:
    with pytest.raises(LLMAdapterError) as caught:
        _RejectRedirect().redirect_request()
    assert caught.value.code == "LLM001_NON_LOOPBACK_ENDPOINT"


def test_loopback_http_backend_without_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"content":"{\\"ok\\":true}","model":"local.gguf"}'

    seen: list[str] = []

    def fake_urlopen(request: object, timeout: float) -> Response:
        seen.append(str(request.full_url))  # type: ignore[attr-defined]
        assert timeout == 1
        return Response()

    monkeypatch.setattr("audio_story.adapters.llm.llama_cpp._open_local", fake_urlopen)
    adapter = LlamaCppAdapter(LlamaCppConfig(timeout_seconds=1))
    result = adapter.generate_structured(_request(), Event())
    assert result.content == b'{"ok":true}'
    assert result.model_identity == "local.gguf"
    assert seen == ["http://127.0.0.1:8080/completion"]


def test_http_truncated_output_and_invalid_semantic_are_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"content": "x", "stop_reason": "length"}).encode()

    monkeypatch.setattr(
        "audio_story.adapters.llm.llama_cpp._open_local", lambda *args, **kwargs: Response()
    )
    adapter = LlamaCppAdapter(LlamaCppConfig())
    with pytest.raises(LLMAdapterError) as caught:
        adapter.generate_structured(_request(), Event())
    assert caught.value.code == "LLM008_TRUNCATED_OUTPUT"

    class SemanticResponse(Response):
        def read(self) -> bytes:
            return b'{"content":"{}"}'

    monkeypatch.setattr(
        "audio_story.adapters.llm.llama_cpp._open_local",
        lambda *args, **kwargs: SemanticResponse(),
    )
    with pytest.raises(LLMAdapterError) as caught:
        adapter.assess_semantic(_request(), Event())
    assert caught.value.code == "LLM011_SEMANTIC_RESPONSE"


def test_subprocess_success_nonzero_empty_timeout_and_cancellation() -> None:
    success = LlamaCppAdapter(
        LlamaCppConfig(
            endpoint=None, command=(sys.executable, "-c", "print('{}')"), timeout_seconds=2
        )
    )
    assert success.generate_structured(_request(), Event()).content.strip() == b"{}"

    cases = [
        ((sys.executable, "-c", "raise SystemExit(3)"), "LLM007_NON_ZERO_EXIT", 2.0),
        ((sys.executable, "-c", "pass"), "LLM008_TRUNCATED_OUTPUT", 2.0),
        ((sys.executable, "-c", "import time; time.sleep(2)"), "LLM003_TIMEOUT", 0.05),
    ]
    for command, code, timeout in cases:
        adapter = LlamaCppAdapter(
            LlamaCppConfig(endpoint=None, command=command, timeout_seconds=timeout)
        )
        with pytest.raises(LLMAdapterError) as caught:
            adapter.generate_structured(_request(), Event())
        assert caught.value.code == code

    cancelled = Event()
    cancelled.set()
    adapter = LlamaCppAdapter(
        LlamaCppConfig(endpoint=None, command=(sys.executable, "-c", "print('{}')"))
    )
    with pytest.raises(LLMAdapterError) as caught:
        adapter.generate_structured(_request(), cancelled)
    assert caught.value.code == "LLM004_CANCELLED"
    assert adapter._process is None


def test_subprocess_spawn_crash_is_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    def crash(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        raise OSError("missing executable")

    monkeypatch.setattr(subprocess, "Popen", crash)
    adapter = LlamaCppAdapter(LlamaCppConfig(endpoint=None, command=("llama-cli",)))
    with pytest.raises(LLMAdapterError) as caught:
        adapter.generate_structured(_request(), Event())
    assert caught.value.code == "LLM006_BACKEND_FAILURE"


def test_running_subprocess_is_terminated_on_cancellation() -> None:
    cancellation = Event()
    timer = Timer(0.05, cancellation.set)
    timer.start()
    adapter = LlamaCppAdapter(
        LlamaCppConfig(
            endpoint=None,
            command=(sys.executable, "-c", "import time; time.sleep(5)"),
            timeout_seconds=2,
        )
    )
    with pytest.raises(LLMAdapterError) as caught:
        adapter.generate_structured(_request(), cancellation)
    timer.join()
    assert caught.value.code == "LLM004_CANCELLED"
    assert adapter._process is None


def test_health_and_model_capability_probes_are_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = iter(
        [
            b'{"status":"ok"}',
            b'{"model_path":"models/local.gguf","n_ctx":4096}',
        ]
    )

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return next(payloads)

    urls: list[str] = []

    def fake_urlopen(request: object, timeout: float) -> Response:
        urls.append(str(request.full_url))  # type: ignore[attr-defined]
        return Response()

    monkeypatch.setattr("audio_story.adapters.llm.llama_cpp._open_local", fake_urlopen)
    adapter = LlamaCppAdapter(LlamaCppConfig())
    assert adapter.health()["status"] == "ok"
    assert adapter.capabilities()["context_size"] == 4096
    assert urls == ["http://127.0.0.1:8080/health", "http://127.0.0.1:8080/props"]


def test_http_cancellation_after_response_never_returns_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancellation = Event()

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            cancellation.set()
            return b'{"content":"do not commit"}'

    monkeypatch.setattr(
        "audio_story.adapters.llm.llama_cpp._open_local", lambda *args, **kwargs: Response()
    )
    with pytest.raises(LLMAdapterError) as caught:
        LlamaCppAdapter(LlamaCppConfig()).generate_structured(_request(), cancellation)
    assert caught.value.code == "LLM004_CANCELLED"
