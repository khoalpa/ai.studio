"""Safe offline defaults for the target workstation."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    host: str = "127.0.0.1"
    max_parallel_gpu_jobs: int = 1
    llama_cpp_url: str = "http://127.0.0.1:8080"
    comfyui_url: str = "http://127.0.0.1:8188"


DEFAULT_CONFIG = RuntimeConfig()
