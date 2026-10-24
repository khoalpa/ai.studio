from __future__ import annotations

import hashlib
import io
from typing import Any, Protocol

from PIL import Image, ImageFilter

from ..stage1.png import solid_png
from .config import stage3_config


class PortraitProvider(Protocol):
    provider_id: str

    def generate(
        self,
        *,
        basename: str,
        landscape_bytes: bytes,
        visual_plan_asset: dict[str, Any],
        visual_bible: dict[str, Any],
        attempt: int,
        reference_inputs: list[dict[str, Any]],
    ) -> bytes: ...


class DeterministicPortraitProvider:
    """Produces valid portrait PNGs for workflow tests, not production artwork."""

    provider_id = "deterministic-portrait-provider/1.0"

    def generate(
        self,
        *,
        basename: str,
        landscape_bytes: bytes,
        visual_plan_asset: dict[str, Any],
        visual_bible: dict[str, Any],
        attempt: int,
        reference_inputs: list[dict[str, Any]] | None = None,
    ) -> bytes:
        seed = hashlib.sha256(landscape_bytes + basename.encode() + bytes([attempt])).digest()
        rgb = (48 + seed[0] % 160, 48 + seed[1] % 160, 48 + seed[2] % 160)
        config = stage3_config()["portrait"]
        data, _ = solid_png(config["width"], config["height"], rgb)
        return data


class LocalPortraitProvider:
    provider_id = "local-diffusion-portrait/1.0"

    def __init__(self, registry, assessor) -> None:
        self.registry = registry
        self.assessor = assessor
        binding = registry.binding("portrait")
        self.model_id = binding.get("model_id")
        self.provider_id = f"local-diffusion-portrait/{self.model_id or 'configured'}"
        self._assessments: dict[str, dict[str, Any]] = {}
        self._repair_plans: dict[str, dict[str, Any]] = {}

    def generate(
        self,
        *,
        basename: str,
        landscape_bytes: bytes,
        visual_plan_asset: dict[str, Any],
        visual_bible: dict[str, Any],
        attempt: int,
        reference_inputs: list[dict[str, Any]] | None = None,
    ) -> bytes:
        from ..runtime import GenerationRequest

        config = stage3_config()
        shot = visual_plan_asset.get("shot_spec", {})
        repair = self._repair_plans.get(basename)
        # Put repair constraints before the story prose.  SD3's CLIP encoder has
        # a short token window; appending these constraints made the most
        # important retry instruction disappear on long Vietnamese actions.
        repair_text = (
            "QA REPAIR: " + " ".join(repair["prompt_corrections"]) + ". "
            if repair else ""
        )
        required = ", ".join(
            LocalPortraitProvider._element_text(value)
            for value in shot.get("required_elements", [])
        )
        forbidden = ", ".join(
            LocalPortraitProvider._element_text(value)
            for value in shot.get("forbidden_elements", [])
        )
        prompt_core = str(shot.get("prompt_core", "")).strip()
        # Cover actions can contain the story title. Repeating that title in an
        # outpaint prompt encourages SD to paint letter-like marks into the new
        # canvas, even when typography is in the negative prompt.
        action = (
            "the same focal character and visual story motif shown in the source image"
            if basename == "cover.png" else
            shot.get("action", visual_plan_asset["visual_moment"])
        )
        prompt = (
            f"{repair_text}{'No visible text or lettering. ' if basename == 'cover.png' else ''}"
            f"{prompt_core if basename != 'cover.png' else action} Portrait 9:16, same scene and identities."
            if prompt_core else (
                f"{repair_text}{'No visible text or lettering. ' if basename == 'cover.png' else ''}"
                f"REQUIRED: {required}. FORBIDDEN: {forbidden}. "
                "portrait 9:16 reframing of the exact same scene and moment, "
                f"{action}, "
                f"emotion {shot.get('emotion', 'story-consistent')}, preserve every "
                f"character identity, wardrobe, props, lighting and palette from source, "
                f"{visual_bible['art_direction_id']}, mobile-safe composition, "
                "coherent anatomy, no typography"
            )
        )
        negative = (
            "text, letters, logo, watermark, signature, changed identity, changed wardrobe, "
            "duplicate person, extra limbs, malformed hands, blur, sexualized pose, gore"
        )
        if shot.get("negative_terms"):
            negative += ", " + ", ".join(str(value) for value in shot["negative_terms"])
        if repair and repair["negative_prompt_additions"]:
            negative += ", " + ", ".join(repair["negative_prompt_additions"])
        seed = int.from_bytes(
            hashlib.sha256(landscape_bytes + basename.encode() + bytes([attempt])).digest()[:8],
            "big",
        ) % (2**31)
        runtime_settings = (
            self.registry.image_settings("portrait")
            if hasattr(self.registry, "image_settings")
            else self.registry.config["runtimes"]["diffusers"]
        )
        work = runtime_settings.get("portrait_work_size", [704, 1216])
        capabilities = None
        if hasattr(self.registry, "runtime_for"):
            capabilities = self.registry.runtime_for("portrait").capabilities()
        use_outpaint = bool(capabilities and capabilities.image_outpainting)
        source_canvas, outpaint_mask, transform = _portrait_canvas(
            landscape_bytes,
            work[0],
            work[1],
            shot.get("subjects", []),
            outpaint=use_outpaint,
            reserve_title=basename == "cover.png",
            exclude_title_band=basename == "cover.png",
        )
        parameters = {
            "negative_prompt": negative,
            "fit_prompt_to_token_budget": True,
            "seed": seed,
            "width": work[0],
            "height": work[1],
            "output_width": config["portrait"]["width"],
            "output_height": config["portrait"]["height"],
            "strength": (
                repair["parameter_adjustments"]["strength"]
                if repair and repair["parameter_adjustments"].get("strength") is not None else
                runtime_settings.get("portrait_outpaint_strength", 0.92)
                if use_outpaint else runtime_settings.get("portrait_strength", 0.38)
            ),
        }
        if use_outpaint:
            parameters.update({
                "outpaint_image": source_canvas,
                "outpaint_mask": outpaint_mask,
                "reference_inputs": reference_inputs or [],
            })
        else:
            parameters["init_image"] = source_canvas
        data = self.registry.generate_image(
            "portrait",
            GenerationRequest(
                prompt=prompt,
                model=self.model_id,
                parameters=parameters,
                request_id=f"stage3-{basename}-{attempt}",
            ),
        )
        self._assessments[basename] = self.assessor.assess(
            data,
            prompt=prompt,
            expected_dimensions=(config["portrait"]["width"], config["portrait"]["height"]),
            # The cover canvas excludes Stage 2's trusted title band. Compare
            # visual parity against that same artwork region, not typography
            # which the portrait is deliberately forbidden to reproduce.
            reference=_without_cover_title_band(landscape_bytes) if basename == "cover.png" else landscape_bytes,
            asset_type="cover" if basename == "cover.png" else "portrait",
            required_elements=[
                item for item in shot.get("required_elements", [])
                if not item.startswith("character:") and not item.startswith("composition:")
            ],
            forbidden_elements=shot.get("forbidden_elements", []),
            fidelity_probes=shot.get("fidelity_probes", []),
            identity_references=[item["data"] for item in (reference_inputs or [])],
        )
        self._assessments[basename]["generation_seed"] = seed
        self._assessments[basename]["portrait_transform"] = transform
        if repair:
            self._assessments[basename]["repair_plan_applied"] = repair
        if hasattr(self.registry, "image_postprocess_metadata"):
            self._assessments[basename]["upscale_postprocess"] = (
                self.registry.image_postprocess_metadata("portrait")
            )
        return data

    def assessment(self, basename: str) -> dict[str, Any]:
        return self._assessments[basename]

    def set_repair_plan(self, basename: str, plan: dict[str, Any]) -> None:
        self._repair_plans[basename] = plan

    @staticmethod
    def _element_text(value: str) -> str:
        labels = {
            "prop:paper boat": "one small folded paper boat made of paper, not a ship",
            "prop:duck pillow": "one duck-shaped fabric pillow, not a living duck",
            "prop:blue pillow": "one blue fabric pillow",
            "duplicate_character": "duplicate or extra person",
            "uncontrolled_text": "uncontrolled text or letters",
        }
        return labels.get(value, value.replace(":", " ").replace("_", " "))


