from __future__ import annotations

from .errors import ConfigurationError
from .provider_config import configure_job
from .runtime import ProviderRuntimeRegistry


def stage1_providers(
    mode: str | None = None, model_overrides=None, quality_preset=None, runtime_preparer=None
):
    from .stage1.providers import (
        DeterministicCharacterImageProvider,
        DeterministicStoryProvider,
        RuleBasedSafetyProvider,
    )

    config = configure_job(mode, model_overrides, quality_preset)
    selected = config["selected"]
    runtime_registry = None
    story_binding = config["adapters"][selected["story"]]
    image_binding = config["adapters"][selected["character_image"]]
    safety_binding = config["adapters"][selected["safety"]]
    if (
        story_binding.get("runtime") == "llama_cpp"
        or safety_binding.get("runtime") == "llama_cpp"
        or image_binding.get("runtime") == "diffusers"
    ):
        runtime_registry = ProviderRuntimeRegistry(config=config, role_preparer=runtime_preparer)
    if selected["story"] == "deterministic":
        story = DeterministicStoryProvider()
    elif story_binding.get("runtime") == "llama_cpp" and runtime_registry:
        from .stage1.local_providers import LocalStoryProvider

        story = LocalStoryProvider(runtime_registry)
    else:
        raise ConfigurationError(f"Story adapter is not installed: {selected['story']}")
    if selected["character_image"] == "deterministic":
        image = DeterministicCharacterImageProvider()
    elif image_binding.get("runtime") == "diffusers" and runtime_registry:
        from .image_qa import LocalImageQualityAssessor
        from .stage1.local_providers import LocalCharacterImageProvider

        assessor = LocalImageQualityAssessor(config["runtimes"]["diffusers"]["qa"])
        image = LocalCharacterImageProvider(runtime_registry, assessor)
    else:
        raise ConfigurationError(
            f"Character image adapter is not installed: {selected['character_image']}"
        )
    if selected["safety"] == "rule_based":
        safety = RuleBasedSafetyProvider()
    elif safety_binding.get("runtime") == "llama_cpp" and runtime_registry:
        from .stage1.local_providers import LocalSafetyProvider

        safety = LocalSafetyProvider(runtime_registry)
    else:
        raise ConfigurationError(f"Safety adapter is not installed: {selected['safety']}")
    return (
        story,
        image,
        safety,
        runtime_registry,
    )


def landscape_provider(mode: str | None = None, model_overrides=None, quality_preset=None):
    from .stage2.providers import DeterministicLandscapeProvider

    config = configure_job(mode, model_overrides, quality_preset)
    selected = config["selected"]["landscape"]
    if selected == "deterministic":
        return DeterministicLandscapeProvider(), None
    if config["adapters"][selected].get("runtime") == "diffusers":
        from .image_qa import LocalImageQualityAssessor
        from .stage2.providers import LocalLandscapeProvider

        registry = ProviderRuntimeRegistry(config=config)
        assessor = LocalImageQualityAssessor(config["runtimes"]["diffusers"]["qa"])
        return LocalLandscapeProvider(registry, assessor), registry
    raise ConfigurationError(f"Landscape adapter is not installed: {selected}")


def portrait_provider(mode: str | None = None, model_overrides=None, quality_preset=None):
    from .stage3.providers import DeterministicPortraitProvider

    config = configure_job(mode, model_overrides, quality_preset)
    selected = config["selected"]["portrait"]
    if selected == "deterministic":
        return DeterministicPortraitProvider(), None
    if config["adapters"][selected].get("runtime") == "diffusers":
        from .image_qa import LocalImageQualityAssessor
        from .stage3.providers import LocalPortraitProvider

        registry = ProviderRuntimeRegistry(config=config)
        assessor = LocalImageQualityAssessor(config["runtimes"]["diffusers"]["qa"])
        return LocalPortraitProvider(registry, assessor), registry
    raise ConfigurationError(f"Portrait adapter is not installed: {selected}")
