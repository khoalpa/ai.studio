from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw, ImageStat

from ai_story.errors import ArtifactError, RuntimeCapabilityError
from ai_story.image_candidates import candidate_score
from ai_story.image_qa import ImageQualityError, LocalImageQualityAssessor
from ai_story.runtime.base import RuntimeCapabilities
from ai_story.runtime.diffusers_runtime import DiffusersRuntime
from ai_story.stage1.local_providers import LocalCharacterImageProvider
from ai_story.stage2.control import ControlMap, composition_canvas
from ai_story.stage2.providers import (
    LocalLandscapeProvider,
    _composite_controlled_paper_boat,
    _hand_preserving_object_cleanup,
    _locate_hands,
    _locate_interaction_hands,
)
from ai_story.stage3.providers import LocalPortraitProvider, _portrait_canvas


def gradient_png(width: int, height: int) -> bytes:
    image = Image.new("RGB", (2, 2))
    image.putdata([(0, 0, 96), (255, 0, 96), (0, 255, 96), (255, 255, 96)])
    image = image.resize((width, height), Image.Resampling.BILINEAR)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class FakeImageRegistry:
    def __init__(self) -> None:
        self.calls = []
        self.config = {
            "runtimes": {
                "diffusers": {
                    "landscape_work_size": [1024, 576],
                    "portrait_work_size": [704, 1216],
                    "portrait_strength": 0.38,
                }
            }
        }

    def binding(self, role):
        return {"model_id": "fake-diffusion"}

    def generate_image(self, role, request, cancellation=None):
        self.calls.append((role, request))
        return gradient_png(
            request.parameters["output_width"], request.parameters["output_height"]
        )


class FakeAssessor:
    def __init__(self) -> None:
        self.calls = []

    def assess(self, data, **kwargs):
        self.calls.append((data, kwargs))
        return {
            "status": "ASSESSED_PASS",
            "method": "TECHNICAL_OCR_CLIP",
            "semantic_score": 0.8,
            "parity_score": 0.9 if kwargs.get("reference") else None,
        }

    def assess_character_identity(self, data, *, character):
        self.calls.append((data, {"character": character, "semantic_character": True}))
        return {
            "status": "ASSESSED_PASS",
            "method": "CLIP_CONTRASTIVE_CHARACTER_QA",
            "character_id": character["character_id"],
            "checks": [{"check": "person_count", "status": "PASS"}],
            "findings": [],
        }