def _without_cover_title_band(source: bytes) -> bytes:
    image = Image.open(io.BytesIO(source)).convert("RGB")
    image = image.crop((0, round(image.height * 0.22), image.width, image.height))
    encoded = io.BytesIO()
    image.save(encoded, format="PNG", optimize=True)
    return encoded.getvalue()


def _portrait_canvas(
    source: bytes,
    width: int,
    height: int,
    subjects: list[dict[str, Any]],
    *,
    outpaint: bool,
    reserve_title: bool,
    exclude_title_band: bool = False,
) -> tuple[bytes, bytes | None, dict[str, Any]]:
    image = Image.open(io.BytesIO(source)).convert("RGB")
    # Stage 2 adds trusted typography to the landscape cover after its image
    # QA. It must not be copied into Stage 3's diffusion input: the model turns
    # those letters into pseudo-text that correctly fails portrait OCR QA.
    cropped_top = round(image.height * 0.22) if exclude_title_band else 0
    if cropped_top:
        image = image.crop((0, cropped_top, image.width, image.height))
    scale = width / image.width
    fitted = image.resize((width, round(image.height * scale)), Image.Resampling.LANCZOS)
    focal_y = (
        sum(float(item.get("position", {}).get("y", 0.5)) for item in subjects) / len(subjects)
        if subjects else 0.5
    )
    target_y = 0.62 if reserve_title else 0.5
    top = round(target_y * height - focal_y * fitted.height)
    top = max(0, min(height - fitted.height, top))

    background = image.resize((width, height), Image.Resampling.LANCZOS).filter(
        ImageFilter.GaussianBlur(radius=max(12, width // 32))
    )
    canvas = background.copy()
    canvas.paste(fitted, (0, top))
    mask = Image.new("L", (width, height), 255)
    preserved = Image.new("L", (width, height), 0)
    preserved.paste(255, (0, top, width, top + fitted.height))
    mask = Image.eval(preserved, lambda value: 255 - value).filter(ImageFilter.GaussianBlur(12))

    canvas_bytes = io.BytesIO()
    canvas.save(canvas_bytes, format="PNG", optimize=True)
    mask_bytes = None
    if outpaint:
        encoded_mask = io.BytesIO()
        mask.save(encoded_mask, format="PNG", optimize=True)
        mask_bytes = encoded_mask.getvalue()
    evidence = {
        "mode": "OUTPAINT" if outpaint else "RECOMPOSE_IMG2IMG",
        "source_top_crop_pixels": cropped_top,
        "source_region": [0, top, width, top + fitted.height],
        "subject_focal_y": round(focal_y, 3),
        "target_focal_y": target_y,
        "title_safe_area_reserved": reserve_title,
        "mask_feather_pixels": 12 if outpaint else 0,
    }
    return canvas_bytes.getvalue(), mask_bytes, evidence
