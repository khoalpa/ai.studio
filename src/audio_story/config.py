"""Safe offline defaults for the target workstation."""

from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Configuration violates an offline runtime invariant."""

    code = "LLM001_NON_LOOPBACK_ENDPOINT"


def require_loopback_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise ConfigurationError("local LLM endpoint must use HTTP on a loopback host")
    return endpoint.rstrip("/")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    host: str = "127.0.0.1"
    max_parallel_gpu_jobs: int = 1
    llama_cpp_url: str = "http://127.0.0.1:8080"
    comfyui_url: str = "http://127.0.0.1:8188"
    llm_context_chars: int = 131_072
    llm_max_output_tokens: int = 8_192
    llm_timeout_seconds: float = 120.0
    llm_max_attempts: int = 2


DEFAULT_CONFIG = RuntimeConfig()
