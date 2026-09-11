from __future__ import annotations

import os

import pytest

from audio_story.adapters.llm import LlamaCppAdapter, LlamaCppConfig


@pytest.mark.local_llm
def test_explicit_local_llama_cpp_health_smoke() -> None:
    endpoint = os.environ.get("AUDIO_STORY_LLAMA_CPP_SMOKE_URL")
    if not endpoint:
        pytest.skip("set AUDIO_STORY_LLAMA_CPP_SMOKE_URL to run the explicit local smoke test")
    assert LlamaCppAdapter(LlamaCppConfig(endpoint=endpoint)).health()["status"]
