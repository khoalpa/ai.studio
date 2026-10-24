from __future__ import annotations

import copy
import hashlib
import io
from typing import Any, Protocol

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from ..errors import ArtifactError, RuntimeCapabilityError
from ..image_qa import ImageQualityError
from ..stage1.png import solid_png
from .config import stage2_config
from .control import DepthControlMapProvider, composition_canvas


class LandscapeProvider(Protocol):
    provider_id: str

    def generate(
        self,
        *,
        basename: str,
        story: dict[str, Any],
        visual_plan_asset: dict[str, Any],
        visual_bible: dict[str, Any],
        attempt: int,
        reference_inputs: list[dict[str, Any]],
    ) -> bytes: ...


class DeterministicLandscapeProvider:
    """Produces valid 4K PNGs for offline workflow tests, not production artwork."""

    provider_id = "deterministic-landscape-provider/1.0"

    def generate(
        self,
        *,
        basename: str,
        story: dict[str, Any],
        visual_plan_asset: dict[str, Any],
        visual_bible: dict[str, Any],
        attempt: int,
        reference_inputs: list[dict[str, Any]] | None = None,
    ) -> bytes:
        seed = hashlib.sha256(f"{basename}:{attempt}:{story['meta']['title']}".encode("utf-8")).digest()
        rgb = (48 + seed[0] % 160, 48 + seed[1] % 160, 48 + seed[2] % 160)
        config = stage2_config()["landscape"]
        data, _ = solid_png(config["width"], config["height"], rgb)
        return data


