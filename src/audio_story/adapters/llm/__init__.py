"""Local-only LLM adapter API."""

from audio_story.adapters.llm.base import LLMAdapterError, LocalLLMAdapter
from audio_story.adapters.llm.llama_cpp import LlamaCppAdapter, LlamaCppConfig
from audio_story.adapters.llm.mock import DeterministicMockAdapter
from audio_story.adapters.llm.models import GenerationRequest, GenerationResponse, PromptCapsule
from audio_story.adapters.llm.service import AdapterPolicy, StructuredGenerationService

__all__ = [
    "AdapterPolicy",
    "DeterministicMockAdapter",
    "GenerationRequest",
    "GenerationResponse",
    "LLMAdapterError",
    "LlamaCppAdapter",
    "LlamaCppConfig",
    "LocalLLMAdapter",
    "PromptCapsule",
    "StructuredGenerationService",
]
