from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_story.errors import ConfigurationError
from ai_story.provider_config import load_provider_config
from ai_story.providers import stage1_providers


class ProviderConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        load_provider_config.cache_clear()

    def test_default_mode_resolves_all_roles(self) -> None:
        config = load_provider_config()
        self.assertEqual(config["active_mode"], "deterministic")
        self.assertEqual(
            set(config["selected"]),
            {"story", "character_image", "safety", "landscape", "portrait"},
        )

    def test_local_stage1_adapters_are_registered_without_fallback(self) -> None:
        with patch.dict(os.environ, {"AI_STORY_PROVIDER_MODE": "local"}):
            load_provider_config.cache_clear()
            story, image, safety, registry = stage1_providers()
            try:
                self.assertTrue(story.provider_id.startswith("local-story-provider/"))
                self.assertTrue(image.provider_id.startswith("local-diffusion-character/"))
                self.assertTrue(safety.provider_id.startswith("local-safety-provider/"))
                self.assertEqual(registry.config["policy"]["fallback"], "disabled")
            finally:
                registry.close()

    def test_local_stage1_accepts_request_scoped_text_model_overrides(self) -> None:
        overrides = {
            "story": {
                "id": "story-model",
                "model_id": "story-model",
                "path": "C:/models/story.gguf",
                "quantization": "Q4_K_M",
            },
            "safety": {
                "id": "safety-model",
                "model_id": "safety-model",
                "path": "C:/models/safety.gguf",
                "quantization": "Q4_K_M",
            },
        }
        story, image, safety, registry = stage1_providers("text_local", overrides)
        try:
            self.assertTrue(story.provider_id.startswith("local-story-provider/"))
            self.assertTrue(safety.provider_id.startswith("local-safety-provider/"))
            self.assertEqual(registry.config["selected"]["story"], "local_text__story")
            self.assertEqual(registry.config["selected"]["safety"], "local_safety__safety")
        finally:
            registry.close()

    def test_local_stage1_accepts_catalog_safety_override(self) -> None:
        overrides = {
            "safety": {
                "id": "safety-model",
                "model_id": "safety-model",
                "path": "C:/models/safety.gguf",
                "quantization": "Q4_K_M",
            },
        }
        _, _, safety, registry = stage1_providers("local", overrides)
        try:
            self.assertTrue(safety.provider_id.startswith("local-safety-provider/"))
            self.assertEqual(registry.config["selected"]["safety"], "local_safety__safety")
            binding = registry.config["adapters"]["local_safety__safety"]
            self.assertEqual(binding["catalog_id"], "safety-model")
            self.assertEqual(binding["model_file"], "C:/models/safety.gguf")
        finally:
            registry.close()

    def test_depth_controlnet_environment_override_is_auditable_runtime_config(self) -> None:
        with patch.dict(os.environ, {"AI_STORY_DEPTH_CONTROLNET": "off"}):
            load_provider_config.cache_clear()
            config = load_provider_config("local")
        self.assertFalse(config["runtimes"]["diffusers"]["depth_controlnet_enabled"])

    def test_invalid_depth_controlnet_environment_override_is_rejected(self) -> None:
        with patch.dict(os.environ, {"AI_STORY_DEPTH_CONTROLNET": "maybe"}):
            load_provider_config.cache_clear()
            with self.assertRaisesRegex(ConfigurationError, "AI_STORY_DEPTH_CONTROLNET"):
                load_provider_config("local")

    def test_incomplete_custom_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "providers.json"
            path.write_text(json.dumps({"active_mode": "deterministic", "modes": {"deterministic": {}}, "adapters": {}}), encoding="utf-8")
            with patch.dict(os.environ, {"AI_STORY_PROVIDER_CONFIG": str(path)}, clear=False):
                load_provider_config.cache_clear()
                with self.assertRaises(ConfigurationError):
                    load_provider_config()