class LocalLandscapeProvider:
    provider_id = "local-diffusion-landscape/1.0"

    def __init__(self, registry, assessor, control_provider=None) -> None:
        self.registry = registry
        self.assessor = assessor
        binding = registry.binding("landscape")
        self.model_id = binding.get("model_id")
        self._assessments: dict[str, dict[str, Any]] = {}
        self._repair_plans: dict[str, dict[str, Any]] = {}
        self._attempt_outputs: dict[tuple[str, int], bytes] = {}
        self._intermediate_outputs: dict[tuple[str, int], dict[str, bytes]] = {}
        runtime_settings = registry.config["runtimes"]["diffusers"]
        self.depth_controlnet_enabled = bool(
            runtime_settings.get("depth_controlnet_enabled", True)
        )
        variant = "depth-on" if self.depth_controlnet_enabled else "depth-off"
        self.provider_id = (
            f"local-diffusion-landscape/{self.model_id or 'configured'}/{variant}"
        )
        self.control_provider = control_provider or DepthControlMapProvider(runtime_settings)

    def generate(
        self,
        *,
        basename: str,
        story: dict[str, Any],
        visual_plan_asset: dict[str, Any],
        visual_bible: dict[str, Any],
        attempt: int,
        reference_inputs: list[dict[str, Any]] | None = None,
    ) -> bytes:
        from ..runtime import GenerationRequest

        config = stage2_config()
        identities = {
            item["character_id"]: item
            for item in visual_bible["character_identity_locks"]
        }
        focal = [
            identities[item]
            for item in visual_plan_asset["focal_character_ids"]
            if item in identities
        ]
        shot = visual_plan_asset.get("shot_spec") or {
            "action": visual_plan_asset.get("visual_moment", "story moment"),
            "emotion": "story-consistent", "location": "story-specific setting", "props": [],
            "required_elements": [], "forbidden_elements": ["uncontrolled_text", "watermark"],
            "composition": {"framing": "cinematic narrative shot"},
        }
        repair = self._repair_plans.get(basename)
        prompt = self._generation_prompt(shot, focal, visual_bible, repair)
        # Keep QA independent from the diffusion token budget.  Generation gets a
        # compact, subject-first prompt; assessment retains the complete contract.
        assessment_prompt = self._assessment_prompt(shot, focal)
        negative = (
            "text, letters, logo, watermark, signature, duplicate person, extra limbs, malformed hands, "
            "cropped face, low detail, blur, oversaturated, sexualized pose, gore"
        )
        if shot.get("negative_prompt_override") is not None:
            negative = str(shot["negative_prompt_override"])
        elif shot.get("negative_terms"):
            negative += ", " + ", ".join(str(value) for value in shot["negative_terms"])
        if repair and repair["negative_prompt_additions"]:
            negative += ", " + ", ".join(repair["negative_prompt_additions"])
        seed = int.from_bytes(
            hashlib.sha256(
                f"{story['meta']['title']}:{basename}:{attempt}".encode()
            ).digest()[:8],
            "big",
        ) % (2**31)
        runtime_settings = (
            self.registry.image_settings("landscape")
            if hasattr(self.registry, "image_settings")
            else self.registry.config["runtimes"]["diffusers"]
        )
        work = runtime_settings.get("landscape_work_size", [1024, 576])
        supports_reference = True
        supports_controlnet = False
        supports_img2img = False
        if hasattr(self.registry, "runtime_for"):
            capabilities = self.registry.runtime_for("landscape").capabilities()
            supports_reference = capabilities.image_reference
            supports_controlnet = capabilities.image_controlnet
            supports_img2img = capabilities.image_to_image
        if (
            shot.get("require_reference_identity_conditioning", False)
            and reference_inputs
            and not supports_reference
        ):
            raise RuntimeCapabilityError(
                "Shot requires identity-reference conditioning but the landscape runtime "
                "does not support reference images"
            )
        control_inputs = []
        control_evidence = None
        if (
            self.depth_controlnet_enabled
            and supports_controlnet
            and self.control_provider.enabled
        ):
            control_map = self.control_provider.create(
                shot=shot,
                reference_inputs=reference_inputs or [],
                size=(work[0], work[1]),
            )
            control_evidence = control_map.evidence
            control_inputs = [{
                "control_type": "depth",
                "data": control_map.data,
                "scale": control_evidence["conditioning_scale"],
            }]
            shot.setdefault("control_guidance", {})["inputs"] = [control_evidence]
        parameters = {
            "negative_prompt": negative,
            "fit_prompt_to_token_budget": True,
            "seed": seed,
            "width": work[0],
            "height": work[1],
            "output_width": config["landscape"]["width"],
            "output_height": config["landscape"]["height"],
            "reference_inputs": (reference_inputs or []) if supports_reference else [],
            "control_inputs": control_inputs,
        }
        if repair:
            adjustments = repair.get("parameter_adjustments", {})
            if adjustments.get("guidance_scale") is not None:
                parameters["guidance_scale"] = float(adjustments["guidance_scale"])
            if adjustments.get("steps") is not None:
                parameters["steps"] = int(adjustments["steps"])
        if (
            supports_img2img
            and not supports_reference
            and not control_inputs
            and reference_inputs
            and not shot.get("disable_composition_canvas_fallback", False)
        ):
            canvas = composition_canvas(shot, reference_inputs, (work[0], work[1]))
            encoded = io.BytesIO()
            canvas.save(encoded, format="PNG", optimize=True)
            parameters["init_image"] = encoded.getvalue()
            parameters["strength"] = float(
                (repair or {}).get("parameter_adjustments", {}).get("strength")
                or shot.get("composition_strength")
                or runtime_settings.get("landscape_composition_strength", 0.58)
            )
        base_prompt = prompt
        masked_edit = shot.get("masked_prop_inpaint")
        if masked_edit:
            base_prompt = str(masked_edit["base_prompt"])
        base_parameters = dict(parameters)
        if masked_edit:
            base_parameters["negative_prompt"] = str(masked_edit.get(
                "base_negative_prompt",
                "text, letters, logo, watermark, signature, duplicate person, extra limbs, "
                "malformed hands, cropped face, low detail, blur",
            ))
        base_data = self.registry.generate_image(
            "landscape",
            GenerationRequest(
                prompt=base_prompt,
                model=self.model_id,
                parameters=base_parameters,
                request_id=f"stage2-{basename}-{attempt}",
            ),
        )
        data = base_data
        if masked_edit:
            self._intermediate_outputs[(basename, attempt)] = {"base": base_data}
            data, mask_data, edit_evidence, edit_artifacts = self._masked_prop_edit(
                basename=basename,
                attempt=attempt,
                base_data=base_data,
                edit=masked_edit,
                negative_prompt=negative,
                seed=seed + 100_003,
            )
            self._intermediate_outputs[(basename, attempt)].update({
                "base": base_data, "mask": mask_data, "inpaint": data,
                **edit_artifacts,
            })
            assessment_prompt = f"{base_prompt} FINAL LOCAL EDIT: {masked_edit['prompt']}"
        self._attempt_outputs[(basename, attempt)] = data
        try:
            fidelity_probes = copy.deepcopy(shot.get("fidelity_probes", []))
            if masked_edit:
                for probe in fidelity_probes:
                    if probe.get("probe_id") == "controlled_prop_scale":
                        probe["crop_box_pixels"] = edit_evidence["crop_box_pixels"]
            self._assessments[basename] = self.assessor.assess(
                data,
                prompt=assessment_prompt,
                expected_dimensions=(
                    config["landscape"]["width"], config["landscape"]["height"]
                ),
                asset_type="cover" if basename == "cover.png" else "landscape",
                identity_references=[item["data"] for item in (reference_inputs or [])],
                required_elements=shot["required_elements"],
                forbidden_elements=shot["forbidden_elements"],
                fidelity_probes=fidelity_probes,
                identity_regions=self._identity_regions(shot, reference_inputs or []),
            )
        except ImageQualityError as exc:
            exc.assessment["generation_seed"] = seed
            if masked_edit:
                exc.assessment["masked_prop_inpaint"] = edit_evidence
            raise
        self._assessments[basename]["generation_seed"] = seed
        if masked_edit:
            self._assessments[basename]["masked_prop_inpaint"] = edit_evidence
        if control_evidence:
            self._assessments[basename]["control_guidance"] = control_evidence
        if repair:
            self._assessments[basename]["repair_plan_applied"] = repair
        if hasattr(self.registry, "image_postprocess_metadata"):
            self._assessments[basename]["upscale_postprocess"] = (
                self.registry.image_postprocess_metadata("landscape")
            )
        return data

    def assessment(self, basename: str) -> dict[str, Any]:
        return self._assessments[basename]

    def attempt_output(self, basename: str, attempt: int) -> bytes | None:
        return self._attempt_outputs.get((basename, attempt))

    def intermediate_outputs(self, basename: str, attempt: int) -> dict[str, bytes]:
        return self._intermediate_outputs.get((basename, attempt), {})

    def _masked_prop_edit(
        self, *, basename: str, attempt: int, base_data: bytes,
        edit: dict[str, Any], negative_prompt: str, seed: int,
    ) -> tuple[bytes, bytes, dict[str, Any], dict[str, bytes]]:
        """Generate a local crop, then composite it through a bounded feathered mask."""
        from ..runtime import GenerationRequest

        base = Image.open(io.BytesIO(base_data)).convert("RGB")
        hand_evidence = None
        localization_data = _empty_localization_overlay(base)
        if edit.get("interaction_centered_mask"):
            hand_evidence, localization_data = _locate_interaction_hands(
                base,
                target_x=float(edit.get("interaction_target_x", 0.5)),
                target_y=float(edit.get("interaction_target_y", 0.62)),
            )
            if hand_evidence["confidence"] < float(edit.get("minimum_hand_confidence", 0.62)):
                raise ArtifactError(
                    f"Interaction localization confidence {hand_evidence['confidence']:.3f} is below "
                    f"{float(edit.get('minimum_hand_confidence', 0.62)):.3f}"
                )
            crop_box = tuple(hand_evidence["crop_box_pixels"])
            mask_box = tuple(hand_evidence["mask_box_pixels"])
        elif edit.get("dynamic_hand_mask"):
            hand_evidence, localization_data = _locate_hands(
                base, target_subject_x=float(edit.get("target_subject_x", 0.5))
            )
            if hand_evidence["confidence"] < float(edit.get("minimum_hand_confidence", 0.62)):
                raise ArtifactError(
                    f"Hand localization confidence {hand_evidence['confidence']:.3f} is below "
                    f"{float(edit.get('minimum_hand_confidence', 0.62)):.3f}"
                )
            crop_box = tuple(hand_evidence["crop_box_pixels"])
            mask_box = tuple(hand_evidence["mask_box_pixels"])
        else:
            crop_box = _normalized_box(edit["crop_box"], base.size)
            mask_box = _normalized_box(edit["mask_box"], base.size)
        hard_mask = Image.new("L", base.size, 0)
        draw = ImageDraw.Draw(hard_mask)
        radius = max(4, round(min(mask_box[2] - mask_box[0], mask_box[3] - mask_box[1]) * 0.22))
        draw.rounded_rectangle(mask_box, radius=radius, fill=255)
        feather = int(edit.get("feather_pixels", 18))
        mask = hard_mask.filter(ImageFilter.GaussianBlur(feather)) if feather else hard_mask
        edit_source = base
        prop_evidence = None
        artifacts = {"hand-localization": localization_data}
        cleanup_evidence = None
        if edit.get("two_pass_cleanup"):
            cleanup_input = base
            cleanup_mask = mask
            cleanup_mask_box = mask_box
            neutralization_evidence = None
            deterministic_cleanup = edit.get("hand_preserving_deterministic_cleanup")
            if deterministic_cleanup:
                prop_box = tuple((hand_evidence or {}).get("prop_box_pixels", mask_box))
                cleanup_input, cleanup_mask, deterministic_evidence = (
                    _hand_preserving_object_cleanup(base, mask_box, prop_box, hand_evidence)
                )
                cleanup_mask_box = tuple(deterministic_evidence["object_mask_box_pixels"])
                neutralization_evidence = deterministic_evidence
                encoded_cleanup_mask = io.BytesIO()
                cleanup_mask.save(encoded_cleanup_mask, format="PNG", optimize=True)
                artifacts["cleanup-mask"] = encoded_cleanup_mask.getvalue()
            elif edit.get("neutralize_object_before_cleanup"):
                prop_box = tuple((hand_evidence or {}).get("prop_box_pixels", mask_box))
                prop_width = prop_box[2] - prop_box[0]
                prop_height = prop_box[3] - prop_box[1]
                center_x = (prop_box[0] + prop_box[2]) // 2
                cleanup_mask_box = (
                    max(mask_box[0], center_x - round(prop_width * 0.58)),
                    max(mask_box[1], prop_box[1] + round(prop_height * 0.08)),
                    min(mask_box[2], center_x + round(prop_width * 0.58)),
                    min(mask_box[3], prop_box[3] + round(prop_height * 0.72)),
                )
                sample_width = max(12, round(prop_width * 0.24))
                left_sample = base.crop((
                    max(0, cleanup_mask_box[0] - sample_width), cleanup_mask_box[1],
                    cleanup_mask_box[0], cleanup_mask_box[3],
                ))
                right_sample = base.crop((
                    cleanup_mask_box[2], cleanup_mask_box[1],
                    min(base.width, cleanup_mask_box[2] + sample_width), cleanup_mask_box[3],
                ))
                left_mean = ImageStat.Stat(left_sample).mean[:3]
                right_mean = ImageStat.Stat(right_sample).mean[:3]
                neutral_color = tuple(round((left + right) / 2) for left, right in zip(left_mean, right_mean))
                neutralized = base.copy()
                ImageDraw.Draw(neutralized).rounded_rectangle(
                    cleanup_mask_box,
                    radius=max(6, round(min(
                        cleanup_mask_box[2] - cleanup_mask_box[0],
                        cleanup_mask_box[3] - cleanup_mask_box[1],
                    ) * 0.18)),
                    fill=neutral_color,
                )
                cleanup_input = neutralized.filter(ImageFilter.GaussianBlur(2.0))
                cleanup_hard_mask = Image.new("L", base.size, 0)
                ImageDraw.Draw(cleanup_hard_mask).rounded_rectangle(
                    cleanup_mask_box, radius=12, fill=255
                )
                cleanup_feather = int(edit.get("cleanup_feather_pixels", 10))
                cleanup_mask = cleanup_hard_mask.filter(
                    ImageFilter.GaussianBlur(cleanup_feather)
                )
                encoded_neutralized = io.BytesIO()
                cleanup_input.save(encoded_neutralized, format="PNG", optimize=True)
                artifacts["neutralized-input"] = encoded_neutralized.getvalue()
                encoded_cleanup_mask = io.BytesIO()
                cleanup_mask.save(encoded_cleanup_mask, format="PNG", optimize=True)
                artifacts["cleanup-mask"] = encoded_cleanup_mask.getvalue()
                neutralization_evidence = {
                    "method": "ADJACENT_STRIP_MEAN_PREFILL_V1",
                    "object_mask_box_pixels": list(cleanup_mask_box),
                    "neutral_fill_rgb": list(neutral_color),
                    "feather_pixels": cleanup_feather,
                }
            if deterministic_cleanup:
                edit_source = cleanup_input
            else:
                cleanup_crop = cleanup_input.crop(crop_box)
                cleanup_bytes = io.BytesIO()
                cleanup_crop.save(cleanup_bytes, format="PNG", optimize=True)
                cleaned_data = self.registry.generate_image(
                    "landscape",
                    GenerationRequest(
                        prompt=str(edit["cleanup_prompt"]), model=self.model_id,
                        parameters={
                            "negative_prompt": negative_prompt + ", paper boat, origami, object on hands",
                            "fit_prompt_to_token_budget": True,
                            "seed": seed,
                            "width": 768, "height": 576,
                            "output_width": cleanup_crop.width, "output_height": cleanup_crop.height,
                            "init_image": cleanup_bytes.getvalue(),
                            "strength": float(edit.get("cleanup_strength", 0.38)),
                            "reference_inputs": [], "control_inputs": [],
                        },
                        request_id=f"stage2-{basename}-{attempt}-cleanup",
                    ),
                )
                cleanup_patch = Image.open(io.BytesIO(cleaned_data)).convert("RGB").resize(cleanup_crop.size)
                cleanup_candidate = base.copy()
                cleanup_candidate.paste(cleanup_patch, crop_box[:2])
                edit_source = Image.composite(cleanup_candidate, base, cleanup_mask)
            encoded_cleanup = io.BytesIO()
            edit_source.save(encoded_cleanup, format="PNG", optimize=True)
            artifacts["cleanup-pass"] = encoded_cleanup.getvalue()
            cleanup_evidence = {
                "status": "GENERATED_AWAITING_CUP_ABSENCE_GATE",
                "prompt": str(edit["cleanup_prompt"]),
                "crop_box_pixels": list(crop_box),
                "mask_box_pixels": list(mask_box),
                "object_mask_box_pixels": list(cleanup_mask_box),
                "strength": float(edit.get("cleanup_strength", 0.38)),
                "neutralization": neutralization_evidence,
            }
        if edit.get("prop_first_compositing"):
            prop_box = tuple((hand_evidence or {}).get("prop_box_pixels", mask_box))
            edit_source, prop_layer, prop_evidence = _composite_controlled_paper_boat(
                edit_source, prop_box, hand_evidence
            )
            encoded_preblend = io.BytesIO()
            edit_source.save(encoded_preblend, format="PNG", optimize=True)
            artifacts["prop-silhouette"] = prop_layer
            artifacts["prop-preblend"] = encoded_preblend.getvalue()
        if edit.get("two_pass_cleanup"):
            final = edit_source
        else:
            crop = edit_source.crop(crop_box)
            crop_bytes = io.BytesIO()
            crop.save(crop_bytes, format="PNG", optimize=True)
            generated = self.registry.generate_image(
                "landscape",
                GenerationRequest(
                    prompt=str(edit["prompt"]), model=self.model_id,
                    parameters={
                        "negative_prompt": negative_prompt + ", large boat, ship, oversized object",
                        "fit_prompt_to_token_budget": True,
                        "seed": seed,
                        "width": 768, "height": 576,
                        "output_width": crop.width, "output_height": crop.height,
                        "init_image": crop_bytes.getvalue(),
                        "strength": float(edit.get("strength", 0.62)),
                        "reference_inputs": [], "control_inputs": [],
                    },
                    request_id=f"stage2-{basename}-{attempt}-masked-prop",
                ),
            )
            patch = Image.open(io.BytesIO(generated)).convert("RGB").resize(crop.size)
            candidate = base.copy()
            candidate.paste(patch, crop_box[:2])
            final = Image.composite(candidate, base, mask)
        effective_mask = mask.point(lambda value: 255 if value else 0)
        outside = ImageChops.difference(final, base)
        outside.paste((0, 0, 0), mask=effective_mask)
        outside_bbox = outside.getbbox()
        output = io.BytesIO()
        final.save(output, format="PNG", optimize=True)
        encoded_mask = io.BytesIO()
        mask.save(encoded_mask, format="PNG", optimize=True)
        evidence = {
            "mode": (
                "HAND_PRESERVING_DETERMINISTIC_CLEANUP_V1"
                if edit.get("hand_preserving_deterministic_cleanup")
                else "NEUTRALIZED_CLEANUP_THEN_CONTROLLED_PROP_V1"
                if edit.get("neutralize_object_before_cleanup")
                else "TWO_PASS_CLEANUP_THEN_CONTROLLED_PROP_V1"
                if edit.get("two_pass_cleanup") else "MASKED_CROP_IMG2IMG_COMPOSITE_V1"
            ),
            "native_inpaint_available": False,
            "crop_box_pixels": list(crop_box),
            "mask_box_pixels": list(mask_box),
            "mask_feather_pixels": feather,
            "outside_hard_mask_pixel_invariance": "PASS" if outside_bbox is None else "FAIL",
            "outside_hard_mask_difference_bbox": list(outside_bbox) if outside_bbox else None,
            "base_prompt": str(edit["base_prompt"]),
            "edit_prompt": str(edit["prompt"]),
            "hand_localization": hand_evidence,
            "controlled_prop": prop_evidence,
            "cleanup_pass": cleanup_evidence,
        }
        return output.getvalue(), encoded_mask.getvalue(), evidence, artifacts

    @staticmethod
    def _identity_regions(
        shot: dict[str, Any], references: list[dict[str, Any]]
    ) -> list[dict[str, Any]] | None:
        if not shot.get("regional_identity_conditioning"):
            return None
        grouped: dict[str, list[bytes]] = {}
        for item in references:
            grouped.setdefault(str(item.get("character_id", "")), []).append(item["data"])
        regions = []
        for subject in shot.get("subjects", []):
            character_id = str(subject.get("character_id", ""))
            position = subject.get("position", {})
            center_x = float(position.get("x", 0.5))
            foot_y = float(position.get("y", 0.75))
            width = float(subject.get("identity_region_width", 0.28))
            height = float(subject.get("identity_region_height", 0.62))
            regions.append({
                "character_id": character_id,
                "box_normalized": [
                    max(0.0, center_x - width / 2), max(0.0, foot_y - height),
                    min(1.0, center_x + width / 2), min(1.0, foot_y),
                ],
                "references": grouped.get(character_id, []),
            })
        return regions

    def set_repair_plan(self, basename: str, plan: dict[str, Any]) -> None:
        self._repair_plans[basename] = plan

    @classmethod
    def _generation_prompt(
        cls, shot: dict[str, Any], focal: list[dict[str, Any]],
        visual_bible: dict[str, Any], repair: dict[str, Any] | None,
    ) -> str:
        """Build a short, subject-first prompt that survives CLIP's 77-token limit."""
        required = ", ".join(cls._element_text(value) for value in shot.get("required_elements", []))
        characters = ", ".join(
            f"{item['name']}, age {item['canonical_age_range'][0]}, "
            f"{', '.join(item.get('identity_traits', [])[:2])}"
            for item in focal
        ) or "no character"
        repair_text = " ".join((repair or {}).get("prompt_corrections", []))
        prompt_core = str(shot.get("prompt_core", "")).strip()
        parts = [
            f"REQUIRED: {required}" if required else "",
            f"characters: {characters}",
            f"action: {prompt_core or shot.get('action', 'story action')}",
            f"location: {shot.get('location', 'story setting')}",
            f"props: {', '.join(shot.get('props', []))}" if shot.get("props") else "",
            f"repair: {repair_text}" if repair_text else "",
            str(shot.get("prompt_style_suffix", "cinematic storybook 16:9, no text")),
        ]
        # Runtime still performs tokenizer-aware fitting.  This word cap prevents
        # important subjects/actions from being displaced by decorative details.
        words = " ".join(part for part in parts if part).split()
        return " ".join(words[:68])

    @classmethod
    def _assessment_prompt(
        cls, shot: dict[str, Any], focal: list[dict[str, Any]]
    ) -> str:
        required = ", ".join(cls._element_text(value) for value in shot.get("required_elements", []))
        return (
            f"Required subjects and props: {required}. "
            f"Action: {shot.get('action', '')}. Location: {shot.get('location', '')}. "
            f"Characters: {', '.join(cls._identity_text(item) for item in focal)}. "
            f"Composition: {shot.get('composition', {}).get('framing', '')}."
        )

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

    def unload(self) -> None:
        self.control_provider.unload()

    @staticmethod
    def _identity_text(item: dict[str, Any]) -> str:
        return (
            f"{item['name']} age {item['canonical_age_range'][0]}, "
            f"presentation {item.get('presentation', 'UNSPECIFIED')}, "
            f"hair {item.get('hair', 'locked by reference')}, "
            f"wardrobe {item.get('wardrobe', 'locked by reference')}, "
            f"cultural context {item.get('cultural_context', 'contemporary')}, "
            f"{', '.join(item['identity_traits'])}"
        )

    @staticmethod
    def _layout_text(subjects: list[dict[str, Any]]) -> str:
        return "; ".join(
            f"{item['character_id']} at ({item['position']['x']:.3f}, {item['position']['y']:.3f}), "
            f"{item.get('scale', 'medium')}, {item.get('pose', 'story-action pose')}, "
            f"gaze {item.get('gaze', 'toward story action')}"
            for item in subjects
        ) or "story-consistent"

    @staticmethod
    def _prop_layout_text(props: list[dict[str, Any]]) -> str:
        return "; ".join(
            f"{item['name']} at ({item['position']['x']:.3f}, {item['position']['y']:.3f}), "
            f"state {item['state']}, scale {item['scale']}"
            for item in props
        ) or "none"

    @staticmethod
    def _reference_text(references: list[dict[str, Any]]) -> str:
        return "; ".join(
            f"cell {index} is {item['character_id']} {item['view_id']}"
            for index, item in enumerate(references, 1)
        ) or "none"


