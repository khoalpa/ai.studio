from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import ConfigurationError


@dataclass(frozen=True)
class ImageModelCapabilities:
    text_to_image: bool = True
    image_to_image: bool = False
    reference_images: bool = False
    inpainting: bool = False
    outpainting: bool = False
    controlnet: bool = False
    negative_prompt: bool = True


@dataclass(frozen=True)
class ImageModelProfile:
    profile_id: str
    family: str
    model_id: str
    dtype: str = "float16"
    variant: str | None = None
    loader: str = "AutoPipelineForText2Image"
    image_loader: str = "AutoPipelineForImage2Image"
    inpaint_loader: str = "AutoPipelineForInpainting"
    scheduler: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    work_sizes: dict[str, tuple[int, int]] = field(default_factory=dict)
    controlnets: dict[str, str] = field(default_factory=dict)
    capabilities: ImageModelCapabilities = field(default_factory=ImageModelCapabilities)

    @classmethod
    def from_config(
        cls, profile_id: str, value: dict[str, Any], *, model_id: str | None = None
    ) -> ImageModelProfile:
        if not isinstance(value, dict):
            raise ConfigurationError(f"Image model profile is invalid: {profile_id}")
        family = str(value.get("family", "")).strip()
        resolved_model = str(model_id or value.get("model_id") or "").strip()
        if family != "sd3":
            raise ConfigurationError(f"Unsupported image model family: {family or '<empty>'}")
        if not resolved_model:
            raise ConfigurationError(f"Image model profile has no model_id: {profile_id}")
        raw_capabilities = value.get("capabilities", {})
        capability_fields = ImageModelCapabilities.__dataclass_fields__
        unknown = set(raw_capabilities) - set(capability_fields)
        if unknown:
            raise ConfigurationError(
                f"Unknown image model capabilities for {profile_id}: {sorted(unknown)}"
            )
        work_sizes = {}
        for role, raw_size in value.get("work_sizes", {}).items():
            if (
                role not in {"character_image", "landscape", "portrait"}
                or not isinstance(raw_size, list)
                or len(raw_size) != 2
                or any(not isinstance(item, int) or item <= 0 or item % 64 for item in raw_size)
            ):
                raise ConfigurationError(
                    f"Invalid image work size for {profile_id}.{role}"
                )
            work_sizes[role] = (raw_size[0], raw_size[1])
        controlnets = dict(value.get("controlnets", {}))
        invalid_controlnets = set(controlnets) - {"depth", "openpose", "canny", "segmentation"}
        if invalid_controlnets or any(not isinstance(model, str) or not model.strip() for model in controlnets.values()):
            raise ConfigurationError(f"Invalid ControlNet mapping for {profile_id}")
        if raw_capabilities.get("controlnet") and not controlnets:
            raise ConfigurationError(f"ControlNet capability requires model mappings: {profile_id}")
        return cls(
            profile_id=profile_id,
            family=family,
            model_id=resolved_model,
            dtype=str(value.get("dtype", "float16")),
            variant=value.get("variant"),
            loader=str(value.get("loader", "AutoPipelineForText2Image")),
            image_loader=str(value.get("image_loader", "AutoPipelineForImage2Image")),
            inpaint_loader=str(value.get("inpaint_loader", "AutoPipelineForInpainting")),
            scheduler=value.get("scheduler"),
            parameters=dict(value.get("parameters", {})),
            work_sizes=work_sizes,
            controlnets=controlnets,
            capabilities=ImageModelCapabilities(**raw_capabilities),
        )

    def settings(self, runtime: dict[str, Any]) -> dict[str, Any]:
        result = dict(runtime)
        result.update({
            "model_profile": self.profile_id,
            "model_family": self.family,
            "model_id": self.model_id,
            "dtype": self.dtype,
            "variant": self.variant,
            "loader": self.loader,
            "image_loader": self.image_loader,
            "inpaint_loader": self.inpaint_loader,
            "scheduler": self.scheduler,
            "model_parameters": dict(self.parameters),
            "model_capabilities": {
                name: getattr(self.capabilities, name)
                for name in ImageModelCapabilities.__dataclass_fields__
            },
            "controlnets": dict(self.controlnets),
        })
        legacy_names = {
            "character_image": "character_work_size",
            "landscape": "landscape_work_size",
            "portrait": "portrait_work_size",
        }
        for role, size in self.work_sizes.items():
            result[legacy_names[role]] = list(size)
        if not self.capabilities.reference_images:
            result["ip_adapter"] = {}
        return result


def resolve_image_model_profile(
    config: dict[str, Any], binding: dict[str, Any]
) -> ImageModelProfile:
    profiles = config.get("image_models", {})
    profile_id = str(binding.get("model_profile") or "").strip()
    if not profile_id:
        model_id = binding.get("model_id")
        matches = [
            name for name, value in profiles.items() if value.get("model_id") == model_id
        ]
        if len(matches) != 1:
            raise ConfigurationError(
                f"Image adapter requires an unambiguous model_profile: {model_id}"
            )
        profile_id = matches[0]
    if profile_id not in profiles:
        raise ConfigurationError(f"Unknown image model profile: {profile_id}")
    return ImageModelProfile.from_config(
        profile_id, profiles[profile_id], model_id=binding.get("model_id")
    )

