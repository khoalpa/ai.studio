from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from threading import Event
from urllib.request import Request

import pytest

from audio_story.adapters.image import ComfyUIConfig, ImageAdapterError, ImageRequest
from audio_story.adapters.image.comfyui import ComfyUIImageAdapter


def _workflow(tmp_path: Path) -> tuple[Path, str]:
    value = {
        "2": {"inputs": {"text": "default positive"}},
        "3": {"inputs": {"text": "default negative"}},
        "4": {"inputs": {}},
        "5": {"inputs": {}},
        "7": {"inputs": {}},
    }
    path = tmp_path / "workflow.json"
    data = json.dumps(value, separators=(",", ":")).encode()
    path.write_bytes(data)
    return path, sha256(data).hexdigest()


def _request(digest: str, *, timeout: float = 1.0) -> ImageRequest:
    return ImageRequest(
        "cover.png", "a" * 64, digest, "sdxl", 7, 1, 32, 32, "PNG", timeout, "tx", "call"
    )


def test_real_api_sequence_returns_single_view_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow, digest = _workflow(tmp_path)
    calls: list[str] = []

    def fake_http(request: Request, timeout: float) -> bytes:
        calls.append(request.full_url)
        if request.full_url.endswith("/prompt"):
            return b'{"prompt_id":"pid"}'
        if "/history/" in request.full_url:
            return json.dumps(
                {"pid": {"outputs": {"7": {"images": [{"filename": "one.png"}]}}}}
            ).encode()
        return b"png-bytes"

    adapter = ComfyUIImageAdapter(ComfyUIConfig(workflow_path=workflow))
    monkeypatch.setattr(adapter, "_http", fake_http)
    assert adapter.generate_image(_request(digest), Event()).content == b"png-bytes"
    assert [url.split("?")[0].rsplit("/", 1)[-1] for url in calls] == [
        "prompt",
        "pid",
        "view",
    ]


def test_real_api_injects_digest_bound_dynamic_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow, digest = _workflow(tmp_path)
    submitted: dict[str, object] = {}

    def fake_http(request: Request, timeout: float) -> bytes:
        if request.full_url.endswith("/prompt"):
            submitted.update(json.loads(request.data))
            return b'{"prompt_id":"pid"}'
        if "/history/" in request.full_url:
            return b'{"pid":{"outputs":{"7":{"images":[{"filename":"one.png"}]}}}}'
        return b"png-bytes"

    adapter = ComfyUIImageAdapter(ComfyUIConfig(workflow_path=workflow))
    monkeypatch.setattr(adapter, "_http", fake_http)
    request = _request(digest)
    request = __import__("dataclasses").replace(
        request,
        commitment_context={
            "positive_prompt": "portrait of An",
            "negative_prompt": "text, watermark",
        },
    )
    adapter.generate_image(request, Event())
    prompt = submitted["prompt"]
    assert isinstance(prompt, dict)
    assert prompt["2"]["inputs"]["text"] == "portrait of An"
    assert prompt["3"]["inputs"]["text"] == "text, watermark"


@pytest.mark.parametrize(
    ("prompt_body", "history_body", "code"),
    [
        (b"{}", b"{}", "IMG014_PROMPT_ID"),
        (b'{"prompt_id":"pid"}', b'{"pid":{"outputs":{}}}', "IMG010_OUTPUT_CARDINALITY"),
        (
            b'{"prompt_id":"pid"}',
            b'{"pid":{"outputs":{"7":{"images":[{"filename":"a"},{"filename":"b"}]}}}}',
            "IMG010_OUTPUT_CARDINALITY",
        ),
    ],
)
def test_real_api_rejects_bad_prompt_and_cardinality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt_body: bytes,
    history_body: bytes,
    code: str,
) -> None:
    workflow, digest = _workflow(tmp_path)
    bodies = iter((prompt_body, history_body))
    adapter = ComfyUIImageAdapter(ComfyUIConfig(workflow_path=workflow))
    monkeypatch.setattr(adapter, "_http", lambda request, timeout: next(bodies))
    with pytest.raises(ImageAdapterError, match=code):
        adapter.generate_image(_request(digest), Event())


def test_real_api_rejects_workflow_drift_and_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow, digest = _workflow(tmp_path)
    adapter = ComfyUIImageAdapter(ComfyUIConfig(workflow_path=workflow))
    with pytest.raises(ImageAdapterError, match="IMG013_WORKFLOW_DIGEST"):
        adapter.generate_image(_request("0" * 64), Event())


def test_real_api_rejects_malformed_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow, digest = _workflow(tmp_path)
    bodies = iter((b'{"prompt_id":"pid"}', b"not-json"))
    adapter = ComfyUIImageAdapter(ComfyUIConfig(workflow_path=workflow))
    monkeypatch.setattr(adapter, "_http", lambda request, timeout: next(bodies))
    with pytest.raises(ImageAdapterError, match="IMG015_HISTORY_INVALID"):
        adapter.generate_image(_request(digest), Event())


def test_cancel_sends_interrupt_for_active_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow, digest = _workflow(tmp_path)
    adapter = ComfyUIImageAdapter(ComfyUIConfig(workflow_path=workflow))
    adapter._prompt_ids["x"] = "pid"
    calls: list[str] = []
    monkeypatch.setattr(
        adapter, "_http", lambda request, timeout: calls.append(request.full_url) or b"{}"
    )
    adapter.cancel("x")
    assert calls == ["http://127.0.0.1:8188/interrupt"]

    cancellation = Event()

    def cancel_after_prompt(request: Request, timeout: float) -> bytes:
        cancellation.set()
        return b'{"prompt_id":"pid"}'

    monkeypatch.setattr(adapter, "_http", cancel_after_prompt)
    with pytest.raises(ImageAdapterError, match="IMG004_CANCELLED"):
        adapter.generate_image(_request(digest), cancellation)


def test_real_api_rejects_empty_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow, digest = _workflow(tmp_path)
    bodies = iter(
        (
            b'{"prompt_id":"pid"}',
            b'{"pid":{"outputs":{"7":{"images":[{"filename":"one.png"}]}}}}',
            b"",
        )
    )
    adapter = ComfyUIImageAdapter(ComfyUIConfig(workflow_path=workflow))
    monkeypatch.setattr(adapter, "_http", lambda request, timeout: next(bodies))
    with pytest.raises(ImageAdapterError, match="IMG009_EMPTY_OUTPUT"):
        adapter.generate_image(_request(digest), Event())