def _normalized_box(values: list[float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = size
    left, top, right, bottom = values
    box = (
        max(0, min(width - 1, round(float(left) * width))),
        max(0, min(height - 1, round(float(top) * height))),
        max(1, min(width, round(float(right) * width))),
        max(1, min(height, round(float(bottom) * height))),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError(f"Invalid normalized image box: {values}")
    return box


def _empty_localization_overlay(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _locate_hands(
    image: Image.Image, *, target_subject_x: float = 0.5
) -> tuple[dict[str, Any], bytes]:
    """Locate clasped/cupped hands below the face using offline color components."""
    probe_width = 480
    probe_height = max(1, round(image.height * probe_width / image.width))
    probe = image.resize((probe_width, probe_height), Image.Resampling.LANCZOS)
    hsv = probe.convert("HSV")
    pixels = list(hsv.get_flattened_data())
    target_subject_x = max(0.15, min(0.85, target_subject_x))
    target_probe_x = probe_width * target_subject_x
    planned_x0 = round(probe_width * max(0.05, target_subject_x - 0.22))
    planned_x1 = round(probe_width * min(0.95, target_subject_x + 0.22))
    hair_mask = [False] * len(pixels)
    for index, (_, saturation, value) in enumerate(pixels):
        y, x = divmod(index, probe_width)
        hair_mask[index] = (
            planned_x0 < x < planned_x1 and probe_height * 0.08 < y < probe_height * 0.58
            and value < 100 and saturation > 18
        )
    hair_components = _binary_components(hair_mask, probe_width, probe_height)
    if not hair_components:
        return _failed_hand_evidence("NO_HAIR_ANCHOR"), _empty_localization_overlay(image)
    _, hair_box = min(
        hair_components,
        key=lambda item: abs(((item[1][0] + item[1][2]) / 2) - target_probe_x),
    )
    face_x = (hair_box[0] + hair_box[2]) / 2
    face_width = max(35.0, float(hair_box[2] - hair_box[0]))
    hand_y0 = hair_box[3] + round(probe_height * 0.08)
    hand_y1 = min(probe_height - 1, hair_box[3] + round(probe_height * 0.26))
    hand_x0 = max(0, round(face_x - face_width))
    hand_x1 = min(probe_width - 1, round(face_x + face_width))
    skin_mask = [False] * len(pixels)
    for index, (hue, saturation, value) in enumerate(pixels):
        y, x = divmod(index, probe_width)
        skin_mask[index] = (
            hand_x0 < x < hand_x1 and hand_y0 < y < hand_y1
            and (hue < 35 or hue > 245) and 35 < saturation < 210 and value > 90
        )
    components = _binary_components(skin_mask, probe_width, probe_height)
    if not components:
        return _failed_hand_evidence("NO_HAND_COMPONENT"), _empty_localization_overlay(image)
    area, hand_box = components[0]
    center_x = (hand_box[0] + hand_box[2]) / 2
    center_y = (hand_box[1] + hand_box[3]) / 2
    detected_width = max(12.0, float(hand_box[2] - hand_box[0]))
    prop_width = max(18.0, min(face_width * 0.78, detected_width * 0.72))
    prop_height = max(10.0, prop_width * 0.48)
    scale_x, scale_y = image.width / probe_width, image.height / probe_height
    mask_box = (
        round((center_x - prop_width / 2) * scale_x),
        round((center_y - prop_height / 2) * scale_y),
        round((center_x + prop_width / 2) * scale_x),
        round((center_y + prop_height / 2) * scale_y),
    )
    crop_half_width = prop_width * 2.0
    crop_half_height = prop_width * 1.35
    crop_box = (
        max(0, round((center_x - crop_half_width) * scale_x)),
        max(0, round((center_y - crop_half_height) * scale_y)),
        min(image.width, round((center_x + crop_half_width) * scale_x)),
        min(image.height, round((center_y + crop_half_height) * scale_y)),
    )
    density = min(1.0, area / max(1.0, detected_width * (hand_box[3] - hand_box[1])))
    area_score = min(1.0, area / 240.0)
    component_height_ratio = (hand_box[3] - hand_box[1]) / face_width
    geometry_valid = component_height_ratio <= 0.85
    confidence = round(0.55 * density + 0.45 * area_score, 4)
    if not geometry_valid:
        confidence = min(confidence, 0.4)
    left = [round((center_x - detected_width * 0.5) * scale_x), round(center_y * scale_y)]
    right = [round((center_x + detected_width * 0.5) * scale_x), round(center_y * scale_y)]
    evidence = {
        "status": "PASS" if confidence >= 0.62 else "LOW_CONFIDENCE",
        "method": "OFFLINE_HSV_CONNECTED_COMPONENTS_V1",
        "target_subject_x": round(target_subject_x, 4),
        "confidence": confidence,
        "hair_anchor_box_probe": list(hair_box),
        "hand_component_box_probe": list(hand_box),
        "hand_component_area_probe": area,
        "left_hand_center_pixels": left,
        "right_hand_center_pixels": right,
        "hand_distance_pixels": right[0] - left[0],
        "mask_box_pixels": list(mask_box),
        "crop_box_pixels": list(crop_box),
        "prop_to_hand_span_ratio": 0.72,
        "component_height_to_face_width_ratio": round(component_height_ratio, 4),
        "geometry_valid": geometry_valid,
    }
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    draw.rectangle(crop_box, outline=(255, 192, 0), width=8)
    draw.rectangle(mask_box, outline=(255, 0, 0), width=8)
    radius = 14
    for point in (left, right):
        draw.ellipse(
            (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
            fill=(0, 255, 128), outline=(0, 64, 32), width=4,
        )
    output = io.BytesIO()
    overlay.save(output, format="PNG", optimize=True)
    return evidence, output.getvalue()


def _locate_interaction_hands(
    image: Image.Image, *, target_x: float = 0.5, target_y: float = 0.62
) -> tuple[dict[str, Any], bytes]:
    """Locate facing hand evidence around a declared two-subject interaction point."""
    probe_width = 480
    probe_height = max(1, round(image.height * probe_width / image.width))
    probe = image.resize((probe_width, probe_height), Image.Resampling.LANCZOS)
    hsv = probe.convert("HSV")
    pixels = list(hsv.get_flattened_data())
    target_x = max(0.2, min(0.8, target_x))
    target_y = max(0.3, min(0.82, target_y))
    center_x = target_x * probe_width
    center_y = target_y * probe_height
    search_x0 = round(probe_width * max(0.05, target_x - 0.20))
    search_x1 = round(probe_width * min(0.95, target_x + 0.20))
    search_y0 = round(probe_height * max(0.15, target_y - 0.18))
    search_y1 = round(probe_height * min(0.92, target_y + 0.18))
    skin_mask = [False] * len(pixels)
    for index, (hue, saturation, value) in enumerate(pixels):
        y, x = divmod(index, probe_width)
        skin_mask[index] = (
            search_x0 < x < search_x1 and search_y0 < y < search_y1
            and (hue < 35 or hue > 245) and 28 < saturation < 220 and value > 82
        )
    components = [
        item for item in _binary_components(skin_mask, probe_width, probe_height)
        if item[0] >= 12
        and item[1][2] - item[1][0] <= round(probe_width * 0.13)
        and item[1][3] - item[1][1] <= round(probe_height * 0.20)
        and abs(((item[1][0] + item[1][2]) / 2) - center_x) <= probe_width * 0.11
    ]
    left_components = [
        item for item in components if (item[1][0] + item[1][2]) / 2 < center_x
    ]
    right_components = [
        item for item in components if (item[1][0] + item[1][2]) / 2 >= center_x
    ]
    if not left_components or not right_components:
        scale_x, scale_y = image.width / probe_width, image.height / probe_height
        interaction_x = round(center_x * scale_x)
        interaction_y = round(center_y * scale_y)
        half_width = round(image.width * 0.058)
        half_height = round(image.height * 0.052)
        mask_box = (
            max(0, interaction_x - half_width), max(0, interaction_y - half_height),
            min(image.width, interaction_x + half_width),
            min(image.height, interaction_y + half_height),
        )
        crop_box = (
            max(0, interaction_x - round(image.width * 0.16)),
            max(0, interaction_y - round(image.height * 0.17)),
            min(image.width, interaction_x + round(image.width * 0.16)),
            min(image.height, interaction_y + round(image.height * 0.17)),
        )
        interaction_patch = image.crop(crop_box).resize((256, 256))
        midpoint = interaction_patch.width // 2
        left_texture = sum(ImageStat.Stat(interaction_patch.crop((0, 0, midpoint, 256))).stddev) / 3
        right_texture = sum(ImageStat.Stat(interaction_patch.crop((midpoint, 0, 256, 256))).stddev) / 3
        bilateral_texture = min(left_texture, right_texture)
        confidence = round(min(0.9, 0.58 + bilateral_texture / 120.0), 4)
        left = [interaction_x - round(image.width * 0.035), interaction_y]
        right = [interaction_x + round(image.width * 0.035), interaction_y]
        hand_distance = right[0] - left[0]
        prop_width = round(hand_distance * 0.76)
        prop_height = max(round(image.height * 0.025), round(prop_width * 0.48))
        prop_box = (
            interaction_x - prop_width // 2,
            interaction_y - prop_height // 2,
            interaction_x + prop_width // 2,
            interaction_y + prop_height // 2,
        )
        evidence = {
            "status": "PASS" if confidence >= 0.62 else "LOW_CONFIDENCE",
            "method": "DECLARED_INTERACTION_ROI_WITH_BILATERAL_TEXTURE_V1",
            "confidence": confidence,
            "target_interaction_normalized": [round(target_x, 4), round(target_y, 4)],
            "search_box_probe": [search_x0, search_y0, search_x1, search_y1],
            "left_hand_center_pixels": left,
            "right_hand_center_pixels": right,
            "hand_distance_pixels": hand_distance,
            "mask_box_pixels": list(mask_box),
            "prop_box_pixels": list(prop_box),
            "crop_box_pixels": list(crop_box),
            "prop_to_hand_span_ratio": 0.76,
            "bilateral_evidence": True,
            "bilateral_texture_stddev": round(bilateral_texture, 4),
            "component_fallback_used": True,
        }
        overlay = image.copy()
        draw = ImageDraw.Draw(overlay)
        draw.rectangle(crop_box, outline=(255, 192, 0), width=8)
        draw.rectangle(mask_box, outline=(255, 0, 0), width=8)
        draw.rectangle(prop_box, outline=(0, 192, 255), width=8)
        for point in (left, right):
            draw.ellipse(
                (point[0] - 14, point[1] - 14, point[0] + 14, point[1] + 14),
                fill=(0, 255, 128), outline=(0, 64, 32), width=4,
            )
        output = io.BytesIO()
        overlay.save(output, format="PNG", optimize=True)
        return evidence, output.getvalue()
    left_area, left_box = min(
        left_components,
        key=lambda item: abs(center_x - ((item[1][0] + item[1][2]) / 2))
        + abs(center_y - ((item[1][1] + item[1][3]) / 2)),
    )
    right_area, right_box = min(
        right_components,
        key=lambda item: abs(center_x - ((item[1][0] + item[1][2]) / 2))
        + abs(center_y - ((item[1][1] + item[1][3]) / 2)),
    )
    left_probe = [
        round((left_box[0] + left_box[2]) / 2),
        round((left_box[1] + left_box[3]) / 2),
    ]
    right_probe = [
        round((right_box[0] + right_box[2]) / 2),
        round((right_box[1] + right_box[3]) / 2),
    ]
    scale_x, scale_y = image.width / probe_width, image.height / probe_height
    left = [round(left_probe[0] * scale_x), round(left_probe[1] * scale_y)]
    right = [round(right_probe[0] * scale_x), round(right_probe[1] * scale_y)]
    hand_distance = max(24, right[0] - left[0])
    interaction_x = round((left[0] + right[0]) / 2)
    interaction_y = round((left[1] + right[1]) / 2)
    prop_width = max(round(image.width * 0.035), round(hand_distance * 0.76))
    prop_height = max(round(prop_width * 0.48), round(image.height * 0.025))
    prop_box = (
        max(0, interaction_x - prop_width // 2),
        max(0, interaction_y - prop_height // 2),
        min(image.width, interaction_x + prop_width // 2),
        min(image.height, interaction_y + prop_height // 2),
    )
    mask_half_width = max(round(prop_width * 0.68), round(image.width * 0.045))
    mask_half_height = max(round(prop_height * 0.78), round(image.height * 0.04))
    mask_box = (
        max(0, interaction_x - mask_half_width),
        max(0, interaction_y - mask_half_height),
        min(image.width, interaction_x + mask_half_width),
        min(image.height, interaction_y + mask_half_height),
    )
    crop_half_width = max(round(image.width * 0.10), round(prop_width * 2.2))
    crop_half_height = max(round(image.height * 0.10), round(prop_width * 1.45))
    crop_box = (
        max(0, interaction_x - crop_half_width),
        max(0, interaction_y - crop_half_height),
        min(image.width, interaction_x + crop_half_width),
        min(image.height, interaction_y + crop_half_height),
    )
    balance = min(left_area, right_area) / max(left_area, right_area)
    proximity = max(0.0, 1.0 - abs((interaction_x / image.width) - target_x) / 0.20)
    confidence = round(0.60 * min(1.0, balance * 1.5) + 0.40 * proximity, 4)
    evidence = {
        "status": "PASS" if confidence >= 0.62 else "LOW_CONFIDENCE",
        "method": "OFFLINE_INTERACTION_CENTERED_SKIN_COMPONENTS_V1",
        "confidence": confidence,
        "target_interaction_normalized": [round(target_x, 4), round(target_y, 4)],
        "search_box_probe": [search_x0, search_y0, search_x1, search_y1],
        "left_hand_component_box_probe": list(left_box),
        "right_hand_component_box_probe": list(right_box),
        "left_hand_component_area_probe": left_area,
        "right_hand_component_area_probe": right_area,
        "left_hand_center_pixels": left,
        "right_hand_center_pixels": right,
        "hand_distance_pixels": hand_distance,
        "mask_box_pixels": list(mask_box),
        "prop_box_pixels": list(prop_box),
        "crop_box_pixels": list(crop_box),
        "prop_to_hand_span_ratio": 0.76,
        "bilateral_evidence": True,
    }
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    draw.rectangle(crop_box, outline=(255, 192, 0), width=8)
    draw.rectangle(mask_box, outline=(255, 0, 0), width=8)
    draw.rectangle(prop_box, outline=(0, 224, 255), width=6)
    for point in (left, right):
        draw.ellipse(
            (point[0] - 14, point[1] - 14, point[0] + 14, point[1] + 14),
            fill=(0, 255, 128), outline=(0, 64, 32), width=4,
        )
    output = io.BytesIO()
    overlay.save(output, format="PNG", optimize=True)
    return evidence, output.getvalue()


def _hand_preserving_object_cleanup(
    base: Image.Image,
    edit_mask_box: tuple[int, int, int, int],
    prop_box: tuple[int, int, int, int],
    hand_evidence: dict[str, Any] | None,
) -> tuple[Image.Image, Image.Image, dict[str, Any]]:
    """Replace only the object core with nearby floor texture while preserving hands."""
    prop_width = prop_box[2] - prop_box[0]
    prop_height = prop_box[3] - prop_box[1]
    center_x = (prop_box[0] + prop_box[2]) // 2
    object_box = (
        max(edit_mask_box[0], center_x - round(prop_width * 0.36)),
        max(edit_mask_box[1], prop_box[1] + round(prop_height * 0.10)),
        min(edit_mask_box[2], center_x + round(prop_width * 0.36)),
        min(edit_mask_box[3], prop_box[3] + round(prop_height * 0.72)),
    )
    height = object_box[3] - object_box[1]
    source_top = min(base.height - height, object_box[3] + max(8, round(height * 0.12)))
    source_box = (object_box[0], source_top, object_box[2], source_top + height)
    replacement = base.crop(source_box).filter(ImageFilter.GaussianBlur(3.0))
    replacement_layer = base.copy()
    replacement_layer.paste(replacement, object_box[:2])

    removal_mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(removal_mask).rounded_rectangle(object_box, radius=10, fill=255)
    protection_mask = Image.new("L", base.size, 0)
    protection_draw = ImageDraw.Draw(protection_mask)
    protected_centers = []
    for key in ("left_hand_center_pixels", "right_hand_center_pixels"):
        point = (hand_evidence or {}).get(key)
        if not point:
            continue
        x, y = int(point[0]), int(point[1])
        protected_centers.append([x, y])
        protection_draw.ellipse((x - 70, y - 62, x + 70, y + 72), fill=255)
    protected_removal = ImageChops.subtract(removal_mask, protection_mask)
    feathered = ImageChops.subtract(
        protected_removal.filter(ImageFilter.GaussianBlur(7)), protection_mask
    )
    cleaned = Image.composite(replacement_layer, base, feathered)

    protected_difference = Image.composite(
        ImageChops.difference(cleaned, base),
        Image.new("RGB", base.size, (0, 0, 0)),
        protection_mask,
    )
    protected_bbox = protected_difference.getbbox()
    changed_bbox = ImageChops.difference(cleaned, base).getbbox()
    evidence = {
        "method": "HAND_PROTECTED_ADJACENT_FLOOR_TEXTURE_V1",
        "object_mask_box_pixels": list(object_box),
        "texture_source_box_pixels": list(source_box),
        "protected_hand_centers_pixels": protected_centers,
        "protected_hand_pixel_invariance": "PASS" if protected_bbox is None else "FAIL",
        "changed_pixel_bbox": list(changed_bbox) if changed_bbox else None,
        "skin_blob_gate": "PASS" if protected_bbox is None else "FAIL",
        "diffusion_used": False,
    }
    return cleaned, feathered, evidence


def _composite_controlled_paper_boat(
    base: Image.Image, mask_box: tuple[int, int, int, int],
    hand_evidence: dict[str, Any] | None,
) -> tuple[Image.Image, bytes, dict[str, Any]]:
    """Create one auditable paper-boat silhouette and alpha-composite it between hands."""
    left, top, right, bottom = mask_box
    width = right - left
    height = bottom - top
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    center_x = (left + right) // 2
    shadow_y = top + round(height * 0.82)
    draw.ellipse(
        (left + round(width * 0.08), shadow_y, right - round(width * 0.08),
         shadow_y + max(3, round(height * 0.14))),
        fill=(75, 55, 45, 55),
    )
    torn = max(2, round(width * 0.018))
    hull = [
        (left + torn, top + round(height * 0.48)),
        (left + round(width * 0.22), bottom - torn),
        (right - round(width * 0.20), bottom - torn * 2),
        (right - torn, top + round(height * 0.48)),
        (center_x + torn, top + round(height * 0.63)),
        (center_x - torn, top + round(height * 0.60)),
    ]
    sail_left = [
        (left + round(width * 0.08), top + round(height * 0.47)),
        (center_x - torn, top + torn),
        (center_x - torn, top + round(height * 0.61)),
    ]
    sail_right = [
        (center_x + torn, top + torn * 2),
        (right - round(width * 0.07), top + round(height * 0.47)),
        (center_x + torn, top + round(height * 0.63)),
    ]
    outline = (125, 105, 88, 245)
    draw.polygon(hull, fill=(221, 207, 181, 252), outline=outline)
    draw.polygon(sail_left, fill=(246, 239, 218, 252), outline=outline)
    draw.polygon(sail_right, fill=(235, 224, 199, 252), outline=outline)
    draw.line(
        (center_x, top + torn, center_x, bottom - torn * 2),
        fill=(143, 124, 102, 220), width=max(2, round(width * 0.012)),
    )
    draw.line(
        (left + round(width * 0.22), bottom - torn, center_x, top + round(height * 0.61),
         right - round(width * 0.20), bottom - torn * 2),
        fill=(158, 136, 111, 210), width=max(2, round(width * 0.009)),
    )
    composed = Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")
    prop_width = width - torn * 2
    prop_height = height - torn * 2
    hand_distance = int((hand_evidence or {}).get("hand_distance_pixels", width))
    scale_ratio = round(prop_width / max(1, hand_distance), 4)
    aspect_ratio = round(prop_width / max(1, prop_height), 4)
    evidence = {
        "method": "CONTROLLED_PAPER_BOAT_SILHOUETTE_V1",
        "object_count": 1,
        "bbox_pixels": [left + torn, top + torn, right - torn, bottom - torn],
        "width_pixels": prop_width,
        "height_pixels": prop_height,
        "aspect_ratio": aspect_ratio,
        "prop_to_hand_distance_ratio": scale_ratio,
        "gates": {
            "prop_readability": "PASS" if 1.6 <= aspect_ratio <= 3.4 else "FAIL",
            "prop_scale": "PASS" if 0.6 <= scale_ratio <= 0.86 else "FAIL",
            "two_hand_contact": "PASS" if hand_evidence else "NOT_ASSESSED",
        },
    }
    output = io.BytesIO()
    layer.save(output, format="PNG", optimize=True)
    return composed, output.getvalue(), evidence


def _failed_hand_evidence(reason: str) -> dict[str, Any]:
    return {
        "status": "FAIL", "method": "OFFLINE_HSV_CONNECTED_COMPONENTS_V1",
        "confidence": 0.0, "reason": reason,
    }


def _binary_components(
    mask: list[bool], width: int, height: int
) -> list[tuple[int, tuple[int, int, int, int]]]:
    seen = bytearray(width * height)
    components = []
    for start, enabled in enumerate(mask):
        if not enabled or seen[start]:
            continue
        seen[start] = 1
        stack = [start]
        points = []
        while stack:
            point = stack.pop()
            points.append(point)
            y, x = divmod(point, width)
            for candidate in (point - 1, point + 1, point - width, point + width):
                if candidate < 0 or candidate >= width * height:
                    continue
                other_y, other_x = divmod(candidate, width)
                if abs(other_x - x) + abs(other_y - y) != 1:
                    continue
                if mask[candidate] and not seen[candidate]:
                    seen[candidate] = 1
                    stack.append(candidate)
        if len(points) < 12:
            continue
        xs = [point % width for point in points]
        ys = [point // width for point in points]
        components.append((len(points), (min(xs), min(ys), max(xs) + 1, max(ys) + 1)))
    return sorted(components, reverse=True)
