from __future__ import annotations

import copy
import unittest

from ai_story.cli import parser
from ai_story.errors import ConfigurationError
from ai_story.image_models import ImageModelProfile, resolve_image_model_profile
from ai_story.model_cache import _image_model_targets
from ai_story.provider_config import configure_job, load_provider_config
from ai_story.runtime import (
    GenerationRequest,
    HealthReport,
    ProviderRuntimeRegistry,
    RuntimeCapabilities,
)
from ai_story.runtime.diffusers_runtime import DiffusersRuntime


class FakeImageRuntime:
    runtime_id = "diffusers"

    def __init__(self, capabilities):
        self._capabilities = capabilities
        self.calls = []

    def health(self):
        return HealthReport("PASS", self.runtime_id)

    def capabilities(self):
        return self._capabilities

    def generate_image(self, request, cancellation=None):
        self.calls.append(request)
        return b"image"

    def unload(self):
        pass


class ImageModelProfileTests(unittest.TestCase):
    def test_prepare_models_targets_selected_family(self):
        args = parser().parse_args(["prepare-image-models", "--mode", "local_sd35"])
        self.assertEqual(args.mode, "local_sd35")

    def test_local_modes_only_use_sd35_profile(self):
        local = load_provider_config("local")
        sd35 = load_provider_config("local_sd35")
        local_profile = resolve_image_model_profile(
            local, local["adapters"][local["selected"]["landscape"]]
        )
        sd35_profile = resolve_image_model_profile(
            sd35, sd35["adapters"][sd35["selected"]["landscape"]]
        )
        self.assertEqual(local_profile, sd35_profile)
        self.assertEqual(sd35_profile.family, "sd3")
        self.assertFalse(sd35_profile.capabilities.reference_images)
        self.assertEqual(sd35_profile.scheduler, "FlowMatchEulerDiscreteScheduler")
        self.assertEqual(sd35_profile.parameters["guidance_scale"], 4.5)

    def test_prepare_models_excludes_unsupported_sdxl_dependencies(self):
        targets = _image_model_targets(load_provider_config("local"))
        self.assertFalse(any(name.startswith("controlnet:sdxl") for name in targets))
        self.assertNotIn("ip_adapter", targets)
        self.assertNotIn("control_preprocessor:depth", targets)
        self.assertNotIn("control_preprocessor:canny", targets)

    def test_profile_rejects_unknown_family_and_bad_work_size(self):
        with self.assertRaisesRegex(ConfigurationError, "family"):
            ImageModelProfile.from_config("bad", {"family": "flux", "model_id": "x"})
        with self.assertRaisesRegex(ConfigurationError, "work size"):
            ImageModelProfile.from_config(
                "bad", {
                    "family": "sd3", "model_id": "x",
                    "work_sizes": {"landscape": [1000, 576]},
                }
            )
        with self.assertRaisesRegex(ConfigurationError, "requires model mappings"):
            ImageModelProfile.from_config(
                "bad-controlnet", {
                    "family": "sd3", "model_id": "x",
                    "capabilities": {"controlnet": True},
                },
            )

    def test_quality_preset_is_request_scoped_for_both_image_adapters(self):
        base = load_provider_config("local_sd35")
        configured = configure_job("local_sd35", None, "quality")
        self.assertEqual(configured["adapters"]["local_sd35"]["parameters"]["steps"], 40)
        self.assertEqual(base["adapters"]["local_sd35"]["parameters"]["steps"], 28)

    def test_catalog_override_keeps_sd35_defaults_without_mutating_base(self):
        base = load_provider_config("local")
        configured = configure_job(
            "local",
            {
                "landscape": {
                    "id": "sd35",
                    "model_id": "stabilityai/stable-diffusion-3.5-medium",
                    "model_profile": "sd35_medium",
                }
            },
        )
        binding = configured["adapters"][configured["selected"]["landscape"]]
        self.assertEqual(resolve_image_model_profile(configured, binding).family, "sd3")
        self.assertEqual(binding["parameters"]["guidance_scale"], 4.5)
        character_binding = configured["adapters"][configured["selected"]["character_image"]]
        self.assertEqual(resolve_image_model_profile(configured, character_binding).family, "sd3")
        self.assertEqual(
            base["adapters"]["local_sd35"]["parameters"]["guidance_scale"], 4.5
        )

    def test_registry_rejects_unsupported_reference_request_before_runtime(self):
        runtime = FakeImageRuntime(RuntimeCapabilities(
            image=True, image_text_to_image=True, image_to_image=True,
            image_reference=False,
        ))
        registry = ProviderRuntimeRegistry(
            "local_sd35", runtime_overrides={"diffusers": runtime}
        )
        try:
            with self.assertRaisesRegex(ConfigurationError, "reference images"):
                registry.generate_image(
                    "landscape",
                    GenerationRequest("scene", parameters={"reference_images": [b"ref"]}),
                )
            self.assertEqual(runtime.calls, [])
        finally:
            registry.close()

    def test_registry_rejects_unsupported_controlnet_before_runtime(self):
        runtime = FakeImageRuntime(RuntimeCapabilities(
            image=True, image_text_to_image=True, image_controlnet=False,
        ))
        registry = ProviderRuntimeRegistry(
            "local", runtime_overrides={"diffusers": runtime}
        )
        try:
            with self.assertRaisesRegex(ConfigurationError, "ControlNet"):
                registry.generate_image(
                    "landscape",
                    GenerationRequest("scene", parameters={
                        "control_inputs": [{"control_type": "depth", "data": b"map"}],
                    }),
                )
            self.assertEqual(runtime.calls, [])
        finally:
            registry.close()

    def test_registry_reuses_runtime_for_the_single_supported_image_profile(self):
        config = copy.deepcopy(load_provider_config("local"))
        config["selected"]["portrait"] = "local_sd35"
        registry = ProviderRuntimeRegistry(config=config)
        try:
            self.assertIs(
                registry.runtime_for("landscape"), registry.runtime_for("portrait")
            )
            self.assertEqual(registry.image_settings("landscape")["model_family"], "sd3")
            self.assertEqual(registry.image_settings("portrait")["model_family"], "sd3")
        finally:
            registry.close()

    def test_diffusers_rejects_unknown_family_parameter_before_loading_model(self):
        runtime = DiffusersRuntime({"model_id": "unused", "model_family": "sd3"})
        with self.assertRaisesRegex(Exception, "Unsupported image parameters"):
            runtime.generate_image(
                GenerationRequest("scene", parameters={"unsupported_knob": 1})
            )

    def test_diffusers_prompt_budget_rejects_truncation(self):
        class Tokenizer:
            model_max_length = 5

            def __call__(self, prompt, **kwargs):
                return {"input_ids": list(range(len(prompt.split()) + 2))}

        pipeline = type("Pipeline", (), {"tokenizer": Tokenizer()})()
        with self.assertRaisesRegex(Exception, "token budget exceeded"):
            DiffusersRuntime._validate_prompt_budget(
                pipeline, "one two three four", label="prompt"
            )

    def test_diffusers_prompt_budget_accepts_exact_limit(self):
        class Tokenizer:
            model_max_length = 6

            def __call__(self, prompt, **kwargs):
                return {"input_ids": list(range(len(prompt.split()) + 2))}

        pipeline = type("Pipeline", (), {"tokenizer": Tokenizer()})()
        DiffusersRuntime._validate_prompt_budget(
            pipeline, "one two three four", label="prompt"
        )

    def test_diffusers_explicit_prompt_fitting_keeps_longest_valid_prefix(self):
        class Tokenizer:
            model_max_length = 6

            def __call__(self, prompt, **kwargs):
                return {"input_ids": list(range(len(prompt.split()) + 2))}

        pipeline = type("Pipeline", (), {"tokenizer": Tokenizer()})()
        fitted = DiffusersRuntime._fit_prompt_to_budget(
            pipeline, "one two three four five six", label="prompt"
        )
        self.assertEqual(fitted, "one two three four")
        DiffusersRuntime._validate_prompt_budget(pipeline, fitted, label="prompt")

    def test_sd3_reference_conditioning_report_blocks_unconfigured_adapter(self):
        runtime = DiffusersRuntime({
            "model_id": "sd35-medium",
            "model_family": "sd3",
            "model_capabilities": {"reference_images": False},
            "ip_adapter": {},
        })
        report = runtime.reference_conditioning_report()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["blockers"], [
            "REFERENCE_CAPABILITY_NOT_DECLARED",
            "IP_ADAPTER_NOT_CONFIGURED",
            "SD3_IMAGE_ENCODER_NOT_CONFIGURED",
            "SD3_ADAPTER_BASE_COMPATIBILITY_NOT_PROVEN",
        ])

    def test_sd3_reference_conditioning_report_accepts_explicit_compatible_stack(self):
        runtime = DiffusersRuntime({
            "model_id": "sd35-medium",
            "model_family": "sd3",
            "model_capabilities": {"reference_images": True},
            "ip_adapter": {
                "model": "adapter-for-medium",
                "image_encoder": "siglip-vision",
                "compatible_base_model": "sd35-medium",
            },
        })
        self.assertEqual(runtime.reference_conditioning_report()["status"], "PASS")
