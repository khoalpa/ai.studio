from __future__ import annotations

import io
from typing import Any

from ..errors import RuntimeCapabilityError, RuntimeUnavailableError
from ..model_cache import cached_model_path
from .base import (
    CancellationToken,
    GenerationRequest,
    GenerationResult,
    HealthReport,
    RuntimeCapabilities,
)


class DiffusersRuntime:
    """Lazy local Diffusers runtime optimized for a single 16 GB accelerator."""

    runtime_id = "diffusers"

    def __init__(self, settings: dict[str, Any], runtime_id: str | None = None) -> None:
        self.settings = settings
        self.runtime_id = runtime_id or self.runtime_id
        self.model_id = settings.get("model_id")
        self.model_family = settings.get("model_family", "sd3")
        self.device = settings.get("device", "cuda")
        self._text_pipeline = None
        self._image_pipeline = None
        self._inpaint_pipeline = None
        self._control_pipelines: dict[str, Any] = {}
        self._ip_adapter_loaded = False
        self._upscaler_pipeline = None
        self.last_image_metadata: dict[str, Any] = {}

    def health(self) -> HealthReport:
        try:
            import diffusers  # noqa: F401
            import torch
            from PIL import Image  # noqa: F401
        except ImportError as exc:
            return HealthReport("NOT_INSTALLED", self.runtime_id, str(exc))
        if not self.model_id:
            return HealthReport("NOT_CONFIGURED", self.runtime_id, "model_id is required")
        if self.device == "cuda" and not torch.cuda.is_available():
            return HealthReport("UNAVAILABLE", self.runtime_id, "CUDA is not available")
        cached = cached_model_path(self.model_id)
        if not cached:
            status = "UNAVAILABLE" if self.settings.get("local_files_only", False) else "DOWNLOAD_REQUIRED"
            return HealthReport(status, self.runtime_id, "Diffusion weights are not cached", self.model_id)
        return HealthReport("PASS", self.runtime_id, "Dependencies and accelerator are available", self.model_id)

    def capabilities(self) -> RuntimeCapabilities:
        value = self.settings.get("model_capabilities", {})
        return RuntimeCapabilities(
            image=True,
            cancellation=True,
            model_unload=True,
            image_text_to_image=bool(value.get("text_to_image", True)),
            image_to_image=bool(value.get("image_to_image", True)),
            image_reference=bool(value.get("reference_images", True)),
            image_inpainting=bool(value.get("inpainting", False)),
            image_outpainting=bool(value.get("outpainting", False)),
            image_controlnet=bool(value.get("controlnet", False)),
        )

    def reference_conditioning_report(self) -> dict[str, Any]:
        """Describe whether reference images can reach inference without loading weights."""
        capabilities = self.settings.get("model_capabilities", {})
        adapter = self.settings.get("ip_adapter") or {}
        declared = bool(capabilities.get("reference_images", False))
        adapter_model = str(adapter.get("model") or "").strip()
        image_encoder = str(adapter.get("image_encoder") or "").strip()
        compatible_base = str(adapter.get("compatible_base_model") or "").strip()
        blockers = []
        if not declared:
            blockers.append("REFERENCE_CAPABILITY_NOT_DECLARED")
        if not adapter_model:
            blockers.append("IP_ADAPTER_NOT_CONFIGURED")
        if self.model_family == "sd3" and not image_encoder:
            blockers.append("SD3_IMAGE_ENCODER_NOT_CONFIGURED")
        if self.model_family == "sd3" and compatible_base != str(self.model_id or ""):
            blockers.append("SD3_ADAPTER_BASE_COMPATIBILITY_NOT_PROVEN")
        return {
            "status": "PASS" if not blockers else "BLOCKED",
            "runtime_id": self.runtime_id,
            "model_family": self.model_family,
            "model_id": self.model_id,
            "reference_capability_declared": declared,
            "ip_adapter_model": adapter_model or None,
            "image_encoder_model": image_encoder or None,
            "compatible_base_model": compatible_base or None,
            "blockers": blockers,
        }

    def generate_text(self, request, cancellation=None) -> GenerationResult:
        raise RuntimeCapabilityError("diffusers runtime does not generate text")

    def generate_json(self, request, cancellation=None) -> dict[str, Any]:
        raise RuntimeCapabilityError("diffusers runtime does not generate JSON")

    def generate_image(
        self, request: GenerationRequest, cancellation: CancellationToken | None = None
    ) -> bytes:
        if cancellation:
            cancellation.raise_if_cancelled()
        parameters = dict(request.parameters)
        supported = {
            "init_image", "outpaint_image", "outpaint_mask", "output_width", "output_height", "width", "height", "seed",
            "negative_prompt", "reference_images", "reference_inputs", "control_inputs",
            "steps", "guidance_scale", "strength", "fit_prompt_to_token_budget",
        }
        unknown = sorted(set(parameters) - supported)
        if unknown:
            raise RuntimeCapabilityError(
                f"Unsupported image parameters for {self.model_family}: {unknown}"
            )
        init_image = parameters.pop("init_image", None)
        outpaint_image = parameters.pop("outpaint_image", None)
        outpaint_mask = parameters.pop("outpaint_mask", None)
        if (outpaint_image is None) != (outpaint_mask is None):
            raise RuntimeCapabilityError("Outpainting requires both image and mask")
        output_width = int(parameters.pop("output_width"))
        output_height = int(parameters.pop("output_height"))
        width = int(parameters.pop("width"))
        height = int(parameters.pop("height"))
        seed = int(parameters.pop("seed"))
        negative_prompt = parameters.pop("negative_prompt", None)
        fit_prompt_to_token_budget = bool(parameters.pop("fit_prompt_to_token_budget", False))
        reference_images = parameters.pop("reference_images", [])
        reference_inputs = parameters.pop("reference_inputs", [])
        control_inputs = parameters.pop("control_inputs", [])
        if len(control_inputs) > 1:
            raise RuntimeCapabilityError("One ControlNet input per generation is currently supported")
        if reference_inputs:
            reference_images = [item["data"] for item in reference_inputs]
        pipeline = (
            self._load_control_pipeline(control_inputs[0]["control_type"])
            if control_inputs else self._load_inpaint_pipeline() if outpaint_image
            else self._load_image_pipeline() if init_image else self._load_text_pipeline()
        )
        prompt = request.prompt
        if fit_prompt_to_token_budget:
            prompt = self._fit_prompt_to_budget(pipeline, prompt, label="prompt")
        else:
            self._validate_prompt_budget(pipeline, prompt, label="prompt")
        if negative_prompt:
            if fit_prompt_to_token_budget:
                negative_prompt = self._fit_prompt_to_budget(
                    pipeline, negative_prompt, label="negative_prompt"
                )
            else:
                self._validate_prompt_budget(pipeline, negative_prompt, label="negative_prompt")
        import torch
        from PIL import Image

        generator_device = self.device if self.device == "cuda" else "cpu"
        generator = torch.Generator(device=generator_device).manual_seed(seed)
        defaults = self.settings.get("model_parameters", {})
        call: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "generator": generator,
            "num_inference_steps": int(parameters.pop("steps", defaults.get("steps", 28))),
            "guidance_scale": float(parameters.pop("guidance_scale", defaults.get("guidance_scale", 6.5))),
        }
        if not self.settings.get("model_capabilities", {}).get("negative_prompt", True):
            call.pop("negative_prompt", None)
        if init_image:
            image = Image.open(io.BytesIO(init_image)).convert("RGB")
            if height > width:
                image = self._portrait_crop(image)
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            call["image"] = image
            call["strength"] = float(parameters.pop("strength", 0.38))
        elif outpaint_image:
            call["image"] = Image.open(io.BytesIO(outpaint_image)).convert("RGB").resize(
                (width, height), Image.Resampling.LANCZOS
            )
            call["mask_image"] = Image.open(io.BytesIO(outpaint_mask)).convert("L").resize(
                (width, height), Image.Resampling.LANCZOS
            )
            call["strength"] = float(parameters.pop("strength", 0.92))
        elif control_inputs:
            control = control_inputs[0]
            call["image"] = Image.open(io.BytesIO(control["data"])).convert("RGB").resize(
                (width, height), Image.Resampling.LANCZOS
            )
            call["controlnet_conditioning_scale"] = float(control.get("scale", 0.75))
        used_ip_adapter = False
        if not init_image and reference_images and self._load_ip_adapter(pipeline):
            used_ip_adapter = True
            images = [Image.open(io.BytesIO(data)).convert("RGB") for data in reference_images]
            if len(images) == 1:
                call["ip_adapter_image"] = images[0]
            else:
                call["ip_adapter_image"] = self._reference_canvas(images)
        try:
            result = pipeline(**call)
            image = result.images[0].convert("RGB")
        except Exception as exc:
            raise RuntimeUnavailableError(f"Diffusers generation failed: {exc}") from exc
        finally:
            # A pipeline with IP-Adapter loaded requires image embeddings on
            # every invocation.  Remove it after a reference-conditioned call
            # so ordinary text-only frames can use the same cached pipeline.
            if used_ip_adapter and hasattr(pipeline, "unload_ip_adapter"):
                pipeline.unload_ip_adapter()
                self._ip_adapter_loaded = False
        if cancellation:
            cancellation.raise_if_cancelled()
        image = self._upscale_and_finish(
            image,
            (output_width, output_height),
            prompt=prompt,
            negative_prompt=negative_prompt,
            generator=generator,
        )
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    @staticmethod
    def _validate_prompt_budget(pipeline, prompt: str, *, label: str) -> None:
        """Reject prompt truncation before diffusion inference starts."""
        checked = []
        for name in ("tokenizer", "tokenizer_2", "tokenizer_3"):
            tokenizer = getattr(pipeline, name, None)
            limit = int(getattr(tokenizer, "model_max_length", 0) or 0)
            if tokenizer is None or limit <= 0 or limit >= 1_000_000:
                continue
            encoded = tokenizer(prompt, add_special_tokens=True, truncation=False)
            token_ids = encoded["input_ids"]
            if token_ids and isinstance(token_ids[0], list):
                token_ids = token_ids[0]
            count = len(token_ids)
            checked.append((name, count, limit))
            if count > limit:
                raise RuntimeCapabilityError(
                    f"Diffusion {label} token budget exceeded for {name}: "
                    f"{count} tokens exceeds {limit}"
                )

    @classmethod
    def _fit_prompt_to_budget(cls, pipeline, prompt: str, *, label: str) -> str:
        """Keep the longest whole-word prefix accepted by every pipeline tokenizer."""
        try:
            cls._validate_prompt_budget(pipeline, prompt, label=label)
            return prompt
        except RuntimeCapabilityError:
            pass

        words = prompt.split()
        low, high = 1, len(words) - 1
        best = ""
        while low <= high:
            middle = (low + high) // 2
            candidate = " ".join(words[:middle])
            try:
                cls._validate_prompt_budget(pipeline, candidate, label=label)
            except RuntimeCapabilityError:
                high = middle - 1
            else:
                best = candidate
                low = middle + 1
        if not best:
            raise RuntimeCapabilityError(
                f"Diffusion {label} cannot fit even one word in the tokenizer budget"
            )
        return best

    def assess_image(self, image, request, cancellation=None) -> GenerationResult:
        raise RuntimeCapabilityError("Image assessment is provided by the QA adapter")

    def unload(self) -> None:
        self._text_pipeline = None
        self._image_pipeline = None
        self._inpaint_pipeline = None
        self._control_pipelines = {}
        self._ip_adapter_loaded = False
        self._upscaler_pipeline = None
        self.last_image_metadata = {}
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _load_text_pipeline(self):
        if self._text_pipeline is not None:
            return self._text_pipeline
        health = self.health()
        if health.status not in {"PASS", "DOWNLOAD_REQUIRED"}:
            raise RuntimeUnavailableError(health.detail or "Diffusers runtime is unavailable")
        import diffusers
        import torch

        dtype = torch.float16 if self.settings.get("dtype", "float16") == "float16" else torch.float32
        try:
            load_options = {
                "torch_dtype": dtype,
                "local_files_only": bool(self.settings.get("local_files_only", False)),
                "use_safetensors": True,
            }
            if self.settings.get("variant"):
                load_options["variant"] = self.settings["variant"]
            loader_name = self.settings.get("loader", "AutoPipelineForText2Image")
            loader = getattr(diffusers, loader_name, None)
            if loader is None:
                raise RuntimeUnavailableError(
                    f"Diffusers loader is unavailable for {self.model_family}: {loader_name}"
                )
            pipeline = loader.from_pretrained(
                self.model_id,
                **load_options,
            )
            scheduler_name = self.settings.get("scheduler")
            if scheduler_name:
                scheduler_type = getattr(diffusers, scheduler_name, None)
                if scheduler_type is None:
                    raise RuntimeUnavailableError(
                        f"Diffusers scheduler is unavailable for {self.model_family}: {scheduler_name}"
                    )
                pipeline.scheduler = scheduler_type.from_config(pipeline.scheduler.config)
            self._optimize(pipeline)
        except Exception as exc:
            raise RuntimeUnavailableError(f"Cannot load diffusion model: {exc}") from exc
        self._text_pipeline = pipeline
        return pipeline

    def _load_image_pipeline(self):
        if self._image_pipeline is not None:
            return self._image_pipeline
        import diffusers

        try:
            loader_name = self.settings.get("image_loader", "AutoPipelineForImage2Image")
            loader = getattr(diffusers, loader_name, None)
            if loader is None:
                raise RuntimeUnavailableError(
                    f"Diffusers image loader is unavailable for {self.model_family}: {loader_name}"
                )
            self._image_pipeline = loader.from_pipe(self._load_text_pipeline())
        except Exception as exc:
            raise RuntimeUnavailableError(f"Cannot create image-to-image pipeline: {exc}") from exc
        return self._image_pipeline

    def _load_inpaint_pipeline(self):
        if self._inpaint_pipeline is not None:
            return self._inpaint_pipeline
        import diffusers

        try:
            loader_name = self.settings.get("inpaint_loader", "AutoPipelineForInpainting")
            loader = getattr(diffusers, loader_name, None)
            if loader is None:
                raise RuntimeUnavailableError(f"Diffusers inpaint loader is unavailable: {loader_name}")
            self._inpaint_pipeline = loader.from_pipe(self._load_text_pipeline())
            self._optimize(self._inpaint_pipeline)
        except Exception as exc:
            raise RuntimeUnavailableError(f"Cannot create outpainting pipeline: {exc}") from exc
        return self._inpaint_pipeline

    def _load_control_pipeline(self, control_type: str):
        if control_type in self._control_pipelines:
            return self._control_pipelines[control_type]
        model_id = (self.settings.get("controlnets") or {}).get(control_type)
        if not model_id:
            raise RuntimeCapabilityError(f"ControlNet type is not configured: {control_type}")
        if self.model_family != "sdxl":
            raise RuntimeCapabilityError("ControlNet is not supported by the configured image profile")
        import diffusers
        import torch

        dtype = torch.float16 if self.settings.get("dtype", "float16") == "float16" else torch.float32
        try:
            controlnet = diffusers.ControlNetModel.from_pretrained(
                model_id,
                torch_dtype=dtype,
                local_files_only=bool(self.settings.get("local_files_only", False)),
                use_safetensors=True,
            )
            pipeline = diffusers.StableDiffusionXLControlNetPipeline.from_pipe(
                self._load_text_pipeline(), controlnet=controlnet
            )
            self._optimize(pipeline)
        except Exception as exc:
            raise RuntimeUnavailableError(f"Cannot load {control_type} ControlNet: {exc}") from exc
        self._control_pipelines[control_type] = pipeline
        return pipeline

    def _load_upscaler(self):
        if self._upscaler_pipeline is not None:
            return self._upscaler_pipeline
        settings = self.settings.get("upscaler") or {}
        model_id = settings.get("model")
        if not model_id:
            raise RuntimeUnavailableError("Learned upscaler model is not configured")
        import diffusers
        import torch

        dtype = torch.float16 if self.settings.get("dtype", "float16") == "float16" else torch.float32
        try:
            pipeline = diffusers.StableDiffusionLatentUpscalePipeline.from_pretrained(
                model_id,
                torch_dtype=dtype,
                local_files_only=bool(self.settings.get("local_files_only", False)),
            )
            self._optimize(pipeline)
        except Exception as exc:
            raise RuntimeUnavailableError(f"Cannot load learned upscaler: {exc}") from exc
        self._upscaler_pipeline = pipeline
        return pipeline

    def _upscale_and_finish(
        self, image, target_size: tuple[int, int], *, prompt: str,
        negative_prompt: str | None, generator,
    ):
        from PIL import Image, ImageEnhance, ImageFilter

        source_size = image.size
        settings = self.settings.get("upscaler") or {}
        needs_upscale = target_size[0] > image.width or target_size[1] > image.height
        learned = bool(settings.get("enabled", False) and needs_upscale)
        learned_size = None
        if learned:
            pipeline = self._load_upscaler()
            try:
                result = pipeline(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    image=image,
                    num_inference_steps=int(settings.get("steps", 20)),
                    guidance_scale=float(settings.get("guidance_scale", 1.0)),
                    generator=generator,
                )
                image = result.images[0].convert("RGB")
                learned_size = image.size
            except Exception as exc:
                raise RuntimeUnavailableError(f"Learned upscale failed: {exc}") from exc
        if image.size != target_size:
            image = image.resize(target_size, Image.Resampling.LANCZOS)
        image = image.filter(ImageFilter.UnsharpMask(
            radius=float(settings.get("sharpen_radius", 1.1)),
            percent=int(settings.get("sharpen_percent", 115)),
            threshold=int(settings.get("sharpen_threshold", 3)),
        ))
        image = ImageEnhance.Contrast(image).enhance(float(settings.get("contrast", 1.02)))
        image = ImageEnhance.Color(image).enhance(float(settings.get("color", 1.01)))
        self.last_image_metadata = {
            "schema_version": "1.0",
            "mode": "LATENT_X2_PLUS_RESIDUAL" if learned else "LANCZOS_FALLBACK",
            "model_id": settings.get("model") if learned else None,
            "source_size": list(source_size),
            "learned_size": list(learned_size) if learned_size else None,
            "output_size": list(target_size),
            "residual_resize": bool(learned_size and learned_size != target_size),
            "postprocess": {
                "sharpen_radius": float(settings.get("sharpen_radius", 1.1)),
                "sharpen_percent": int(settings.get("sharpen_percent", 115)),
                "sharpen_threshold": int(settings.get("sharpen_threshold", 3)),
                "contrast": float(settings.get("contrast", 1.02)),
                "color": float(settings.get("color", 1.01)),
            },
        }
        return image

    def _optimize(self, pipeline) -> None:
        if hasattr(pipeline, "enable_vae_slicing"):
            pipeline.enable_vae_slicing()
        if hasattr(pipeline, "enable_vae_tiling"):
            pipeline.enable_vae_tiling()
        if self.settings.get("model_cpu_offload", True):
            try:
                pipeline.enable_model_cpu_offload()
                return
            except Exception:
                pass
        pipeline.to(self.device)

    def _load_ip_adapter(self, pipeline) -> bool:
        adapter = self.settings.get("ip_adapter") or {}
        if not adapter.get("model"):
            return False
        if self.model_family == "sd3" and not adapter.get("image_encoder"):
            raise RuntimeCapabilityError(
                "SD3 IP-Adapter requires an explicitly configured image encoder"
            )
        if self._ip_adapter_loaded:
            return True
        try:
            pipeline.load_ip_adapter(
                adapter["model"],
                subfolder=adapter.get("subfolder"),
                weight_name=adapter.get("weight_name"),
                local_files_only=bool(self.settings.get("local_files_only", False)),
            )
            pipeline.set_ip_adapter_scale(float(adapter.get("scale", 0.65)))
            # The base pipeline may already have CPU-offload hooks. Reapply
            # them so the newly attached image encoder follows the same
            # execution device policy as the UNet and text encoders.
            if self.settings.get("model_cpu_offload", True):
                pipeline.enable_model_cpu_offload()
        except Exception as exc:
            raise RuntimeUnavailableError(f"Cannot load IP-Adapter: {exc}") from exc
        self._ip_adapter_loaded = True
        return True

    @staticmethod
    def _portrait_crop(image):
        from PIL import ImageStat

        target_ratio = 9 / 16
        current_ratio = image.width / image.height
        if current_ratio > target_ratio:
            width = round(image.height * target_ratio)
            travel = image.width - width
            # A centered 9:16 crop can contain only background when the
            # subject is composed on either side of a landscape frame. Pick
            # the crop with the most visual information instead. This keeps
            # image-to-image generation anchored on the actual subject and
            # prevents valid sparse scenes from repeatedly failing QA as
            # "blank or near-uniform".
            candidates = {round(travel * step / 8) for step in range(9)}
            center = travel / 2

            def score(left):
                sample = image.crop((left, 0, left + width, image.height))
                sample.thumbnail((128, 128))
                stat = ImageStat.Stat(sample.convert("RGB"))
                variance = sum(value * value for value in stat.stddev) / 3
                # Prefer the center only when two crops carry essentially the
                # same amount of detail.
                center_bias = 1 - abs(left - center) / max(center, 1)
                return variance + center_bias * 0.01

            left = max(candidates, key=score)
            return image.crop((left, 0, left + width, image.height))
        height = round(image.width / target_ratio)
        top = (image.height - height) // 2
        return image.crop((0, top, image.width, top + height))

    @staticmethod
    def _reference_canvas(images, cell_size: int = 512, padding: int = 24):
        """Build a stable square cast sheet; input order stays bound to prompt roles."""
        import math

        from PIL import Image

        columns = math.ceil(math.sqrt(len(images)))
        rows = math.ceil(len(images) / columns)
        canvas = Image.new(
            "RGB",
            (columns * cell_size + (columns + 1) * padding,
             rows * cell_size + (rows + 1) * padding),
            (127, 127, 127),
        )
        for index, image in enumerate(images):
            fitted = image.copy()
            fitted.thumbnail((cell_size, cell_size), Image.Resampling.LANCZOS)
            x = padding + (index % columns) * (cell_size + padding) + (cell_size - fitted.width) // 2
            y = padding + (index // columns) * (cell_size + padding) + (cell_size - fitted.height) // 2
            canvas.paste(fitted, (x, y))
        return canvas