class LocalImageProviderTests(unittest.TestCase):
    def test_layered_qa_reports_semantic_and_missing_elements_together(self) -> None:
        class ProbeAssessor(LocalImageQualityAssessor):
            def _clip_similarity(self, image, *, prompt=None, reference=None):
                return 0.1

        assessor = ProbeAssessor({
            "ocr_enabled": False, "require_semantic": True,
            "minimum_variance": 1, "semantic_threshold": 0.22,
            "element_threshold": 0.16,
        })
        with self.assertRaises(ImageQualityError) as raised:
            assessor.assess(
                gradient_png(64, 64), prompt="boy helps injured bird on beach",
                expected_dimensions=(64, 64),
                required_elements=["prop:injured seabird", "prop:beach"],
            )
        codes = [item["error"] for item in raised.exception.assessment["findings"]]
        self.assertEqual(codes, ["SEMANTIC_MISMATCH", "REQUIRED_ELEMENT_MISSING"])
        self.assertEqual(
            raised.exception.assessment["structured_visual_qa"]["status"], "FAIL"
        )

    def test_candidate_score_rewards_clearance_above_hard_gates(self) -> None:
        base = {
            "status": "ASSESSED_PASS",
            "applied_thresholds": {"semantic_threshold": 0.22},
            "identity_similarity_scores": [0.56],
            "qa_layers": [{
                "layer": "IDENTITY", "checks": {"threshold": 0.55},
            }],
        }
        narrow = {**base, "semantic_score": 0.221}
        robust = {**base, "semantic_score": 0.29}
        self.assertGreater(candidate_score(robust), candidate_score(narrow))

    def test_composition_canvas_places_reference_at_shot_coordinates(self) -> None:
        reference = gradient_png(80, 160)
        canvas = composition_canvas(
            {
                "subjects": [{
                    "character_id": "an", "position": {"x": 0.25, "y": 0.75},
                    "scale": "medium_full",
                }],
                "prop_layout": [{"name": "boat", "position": {"x": 0.7, "y": 0.8}}],
            },
            [{"character_id": "an", "data": reference}],
            (400, 240),
        )
        self.assertEqual(canvas.size, (400, 240))
        self.assertGreater(sum(ImageStat.Stat(canvas).stddev), 10)

    def test_pose_aware_canvas_uses_small_prop_and_articulated_guide(self) -> None:
        reference = gradient_png(160, 160)
        canvas = composition_canvas(
            {
                "pose_aware_scene_conditioning": True,
                "subjects": [{
                    "character_id": "bo", "position": {"x": 0.5, "y": 0.75},
                    "scale": "medium_full", "pose": "seated story-action pose",
                    "interaction_target": {"x": 0.55, "y": 0.62},
                }],
                "prop_layout": [{
                    "name": "paper boat", "position": {"x": 0.55, "y": 0.62},
                    "relative_width": 0.035,
                }],
            },
            [{"character_id": "bo", "view_id": "face_closeup", "data": reference}],
            (400, 240),
        )
        self.assertEqual(canvas.size, (400, 240))
        self.assertGreater(sum(ImageStat.Stat(canvas).stddev), 10)

    def test_prop_free_latent_canvas_ignores_prop_geometry(self) -> None:
        base = {
            "latent_props_disabled": True,
            "subjects": [],
            "prop_layout": [{
                "name": "paper boat", "position": {"x": 0.5, "y": 0.7},
                "relative_width": 0.5,
            }],
        }
        with_prop = composition_canvas(base, [], (400, 240))
        without_prop = composition_canvas({**base, "prop_layout": []}, [], (400, 240))
        self.assertEqual(with_prop.tobytes(), without_prop.tobytes())

    def test_masked_prop_edit_preserves_every_pixel_outside_effective_mask(self) -> None:
        registry = FakeImageRegistry()
        provider = LocalLandscapeProvider(registry, FakeAssessor())
        base = gradient_png(400, 240)
        result, mask_data, evidence, _ = provider._masked_prop_edit(
            basename="cover.png", attempt=1, base_data=base,
            edit={
                "base_prompt": "boy with empty cupped hands",
                "prompt": "insert one tiny paper boat only",
                "crop_box": [0.3, 0.3, 0.7, 0.8],
                "mask_box": [0.46, 0.55, 0.54, 0.68],
                "feather_pixels": 8, "strength": 0.5,
            },
            negative_prompt="large boat", seed=7,
        )
        source = Image.open(io.BytesIO(base)).convert("RGB")
        edited = Image.open(io.BytesIO(result)).convert("RGB")
        mask = Image.open(io.BytesIO(mask_data)).convert("L")
        outside = ImageChops.difference(source, edited)
        outside.paste((0, 0, 0), mask=mask.point(lambda value: 255 if value else 0))
        self.assertIsNone(outside.getbbox())
        self.assertEqual(evidence["outside_hard_mask_pixel_invariance"], "PASS")
        self.assertEqual(len(registry.calls), 1)

    def test_hand_localizer_builds_dynamic_mask_between_cupped_hands(self) -> None:
        image = Image.new("RGB", (800, 450), (232, 220, 205))
        draw = ImageDraw.Draw(image)
        draw.ellipse((350, 80, 450, 190), fill=(224, 168, 132))
        draw.rectangle((355, 70, 445, 115), fill=(38, 28, 24))
        draw.ellipse((372, 220, 410, 250), fill=(224, 168, 132))
        draw.ellipse((410, 220, 448, 250), fill=(224, 168, 132))
        evidence, overlay = _locate_hands(image)
        self.assertEqual(evidence["status"], "PASS")
        self.assertGreaterEqual(evidence["confidence"], 0.62)
        self.assertLess(evidence["mask_box_pixels"][0], 410)
        self.assertGreater(evidence["mask_box_pixels"][2], 410)
        self.assertEqual(Image.open(io.BytesIO(overlay)).size, image.size)

    def test_hand_localizer_targets_requested_subject_in_two_person_scene(self) -> None:
        image = Image.new("RGB", (1000, 560), (232, 220, 205))
        draw = ImageDraw.Draw(image)
        for center_x in (350, 680):
            draw.ellipse((center_x - 55, 80, center_x + 55, 200), fill=(224, 168, 132))
            draw.rectangle((center_x - 50, 70, center_x + 50, 120), fill=(38, 28, 24))
            draw.ellipse((center_x - 35, 240, center_x, 272), fill=(224, 168, 132))
            draw.ellipse((center_x, 240, center_x + 35, 272), fill=(224, 168, 132))

        left, _ = _locate_hands(image, target_subject_x=0.35)
        right, _ = _locate_hands(image, target_subject_x=0.68)

        self.assertEqual(left["status"], "PASS")
        self.assertEqual(right["status"], "PASS")
        self.assertLess(left["mask_box_pixels"][0], 500)
        self.assertGreater(right["mask_box_pixels"][0], 500)

    def test_controlled_prop_has_readable_scale_and_contact_gates(self) -> None:
        base = Image.new("RGB", (800, 450), (80, 100, 120))
        composed, layer, evidence = _composite_controlled_paper_boat(
            base, (340, 190, 460, 248), {"hand_distance_pixels": 164}
        )
        self.assertEqual(composed.size, base.size)
        self.assertEqual(Image.open(io.BytesIO(layer)).mode, "RGBA")
        self.assertEqual(evidence["object_count"], 1)
        self.assertEqual(set(evidence["gates"].values()), {"PASS"})

    def test_two_pass_prop_composite_uses_cleaned_base(self) -> None:
        base = Image.new("RGB", (800, 450), (80, 100, 120))
        cleaned = base.copy()
        ImageDraw.Draw(cleaned).rectangle((340, 180, 460, 260), fill=(120, 130, 140))
        composed, _, evidence = _composite_controlled_paper_boat(
            cleaned, (360, 195, 440, 235), {"hand_distance_pixels": 108}
        )
        self.assertEqual(composed.getpixel((350, 220)), (120, 130, 140))
        self.assertNotEqual(composed.getpixel((400, 215)), cleaned.getpixel((400, 215)))
        self.assertEqual(set(evidence["gates"].values()), {"PASS"})

    def test_neutralized_object_mask_is_tighter_than_edit_mask(self) -> None:
        edit_mask = (1697, 1130, 2143, 1354)
        prop_box = (1818, 1193, 2022, 1291)
        prop_width = prop_box[2] - prop_box[0]
        prop_height = prop_box[3] - prop_box[1]
        center_x = (prop_box[0] + prop_box[2]) // 2
        object_mask = (
            max(edit_mask[0], center_x - round(prop_width * 0.58)),
            max(edit_mask[1], prop_box[1] + round(prop_height * 0.08)),
            min(edit_mask[2], center_x + round(prop_width * 0.58)),
            min(edit_mask[3], prop_box[3] + round(prop_height * 0.72)),
        )
        self.assertLess(object_mask[2] - object_mask[0], edit_mask[2] - edit_mask[0])
        self.assertLessEqual(object_mask[3], edit_mask[3])
        self.assertGreater(object_mask[3], prop_box[3])

    def test_deterministic_cleanup_preserves_hand_centers(self) -> None:
        base = Image.new("RGB", (800, 450), (210, 190, 165))
        draw = ImageDraw.Draw(base)
        draw.rectangle((370, 220, 430, 300), fill=(40, 90, 150))
        evidence = {
            "left_hand_center_pixels": [350, 240],
            "right_hand_center_pixels": [450, 240],
        }
        cleaned, mask, cleanup = _hand_preserving_object_cleanup(
            base, (320, 180, 480, 320), (350, 205, 450, 255), evidence
        )
        self.assertEqual(cleaned.getpixel((350, 240)), base.getpixel((350, 240)))
        self.assertEqual(cleaned.getpixel((450, 240)), base.getpixel((450, 240)))
        self.assertEqual(cleanup["protected_hand_pixel_invariance"], "PASS")
        self.assertEqual(cleanup["diffusion_used"], False)
        self.assertEqual(mask.size, base.size)

    def test_interaction_localizer_requires_bilateral_hand_evidence(self) -> None:
        image = Image.new("RGB", (1000, 560), (220, 210, 195))
        draw = ImageDraw.Draw(image)
        draw.ellipse((430, 300, 475, 340), fill=(224, 168, 132))
        draw.ellipse((525, 302, 570, 342), fill=(224, 168, 132))

        evidence, overlay = _locate_interaction_hands(
            image, target_x=0.5, target_y=0.58
        )

        self.assertEqual(evidence["status"], "PASS")
        self.assertTrue(evidence["bilateral_evidence"])
        self.assertLess(evidence["left_hand_center_pixels"][0], 500)
        self.assertGreater(evidence["right_hand_center_pixels"][0], 500)
        self.assertLess(
            evidence["prop_box_pixels"][2] - evidence["prop_box_pixels"][0],
            evidence["mask_box_pixels"][2] - evidence["mask_box_pixels"][0],
        )
        _, _, prop_evidence = _composite_controlled_paper_boat(
            image, tuple(evidence["prop_box_pixels"]), evidence
        )
        self.assertEqual(set(prop_evidence["gates"].values()), {"PASS"})
        self.assertEqual(Image.open(io.BytesIO(overlay)).size, image.size)

    def test_learned_upscale_runs_before_bounded_postprocess(self) -> None:
        class Upscaler:
            def __call__(self, **kwargs):
                class Result:
                    images = [kwargs["image"].resize((128, 128), Image.Resampling.NEAREST)]
                return Result()

        runtime = DiffusersRuntime({
            "model_id": "unused",
            "upscaler": {
                "enabled": True, "model": "test/x2", "steps": 4,
                "guidance_scale": 1.0, "sharpen_percent": 100,
                "sharpen_radius": 1.0, "sharpen_threshold": 3,
                "contrast": 1.0, "color": 1.0,
            },
        })
        with patch.object(runtime, "_load_upscaler", return_value=Upscaler()):
            result = runtime._upscale_and_finish(
                Image.new("RGB", (64, 64), (20, 40, 60)),
                (120, 120), prompt="scene", negative_prompt=None, generator=object(),
            )
        self.assertEqual(result.size, (120, 120))
        self.assertEqual(runtime.last_image_metadata["mode"], "LATENT_X2_PLUS_RESIDUAL")
        self.assertEqual(runtime.last_image_metadata["learned_size"], [128, 128])
        self.assertTrue(runtime.last_image_metadata["residual_resize"])

    def test_disabled_upscaler_records_explicit_fallback(self) -> None:
        runtime = DiffusersRuntime({"model_id": "unused", "upscaler": {"enabled": False}})
        result = runtime._upscale_and_finish(
            Image.new("RGB", (32, 32), (30, 50, 70)),
            (64, 64), prompt="scene", negative_prompt=None, generator=object(),
        )
        self.assertEqual(result.size, (64, 64))
        self.assertEqual(runtime.last_image_metadata["mode"], "LANCZOS_FALLBACK")

    def test_reference_canvas_uses_stable_square_cells(self) -> None:
        images = [
            Image.new("RGB", (200, 400), (255, 0, 0)),
            Image.new("RGB", (400, 200), (0, 255, 0)),
            Image.new("RGB", (300, 300), (0, 0, 255)),
        ]
        canvas = DiffusersRuntime._reference_canvas(images, cell_size=100, padding=10)
        self.assertEqual(canvas.size, (230, 230))
        self.assertEqual(canvas.getpixel((60, 60)), (255, 0, 0))
        self.assertEqual(canvas.getpixel((170, 60)), (0, 255, 0))

    def test_character_retry_prompt_applies_previous_semantic_qa_findings(self) -> None:
        class RejectingAssessor(FakeAssessor):
            def assess_character_identity(self, data, *, character):
                return {
                    "status": "ASSESSED_FAIL",
                    "findings": [
                        {"error": "CHARACTER_PERSON_COUNT_MISMATCH"},
                        {"error": "CHARACTER_PRESENTATION_MISMATCH"},
                        {"error": "CHARACTER_FRAMING_MISMATCH"},
                        {"error": "CHARACTER_AGE_BAND_MISMATCH"},
                    ],
                }

        registry = FakeImageRegistry()
        registry.config["runtimes"]["diffusers"]["character_work_size"] = [768, 1024]
        provider = LocalCharacterImageProvider(registry, RejectingAssessor())
        provider.configure_cast({"characters": [
            {
                "character_id": "ha", "name": "Ha", "canonical_age_min": 10,
                "visual_identity": {"presentation": "FEMININE", "hair": "long hair"},
            },
            {
                "character_id": "nam", "name": "Nam", "canonical_age_min": 10,
                "visual_identity": {"presentation": "MASCULINE", "hair": "short hair"},
            },
        ]})
        character = {
            "character_id": "nam", "name": "Nam", "role": "nhân vật chính",
            "canonical_age_min": 10, "identity_traits": ["tóc đen", "áo xanh"],
            "visual_identity": {"presentation": "MASCULINE"},
        }

        with self.assertRaises(ArtifactError):
            provider.generate_attempt(character, 1)
        with self.assertRaises(ArtifactError):
            provider.generate_attempt(character, 2)

        retry_prompt = registry.calls[1][1].prompt
        self.assertTrue(
            registry.calls[1][1].parameters["fit_prompt_to_token_budget"]
        )
        self.assertIn("RETRY 2 FIX", retry_prompt)
        self.assertIn("one person, no duplicates", retry_prompt)
        self.assertIn("unmistakably boy", retry_prompt)
        self.assertIn("entire head and both shoes visible", retry_prompt)
        self.assertIn("10-year-old child with child facial features", retry_prompt)
        self.assertLess(
            retry_prompt.index("Entire head and both shoes visible"),
            retry_prompt.index("ART_DIRECTION_ID"),
        )
        first_window = " ".join(retry_prompt.split()[:77])
        self.assertIn("both shoes", first_window)
        self.assertIn("boy", first_window)
        self.assertNotIn("CAST_BIBLE", retry_prompt)
        self.assertNotIn("Render only this target character: Ha", retry_prompt)

    def test_character_retry_encodes_visible_older_adult_age_cues(self) -> None:
        class AgeRejectingAssessor(FakeAssessor):
            def assess_character_identity(self, data, *, character):
                return {
                    "status": "ASSESSED_FAIL",
                    "findings": [{"error": "CHARACTER_AGE_BAND_MISMATCH"}],
                }

        registry = FakeImageRegistry()
        registry.config["runtimes"]["diffusers"]["character_work_size"] = [768, 1024]
        provider = LocalCharacterImageProvider(registry, AgeRejectingAssessor())
        character = {
            "character_id": "ong_hung", "name": "Ông Hùng", "role": "caretaker",
            "canonical_age_min": 65, "identity_traits": ["kind face", "gray hair"],
            "visual_identity": {"presentation": "MASCULINE"},
        }

        with self.assertRaises(ArtifactError):
            provider.generate_attempt(character, 1)
        with self.assertRaises(ArtifactError):
            provider.generate_attempt(character, 2)

        retry_prompt = registry.calls[1][1].prompt
        first_prompt = registry.calls[0][1].prompt
        self.assertIn("older adult facial structure", first_prompt)
        self.assertIn("visible age lines", first_prompt)
        self.assertIn("older adult aged 65", retry_prompt)
        self.assertIn("visible age lines", retry_prompt)
        self.assertIn("naturally graying hair", retry_prompt)
        self.assertIn("not a child or teenager", retry_prompt)

    def test_character_retry_uses_technical_ocr_failure_as_repair_input(self) -> None:
        class OcrRejectingAssessor(FakeAssessor):
            def assess(self, data, **kwargs):
                raise ImageQualityError(
                    "Image QA detected unwanted text: pseudo",
                    {
                        "status": "ASSESSED_FAIL",
                        "findings": [{"error": "UNWANTED_TEXT", "layer": "OCR_SAFETY"}],
                        "qa_layers": [],
                    },
                )

        registry = FakeImageRegistry()
        registry.config["runtimes"]["diffusers"]["character_work_size"] = [768, 1024]
        provider = LocalCharacterImageProvider(registry, OcrRejectingAssessor())
        character = {
            "character_id": "minh", "name": "Minh", "role": "elder sister",
            "canonical_age_min": 10, "identity_traits": ["careful"],
            "visual_identity": {"presentation": "FEMININE"},
        }

        with self.assertRaisesRegex(ArtifactError, "unwanted text"):
            provider.generate_attempt(character, 1)
        with self.assertRaises(ArtifactError):
            provider.generate_attempt(character, 2)

        retry_prompt = registry.calls[1][1].prompt
        self.assertIn("RETRY 2 FIX", retry_prompt)
        self.assertIn("no text, letters, signs, logos, or marks", retry_prompt)

    def test_character_retry_corrects_overexposed_luminance(self) -> None:
        class LuminanceRejectingAssessor(FakeAssessor):
            def assess(self, data, **kwargs):
                raise ImageQualityError(
                    "Image QA rejected out-of-band luminance",
                    {
                        "status": "ASSESSED_FAIL",
                        "findings": [{
                            "error": "LUMINANCE_OUT_OF_BAND",
                            "layer": "TECHNICAL",
                            "mean_luma": 252.0,
                            "expected_band": [5, 250],
                        }],
                        "qa_layers": [],
                    },
                )

        registry = FakeImageRegistry()
        registry.config["runtimes"]["diffusers"]["character_work_size"] = [768, 1024]
        provider = LocalCharacterImageProvider(registry, LuminanceRejectingAssessor())
        character = {
            "character_id": "nam", "name": "Nam", "role": "main character",
            "canonical_age_min": 10, "identity_traits": ["black hair"],
            "visual_identity": {"presentation": "MASCULINE"},
        }

        with self.assertRaises(ArtifactError):
            provider.generate_attempt(character, 1)
        with self.assertRaises(ArtifactError):
            provider.generate_attempt(character, 2)

        retry_prompt = registry.calls[1][1].prompt
        self.assertIn("RETRY 2 FIX", retry_prompt)
        self.assertIn("reduce exposure", retry_prompt)
        self.assertIn("mid-tone beige studio backdrop", retry_prompt)

    def test_portrait_crop_avoids_empty_center_when_subject_is_off_center(self) -> None:
        image = Image.new("RGB", (1600, 900), (128, 128, 128))
        for x in range(1100, 1500):
            for y in range(100, 800):
                image.putpixel((x, y), ((x + y) % 256, x % 256, y % 256))

        crop = DiffusersRuntime._portrait_crop(image)

        self.assertEqual(crop.size, (506, 900))
        self.assertGreater(crop.getbbox()[2], 0)
        self.assertGreater(sum(ImageStat.Stat(crop).stddev), 30)

    def test_character_reference_uses_diffusion_and_pixel_digest(self) -> None:
        registry = FakeImageRegistry()
        registry.config["runtimes"]["diffusers"]["character_work_size"] = [768, 1024]
        assessor = FakeAssessor()
        provider = LocalCharacterImageProvider(registry, assessor)
        data, pixel_digest = provider.generate(
            {
                "character_id": "an",
                "name": "An",
                "role": "nhân vật chính",
                "canonical_age_min": 12,
                "identity_traits": ["tóc đen", "áo xanh"],
            }
        )
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(len(pixel_digest), 64)
        self.assertEqual(registry.calls[0][0], "character_image")
        self.assertEqual(provider.assessment("an")["status"], "ASSESSED_PASS")

    def test_character_semantic_qa_rejects_group_scene_and_wrong_age(self) -> None:
        class ProbeAssessor(LocalImageQualityAssessor):
            def _clip_similarity(self, image, *, prompt=None, reference=None):
                scores = {
                    "one person": 0.2, "multiple people": 0.8, "no person": 0.1,
                    "child": 0.2, "teenager": 0.1, "adult": 0.8,
                    "a girl": 0.8, "a boy": 0.1, "an androgynous child": 0.2,
                    "one centered person visible from head to toe on a plain studio background": 0.2,
                    "a close-up or waist-up portrait with the body cropped": 0.3,
                    "an environmental story scene with scenery": 0.8,
                }
                return scores.get(prompt, 0.9)

        assessor = ProbeAssessor({"character_attribute_threshold": 0.16})
        result = assessor.assess_character_identity(
            gradient_png(64, 64),
            character={
                "character_id": "ha", "canonical_age_min": 10,
                "visual_identity": {
                    "presentation": "FEMININE", "hair": "tóc đen dài",
                    "wardrobe": "áo trắng", "silhouette": "bé gái nhỏ nhắn",
                    "cultural_context": "Việt Nam",
                },
            },
        )

        self.assertEqual(result["status"], "ASSESSED_FAIL")
        errors = {item["error"] for item in result["findings"]}
        self.assertIn("CHARACTER_PERSON_COUNT_MISMATCH", errors)
        self.assertIn("CHARACTER_AGE_BAND_MISMATCH", errors)
        self.assertIn("CHARACTER_FRAMING_MISMATCH", errors)

    def test_character_semantic_qa_accepts_ambiguous_clip_scores(self) -> None:
        class ProbeAssessor(LocalImageQualityAssessor):
            def _clip_similarity(self, image, *, prompt=None, reference=None):
                scores = {
                    "one person": 0.40, "multiple people": 0.41, "no person": 0.2,
                    "child": 0.40, "teenager": 0.42, "adult": 0.2,
                    "a girl": 0.3, "a boy": 0.4, "an androgynous child": 0.2,
                    "one centered person visible from head to toe on a plain studio background": 0.40,
                    "a close-up or waist-up portrait with the body cropped": 0.42,
                    "an environmental story scene with scenery": 0.2,
                }
                return scores.get(prompt, 0.9)

        assessor = ProbeAssessor({"character_contrastive_tolerance": 0.03})
        result = assessor.assess_character_identity(
            gradient_png(64, 64),
            character={
                "character_id": "minh", "canonical_age_min": 10,
                "visual_identity": {"presentation": "UNSPECIFIED"},
            },
        )

        self.assertEqual(result["status"], "ASSESSED_PASS")
        presentation = next(
            item for item in result["checks"] if item["check"] == "presentation"
        )
        self.assertEqual(presentation["status"], "NOT_APPLICABLE")

    def test_character_semantic_qa_still_rejects_clear_contrastive_mismatch(self) -> None:
        class ProbeAssessor(LocalImageQualityAssessor):
            def _clip_similarity(self, image, *, prompt=None, reference=None):
                scores = {
                    "one person": 0.2, "multiple people": 0.8, "no person": 0.1,
                    "child": 0.2, "teenager": 0.1, "adult": 0.8,
                    "a girl": 0.2, "a boy": 0.8, "an androgynous child": 0.1,
                    "one centered person visible from head to toe on a plain studio background": 0.2,
                    "a close-up or waist-up portrait with the body cropped": 0.8,
                    "an environmental story scene with scenery": 0.1,
                }
                return scores.get(prompt, 0.9)

        assessor = ProbeAssessor({"character_contrastive_tolerance": 0.03})
        result = assessor.assess_character_identity(
            gradient_png(64, 64),
            character={
                "character_id": "minh", "canonical_age_min": 10,
                "visual_identity": {"presentation": "FEMININE"},
            },
        )

        self.assertEqual(result["status"], "ASSESSED_FAIL")
        self.assertGreaterEqual(len(result["findings"]), 3)

    def test_landscape_generation_binds_prompt_seed_references_and_qa(self) -> None:
        registry = FakeImageRegistry()
        assessor = FakeAssessor()
        provider = LocalLandscapeProvider(registry, assessor)
        data = provider.generate(
            basename="opening.png",
            story={"meta": {"title": "Sau Mưa"}},
            visual_plan_asset={
                "visual_moment": "An bước vào vườn",
                "state_delta_to_show": "cánh cổng mở",
                "focal_character_ids": ["an"],
                "shot_spec": {
                    "action": "An mở cánh cổng", "emotion": "tò mò", "location": "khu vườn",
                    "props": ["paper boat"], "required_elements": ["character:an", "prop:paper boat"],
                    "forbidden_elements": ["uncontrolled_text"],
                    "composition": {"framing": "medium shot"},
                },
            },
            visual_bible={
                "art_direction_id": "cinematic_storybook_v1",
                "tonal_plan": {"palette": ["deep_blue", "warm_amber"]},
                "character_identity_locks": [
                    {
                        "character_id": "an",
                        "name": "An",
                        "canonical_age_range": [12, 12],
                        "identity_traits": ["tóc đen", "áo xanh"],
                    }
                ],
            },
            attempt=1,
            reference_inputs=[{
                "reference_id": "an:full_body_front", "character_id": "an",
                "view_id": "full_body_front", "weight": 1.0, "data": b"reference",
            }],
        )
        self.assertTrue(data.startswith(b"\x89PNG"))
        request = registry.calls[0][1]
        self.assertLessEqual(len(request.prompt.split()), 68)
        self.assertLess(request.prompt.index("REQUIRED:"), request.prompt.index("action:"))
        self.assertEqual(request.parameters["reference_inputs"][0]["character_id"], "an")
        self.assertTrue(request.parameters["fit_prompt_to_token_budget"])
        self.assertNotIn("reference_images", request.parameters)
        self.assertEqual(request.parameters["output_width"], 3840)
        self.assertEqual(provider.assessment("opening.png")["status"], "ASSESSED_PASS")
        self.assertEqual(assessor.calls[0][1]["required_elements"], ["character:an", "prop:paper boat"])

    def test_landscape_generation_passes_dpt_depth_map_and_records_provenance(self) -> None:
        class ControlledRegistry(FakeImageRegistry):
            def runtime_for(self, role):
                return SimpleNamespace(capabilities=lambda: RuntimeCapabilities(
                    image=True, image_reference=True, image_controlnet=True,
                ))

        class FakeDepthProvider:
            enabled = True
            unloaded = False

            def create(self, *, shot, reference_inputs, size):
                return ControlMap(
                    gradient_png(*size),
                    {
                        "schema_version": "1.0", "control_type": "depth",
                        "method": "DPT_FROM_SHOT_COMPOSITION_V1", "model_id": "test/dpt",
                        "control_map_sha256": "abc", "width": size[0], "height": size[1],
                        "conditioning_scale": 0.8, "reference_count": len(reference_inputs),
                        "source": "SHOT_SPEC_AND_CHARACTER_REFERENCES",
                    },
                )

            def unload(self):
                self.unloaded = True

        registry = ControlledRegistry()
        depth = FakeDepthProvider()
        provider = LocalLandscapeProvider(registry, FakeAssessor(), control_provider=depth)
        shot = {
            "action": "An đứng bên sông", "emotion": "bình tĩnh", "location": "bờ sông",
            "props": [], "prop_layout": [], "required_elements": ["character:an"],
            "forbidden_elements": ["uncontrolled_text"],
            "composition": {"framing": "wide shot"},
            "subjects": [{
                "character_id": "an", "position": {"x": 0.4, "y": 0.6},
                "scale": "medium", "pose": "standing", "gaze": "river",
            }],
            "control_guidance": {"priority": ["depth"], "inputs": [], "fallback": "prompt"},
        }
        provider.generate(
            basename="opening.png", story={"meta": {"title": "Bờ Sông"}},
            visual_plan_asset={
                "visual_moment": "An đứng bên sông", "state_delta_to_show": "nước lặng",
                "focal_character_ids": ["an"], "shot_spec": shot,
            },
            visual_bible={
                "art_direction_id": "storybook", "tonal_plan": {"palette": ["blue"]},
                "character_identity_locks": [{
                    "character_id": "an", "name": "An", "canonical_age_range": [10, 10],
                    "identity_traits": ["tóc đen"],
                }],
            },
            attempt=1, reference_inputs=[],
        )
        request = registry.calls[0][1]
        self.assertEqual(request.parameters["control_inputs"][0]["control_type"], "depth")
        self.assertEqual(request.parameters["control_inputs"][0]["scale"], 0.8)
        self.assertEqual(shot["control_guidance"]["inputs"][0]["model_id"], "test/dpt")
        self.assertEqual(provider.assessment("opening.png")["control_guidance"]["control_map_sha256"], "abc")
        provider.unload()
        self.assertTrue(depth.unloaded)

    def test_landscape_uses_composition_img2img_when_reference_adapter_is_unavailable(self) -> None:
        class Img2ImgRegistry(FakeImageRegistry):
            def runtime_for(self, role):
                return SimpleNamespace(capabilities=lambda: RuntimeCapabilities(
                    image=True, image_text_to_image=True, image_to_image=True,
                    image_reference=False, image_controlnet=False,
                ))

        registry = Img2ImgRegistry()
        provider = LocalLandscapeProvider(registry, FakeAssessor())
        provider.generate(
            basename="cover.png", story={"meta": {"title": "Paper Boat"}},
            visual_plan_asset={
                "visual_moment": "Bo holds a paper boat", "state_delta_to_show": "quiet",
                "focal_character_ids": ["bo"],
                "shot_spec": {
                    "action": "Bo holds a small folded paper boat", "emotion": "quiet",
                    "location": "bedroom", "props": ["paper boat"],
                    "required_elements": ["character:bo", "prop:paper boat"],
                    "forbidden_elements": ["duplicate_character"],
                    "composition": {"framing": "medium"},
                    "subjects": [{
                        "character_id": "bo", "position": {"x": 0.5, "y": 0.7},
                        "scale": "medium_full",
                    }],
                },
            },
            visual_bible={
                "art_direction_id": "storybook", "tonal_plan": {"palette": ["blue"]},
                "character_identity_locks": [{
                    "character_id": "bo", "name": "Bo", "canonical_age_range": [12, 12],
                    "identity_traits": ["boy"],
                }],
            },
            attempt=1,
            reference_inputs=[{
                "reference_id": "bo:full_body_front", "character_id": "bo",
                "view_id": "full_body_front", "data": gradient_png(80, 160),
            }],
        )
        request = registry.calls[0][1]
        self.assertIn("init_image", request.parameters)
        self.assertNotIn("visible change", request.prompt)
        self.assertLess(request.prompt.index("REQUIRED:"), request.prompt.index("action:"))

    def test_landscape_can_disable_composition_fallback_and_storybook_suffix(self) -> None:
        class Img2ImgRegistry(FakeImageRegistry):
            def runtime_for(self, role):
                return SimpleNamespace(capabilities=lambda: RuntimeCapabilities(
                    image=True, image_text_to_image=True, image_to_image=True,
                    image_reference=False, image_controlnet=False,
                ))

        registry = Img2ImgRegistry()
        provider = LocalLandscapeProvider(registry, FakeAssessor())
        provider.generate(
            basename="climax.png", story={"meta": {"title": "Paper Boat"}},
            visual_plan_asset={
                "focal_character_ids": ["bo"],
                "shot_spec": {
                    "prompt_core": "A candid family photograph.",
                    "prompt_style_suffix": "Photorealistic natural 16:9.",
                    "negative_prompt_override": "locked negative prompt",
                    "disable_composition_canvas_fallback": True,
                    "required_elements": ["character:bo"],
                    "forbidden_elements": ["uncontrolled_text"],
                    "subjects": [],
                },
            },
            visual_bible={
                "art_direction_id": "photorealistic-natural",
                "tonal_plan": {"palette": ["warm neutral"]},
                "character_identity_locks": [{
                    "character_id": "bo", "name": "Bo",
                    "canonical_age_range": [12, 12], "identity_traits": ["boy"],
                }],
            },
            attempt=1,
            reference_inputs=[{
                "reference_id": "bo:face_closeup", "character_id": "bo",
                "view_id": "face_closeup", "data": gradient_png(80, 160),
            }],
        )
        request = registry.calls[0][1]
        self.assertNotIn("init_image", request.parameters)
        self.assertIn("Photorealistic natural 16:9.", request.prompt)
        self.assertNotIn("Storybook", request.prompt)
        self.assertEqual(request.parameters["negative_prompt"], "locked negative prompt")

    def test_landscape_blocks_required_identity_conditioning_when_unsupported(self) -> None:
        class NoReferenceRegistry(FakeImageRegistry):
            def runtime_for(self, role):
                return SimpleNamespace(capabilities=lambda: RuntimeCapabilities(
                    image=True, image_text_to_image=True, image_to_image=True,
                    image_reference=False,
                ))

        registry = NoReferenceRegistry()
        provider = LocalLandscapeProvider(registry, FakeAssessor())
        with self.assertRaisesRegex(
            RuntimeCapabilityError, "requires identity-reference conditioning"
        ):
            provider.generate(
                basename="climax.png", story={"meta": {"title": "Paper Boat"}},
                visual_plan_asset={
                    "focal_character_ids": ["bo"],
                    "shot_spec": {
                        "prompt_core": "Photorealistic family scene.",
                        "require_reference_identity_conditioning": True,
                        "required_elements": ["character:bo"],
                        "forbidden_elements": ["uncontrolled_text"],
                        "subjects": [],
                    },
                },
                visual_bible={
                    "art_direction_id": "photorealistic-natural",
                    "tonal_plan": {"palette": ["warm neutral"]},
                    "character_identity_locks": [{
                        "character_id": "bo", "name": "Bo",
                        "canonical_age_range": [12, 12], "identity_traits": ["boy"],
                    }],
                },
                attempt=1,
                reference_inputs=[{
                    "reference_id": "bo:face_closeup", "character_id": "bo",
                    "view_id": "face_closeup", "data": gradient_png(80, 160),
                }],
            )
        self.assertEqual(registry.calls, [])

    def test_visual_fidelity_probe_rejects_clear_wrong_object_form(self) -> None:
        class ProbeAssessor(LocalImageQualityAssessor):
            def _clip_similarity(self, image, *, prompt=None, reference=None):
                return {
                    "scene": 0.8,
                    "a small folded paper boat": 0.2,
                    "a full-size wooden ship": 0.7,
                }.get(prompt, 0.8)

        assessor = ProbeAssessor({
            "ocr_enabled": False, "require_semantic": True,
            "minimum_variance": 1, "semantic_threshold": 0.1,
        })
        with self.assertRaisesRegex(ImageQualityError, "visual fidelity") as raised:
            assessor.assess(
                gradient_png(64, 64), prompt="scene", expected_dimensions=(64, 64),
                fidelity_probes=[{
                    "probe_id": "paper_boat_scale",
                    "expected": "a small folded paper boat",
                    "forbidden": ["a full-size wooden ship"],
                }],
            )
        self.assertEqual(
            raised.exception.assessment["findings"][0]["error"],
            "VISUAL_FIDELITY_MISMATCH",
        )

    def test_visual_fidelity_probe_uses_local_crop_when_requested(self) -> None:
        observed_sizes = []

        class ProbeAssessor(LocalImageQualityAssessor):
            def _clip_similarity(self, image, *, prompt=None, reference=None):
                observed_sizes.append(image.size)
                return 0.8 if "palm-sized" in str(prompt) else 0.2

        assessor = ProbeAssessor({"fidelity_contrastive_tolerance": 0.015})
        result = assessor.assess_fidelity_probes(
            gradient_png(100, 80),
            fidelity_probes=[{
                "probe_id": "controlled_prop_scale",
                "expected": "a palm-sized paper boat between two hands",
                "forbidden": ["an oversized paper boat"],
                "crop_box_pixels": [20, 10, 70, 50],
            }],
        )

        self.assertEqual(result["status"], "ASSESSED_PASS")
        self.assertEqual(result["checks"][0]["scope"], "LOCAL_CROP")
        self.assertEqual(result["checks"][0]["crop_box_pixels"], [20, 10, 70, 50])
        self.assertEqual(observed_sizes, [(50, 40), (50, 40)])

    def test_required_visual_fidelity_gate_enforces_absolute_score_and_margin(self) -> None:
        class ProbeAssessor(LocalImageQualityAssessor):
            def _clip_similarity(self, image, *, prompt=None, reference=None):
                return {
                    "natural hands holding an object": 0.31,
                    "malformed merged hands": 0.30,
                }.get(prompt)

        assessor = ProbeAssessor({"fidelity_contrastive_tolerance": 0.015})
        result = assessor.assess_fidelity_probes(
            gradient_png(100, 80),
            fidelity_probes=[{
                "probe_id": "hand_anatomy",
                "required": True,
                "expected": "natural hands holding an object",
                "forbidden": ["malformed merged hands"],
                "minimum_expected_score": 0.32,
                "minimum_contrast_margin": 0.03,
            }],
        )

        self.assertEqual(result["status"], "ASSESSED_FAIL")
        self.assertEqual(result["failed_probes"], ["hand_anatomy"])
        self.assertEqual(
            result["checks"][0]["failure_reasons"],
            ["EXPECTED_SCORE_BELOW_MINIMUM", "CONTRAST_MARGIN_BELOW_MINIMUM"],
        )

    def test_portrait_uses_image_to_image_and_parity_assessment(self) -> None:
        registry = FakeImageRegistry()
        assessor = FakeAssessor()
        provider = LocalPortraitProvider(registry, assessor)
        source = gradient_png(384, 216)
        data = provider.generate(
            basename="opening.png",
            landscape_bytes=source,
            visual_plan_asset={"visual_moment": "An bước vào vườn"},
            visual_bible={"art_direction_id": "cinematic_storybook_v1"},
            attempt=1,
        )
        self.assertTrue(data.startswith(b"\x89PNG"))
        request = registry.calls[0][1]
        self.assertIn("init_image", request.parameters)
        recomposed = Image.open(io.BytesIO(request.parameters["init_image"]))
        self.assertEqual(recomposed.size, (704, 1216))
        self.assertEqual(request.parameters["output_height"], 1920)
        self.assertTrue(request.parameters["fit_prompt_to_token_budget"])
        self.assertEqual(assessor.calls[0][1]["reference"], source)
        self.assertEqual(provider.assessment("opening.png")["portrait_transform"]["mode"], "RECOMPOSE_IMG2IMG")

    def test_portrait_outpaint_builds_mask_and_preserves_source_band(self) -> None:
        source = gradient_png(384, 216)
        canvas, mask, evidence = _portrait_canvas(
            source, 704, 1216,
            [{"position": {"x": 0.5, "y": 0.5}}],
            outpaint=True,
            reserve_title=False,
        )
        self.assertEqual(Image.open(io.BytesIO(canvas)).size, (704, 1216))
        mask_image = Image.open(io.BytesIO(mask))
        self.assertEqual(mask_image.getpixel((352, 608)), 0)
        self.assertGreater(mask_image.getpixel((352, 20)), 240)
        self.assertEqual(evidence["mode"], "OUTPAINT")

    def test_portrait_cover_canvas_excludes_stage2_title_band(self) -> None:
        source = Image.new("RGB", (400, 200), "green")
        source.paste("red", (0, 0, 400, 44))
        encoded = io.BytesIO()
        source.save(encoded, format="PNG")
        canvas, _, evidence = _portrait_canvas(
            encoded.getvalue(), 200, 400, [],
            outpaint=False, reserve_title=True, exclude_title_band=True,
        )
        image = Image.open(io.BytesIO(canvas))
        self.assertEqual(evidence["source_top_crop_pixels"], 44)
        self.assertEqual(image.getpixel((100, 250)), (0, 128, 0))

    def test_portrait_prefers_outpaint_when_runtime_supports_it(self) -> None:
        class OutpaintRegistry(FakeImageRegistry):
            def runtime_for(self, role):
                class Runtime:
                    @staticmethod
                    def capabilities():
                        return RuntimeCapabilities(
                            image=True, image_text_to_image=True, image_to_image=True,
                            image_reference=True, image_inpainting=True, image_outpainting=True,
                        )
                return Runtime()

        registry = OutpaintRegistry()
        provider = LocalPortraitProvider(registry, FakeAssessor())
        provider.generate(
            basename="cover.png",
            landscape_bytes=gradient_png(384, 216),
            visual_plan_asset={
                "visual_moment": "An dưới mưa",
                "shot_spec": {"subjects": [{"position": {"x": 0.5, "y": 0.64}}]},
            },
            visual_bible={"art_direction_id": "cinematic_storybook_v1"},
            attempt=1,
            reference_inputs=[{
                "reference_id": "an:face_closeup", "character_id": "an",
                "view_id": "face_closeup", "weight": 1.0,
                "data": gradient_png(64, 64),
            }],
        )
        request = registry.calls[0][1]
        self.assertIn("outpaint_image", request.parameters)
        self.assertIn("outpaint_mask", request.parameters)
        self.assertNotIn("init_image", request.parameters)
        self.assertEqual(request.parameters["reference_inputs"][0]["character_id"], "an")
        self.assertEqual(provider.assessment("cover.png")["portrait_transform"]["mode"], "OUTPAINT")

    def test_portrait_cover_prompt_does_not_repeat_story_title(self) -> None:
        registry = FakeImageRegistry()
        provider = LocalPortraitProvider(registry, FakeAssessor())
        provider.generate(
            basename="cover.png",
            landscape_bytes=gradient_png(384, 216),
            visual_plan_asset={
                "visual_moment": "Key art for The Lost Bird Adventure",
                "shot_spec": {"action": "Cover art for The Lost Bird Adventure"},
            },
            visual_bible={"art_direction_id": "cinematic_storybook_v1"},
            attempt=1,
        )
        prompt = registry.calls[0][1].prompt
        self.assertIn("No visible text or lettering", prompt)
        self.assertNotIn("The Lost Bird Adventure", prompt)

    def test_portrait_repair_plan_changes_prompt_and_denoise_strength(self) -> None:
        registry = FakeImageRegistry()
        provider = LocalPortraitProvider(registry, FakeAssessor())
        provider.set_repair_plan("opening.png", {
            "prompt_corrections": ["Preserve source identity and wardrobe."],
            "negative_prompt_additions": ["face swap"],
            "parameter_adjustments": {"strength": 0.24},
        })
        provider.generate(
            basename="opening.png",
            landscape_bytes=gradient_png(384, 216),
            visual_plan_asset={"visual_moment": "An mở cổng", "shot_spec": {}},
            visual_bible={"art_direction_id": "cinematic_storybook_v1"},
            attempt=2,
        )
        request = registry.calls[0][1]
        self.assertIn("QA REPAIR", request.prompt)
        self.assertIn("face swap", request.parameters["negative_prompt"])
        self.assertEqual(request.parameters["strength"], 0.24)

    def test_technical_qa_rejects_blank_image(self) -> None:
        assessor = LocalImageQualityAssessor(
            {
                "ocr_enabled": False,
                "require_semantic": False,
                "minimum_variance": 18,
                "luma_band": [20, 235],
            }
        )
        blank = io.BytesIO()
        Image.new("RGB", (64, 64), (128, 128, 128)).save(blank, format="PNG")
        with self.assertRaisesRegex(ImageQualityError, "blank") as raised:
            assessor.assess(
                blank.getvalue(), prompt="scene", expected_dimensions=(64, 64)
            )
        self.assertEqual(raised.exception.assessment["findings"][0]["error"], "LOW_VISUAL_VARIANCE")
        self.assertEqual(raised.exception.assessment["qa_layers"][-1]["layer"], "TECHNICAL")

    def test_technical_qa_uses_asset_specific_luminance_band(self) -> None:
        assessor = LocalImageQualityAssessor(
            {
                "ocr_enabled": False,
                "require_semantic": False,
                "minimum_variance": 1,
                "luma_band": [20, 235],
                "thresholds_by_asset": {"character": {"luma_band": [5, 250]}},
            }
        )
        image = Image.new("RGB", (64, 64), (245, 245, 245))
        for x in range(24, 40):
            for y in range(8, 56):
                image.putpixel((x, y), (80, 100, 120))
        output = io.BytesIO()
        image.save(output, format="PNG")

        result = assessor.assess(
            output.getvalue(), prompt="character sheet", expected_dimensions=(64, 64),
            asset_type="character",
        )

        self.assertEqual(result["status"], "ASSESSED_PASS")

    def test_qa_rejects_any_pseudo_text_when_typography_is_forbidden(self) -> None:
        assessor = LocalImageQualityAssessor(
            {
                "ocr_enabled": True,
                "require_semantic": False,
                "minimum_variance": 1,
                "luma_band": [0, 255],
                "maximum_ocr_characters": 0,
            }
        )
        with patch.object(assessor, "_ocr", return_value="pseudo"):
            with self.assertRaisesRegex(Exception, "unwanted text"):
                assessor.assess(
                    gradient_png(64, 64), prompt="scene", expected_dimensions=(64, 64),
                    asset_type="cover",
                )

    def test_structured_visual_qa_records_required_and_forbidden_elements(self) -> None:
        assessor = LocalImageQualityAssessor(
            {
                "ocr_enabled": False, "require_semantic": False, "minimum_variance": 1,
                "luma_band": [0, 255], "element_threshold": 0.16,
            }
        )
        with patch.object(assessor, "_clip_similarity", return_value=0.8):
            result = assessor.assess(
                gradient_png(64, 64), prompt="scene", expected_dimensions=(64, 64),
                required_elements=["prop:paper boat", "composition:face_unobstructed"],
                forbidden_elements=["uncontrolled_text", "duplicate_character"],
            )
        structured = result["structured_visual_qa"]
        self.assertEqual(structured["status"], "PARTIALLY_ASSESSED")
        self.assertEqual(structured["required_element_count"], 2)
        self.assertEqual(structured["checks"][-1]["status"], "NOT_MEASURED")


if __name__ == "__main__":
    unittest.main()
