from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_story.job_engine import JobRegistry
from ai_story.web import WebService
from tools.prepare_week1_usability_dataset import prepare


class Week1UsabilityDatasetTests(unittest.TestCase):
    def test_dataset_is_reproducible_and_exposes_expected_states(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "week1"
            manifest = prepare(output)

            self.assertEqual(manifest["expected"]["clean_workspace_run_count"], 0)
            self.assertEqual(
                [path for path in Path(manifest["clean_workspace"]).iterdir()], []
            )

            service = WebService(
                Path(manifest["blocked_workspace"]), jobs=JobRegistry(max_workers=1)
            )
            try:
                detail = service.get_run(manifest["blocked_run_id"])
                self.assertGreaterEqual(detail["validation"]["blocking_count"], 1)
                blocker = next(
                    item
                    for item in detail["validation"]["records"]
                    if item["id"] == "RESEARCH:BLOCKER:BRIEF_COVERAGE"
                )
                self.assertEqual(blocker["status"], "FAIL")
                self.assertEqual(blocker["severity"], "PUBLISH_BLOCKER")

                package = Path(manifest["warning_package"])
                inspected = service.inspect_package(package.read_bytes())
                self.assertTrue(inspected["valid"])
                self.assertEqual(
                    inspected["quality_decision"]["release_status"], "BLOCKED"
                )
            finally:
                service.jobs.close()

            stored = json.loads(
                (output / "study-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(stored["blocked_run_id"], manifest["blocked_run_id"])

            ready_service = WebService(
                Path(manifest["ready_workspace"]), jobs=JobRegistry(max_workers=1)
            )
            try:
                ready = ready_service.get_run(manifest["blocked_run_id"])
                self.assertEqual(ready["validation"]["blocking_count"], 0)
                self.assertEqual(ready["package"]["allowed_next_stage"], "STAGE2")
            finally:
                ready_service.jobs.close()


if __name__ == "__main__":
    unittest.main()
