from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_story.smoke import run_deterministic_smoke


class SmokeWorkflowTests(unittest.TestCase):
    def test_deterministic_workflow_reaches_stage4_and_release_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = run_deterministic_smoke(Path(temporary))

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["completed_stages"],
            ["STAGE1", "STAGE2", "STAGE3", "STAGE4"],
        )
        self.assertEqual(result["release_evaluation"]["readiness"], "BLOCKED")
        self.assertIn(
            "RELEASABLE_ARTIFACT_CLASS",
            result["release_evaluation"]["blockers"],
        )
        self.assertEqual(result["release_bundle"]["distribution_status"], "NOT_APPROVED")
        self.assertEqual(result["validation_ledger"]["current_stage"], "STAGE4")
        self.assertEqual(
            result["validation_ledger"]["stage_history"],
            ["STAGE1", "STAGE2", "STAGE3", "STAGE4"],
        )
        self.assertGreater(result["validation_ledger"]["summary"]["record_count"], 20)
        self.assertGreater(result["validation_ledger"]["summary"]["open_warning_count"], 0)


if __name__ == "__main__":
    unittest.main()
