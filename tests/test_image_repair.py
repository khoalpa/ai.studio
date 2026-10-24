from __future__ import annotations

import unittest

from ai_story.image_repair import plan_image_repair


class ImageRepairPlannerTests(unittest.TestCase):
    def test_parity_failure_selects_recompose_and_lower_strength(self) -> None:
        plan = plan_image_repair(
            {"findings": [{"error": "PARITY_MISMATCH", "layer": "PARITY"}]},
            attempt=1,
            asset_type="portrait",
        )
        self.assertEqual(plan["disposition"], "RECOMPOSE")
        self.assertEqual(plan["parameter_adjustments"]["strength"], 0.24)
        self.assertTrue(plan["retryable"])

    def test_identity_and_text_repairs_are_merged_without_duplicates(self) -> None:
        plan = plan_image_repair(
            {"findings": [
                {"error": "IDENTITY_MISMATCH", "layer": "IDENTITY"},
                {"error": "UNWANTED_TEXT", "layer": "OCR_SAFETY"},
            ]},
            attempt=2,
            asset_type="landscape",
        )
        self.assertIn("mixed identity", plan["negative_prompt_additions"])
        self.assertIn("letters", plan["negative_prompt_additions"])
        self.assertEqual(plan["parameter_adjustments"]["strength"], 0.3)

    def test_missing_assessor_aborts_without_retry(self) -> None:
        plan = plan_image_repair(
            {"findings": [{"error": "ASSESSOR_UNAVAILABLE", "layer": "SEMANTIC"}]},
            attempt=1,
            asset_type="cover",
        )
        self.assertEqual(plan["disposition"], "ABORT")
        self.assertFalse(plan["retryable"])

    def test_missing_props_are_named_first_in_repair_prompt(self) -> None:
        plan = plan_image_repair(
            {"findings": [{
                "error": "REQUIRED_ELEMENT_MISSING", "layer": "COMPOSITION_ELEMENTS",
                "elements": ["prop:blue pillow", "prop:duck pillow"],
            }]},
            attempt=1,
            asset_type="scene",
        )
        self.assertEqual(
            plan["prompt_corrections"][0],
            "Clearly show these missing required elements: blue pillow, duck pillow",
        )

    def test_missing_characters_and_props_are_both_named(self) -> None:
        plan = plan_image_repair(
            {"findings": [{
                "error": "REQUIRED_ELEMENT_MISSING", "layer": "COMPOSITION_ELEMENTS",
                "elements": ["character:hao", "prop:injured seabird"],
            }]},
            attempt=1,
            asset_type="scene",
        )
        self.assertIn("hao, injured seabird", plan["prompt_corrections"][0])
        self.assertGreater(plan["parameter_adjustments"]["guidance_scale"], 6.5)
        self.assertGreater(plan["parameter_adjustments"]["steps"], 28)


if __name__ == "__main__":
    unittest.main()
