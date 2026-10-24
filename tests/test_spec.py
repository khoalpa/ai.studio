from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lint_spec", ROOT / "tools" / "lint_spec.py")
assert SPEC and SPEC.loader
lint_spec = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint_spec)


class SpecificationTests(unittest.TestCase):
    def test_canonical_spec_is_valid(self) -> None:
        summary = lint_spec.lint()
        self.assertIn("routes=24", summary)

    def test_invalid_fixture_skips_stage(self) -> None:
        fixture = json.loads(
            (ROOT / "fixtures" / "invalid" / "skip_stage.json").read_text(encoding="utf-8")
        )
        registry = lint_spec.load("spec/registry.json")
        next_stage = registry["workflow"]["transitions"][fixture["current_stage"]]
        self.assertNotEqual(next_stage, fixture["requested_stage"])
        self.assertEqual(fixture["expected_error"], "STAGE_TRANSITION_INVALID")

    def test_every_artifact_has_single_owner(self) -> None:
        registry = lint_spec.load("spec/registry.json")
        for definition in registry["artifacts"].values():
            self.assertIsInstance(definition["owner_stage"], str)
            self.assertTrue(definition["owner_stage"])


if __name__ == "__main__":
    unittest.main()
