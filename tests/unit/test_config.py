from audio_story.config import DEFAULT_CONFIG


def test_gpu_work_is_serialized_by_default() -> None:
    assert DEFAULT_CONFIG.max_parallel_gpu_jobs == 1
    assert DEFAULT_CONFIG.host == "127.0.0.1"
    assert DEFAULT_CONFIG.llama_cpp_url.startswith("http://127.0.0.1:")
    assert DEFAULT_CONFIG.comfyui_url.startswith("http://127.0.0.1:")
