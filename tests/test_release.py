from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_story.models import Profile
from ai_story.release import ReleaseEvaluator
from ai_story.stage1 import Stage1Pipeline, Stage1Request
from ai_story.stage1.config import confirm_duration
from ai_story.stage2 import Stage2Pipeline, Stage2Request
from ai_story.stage3 import Stage3Pipeline, Stage3Request
from ai_story.stage4 import Stage4Pipeline, Stage4Request
from ai_story.workspace import RunWorkspace


class ReleaseTests(unittest.TestCase):
    def _stage4(self, root: Path) -> Path:
        first = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-release-stage1")
        stage1 = Stage1Pipeline().run(
            Stage1Request(
                Profile.YOUTH_SAFE,
                "Hai người bạn cùng bảo vệ khu vườn sau cơn bão",
                confirm_duration(Profile.YOUTH_SAFE, 15),
            ),
            first,
        )
        second = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-release-stage2")
        stage2 = Stage2Pipeline().run(
            Stage2Request(Path(stage1.package.archive_path), allow_blocked_fixture_for_testing=True), second
        )
        third = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-release-stage3")
        stage3 = Stage3Pipeline().run(
            Stage3Request(Path(stage2.package.archive_path), allow_blocked_fixture_for_testing=True), third
        )
        fourth = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-release-stage4")
        stage4 = Stage4Pipeline().run(
            Stage4Request(Path(stage3.package.archive_path), confirm_large_plan=True, visual_review_approved=True, allow_blocked_fixture_for_testing=True), fourth
        )
        return Path(stage4.package.archive_path)

    def test_development_release_blocks_fixture_even_when_quality_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = self._stage4(root)
            report = ReleaseEvaluator().evaluate(package, channel="development")
            self.assertEqual(report["readiness"], "BLOCKED")
            self.assertEqual(report["release_label"], "LOCAL_DEVELOPMENT")
            self.assertTrue(report["blockers"])
            self.assertIn("RELEASABLE_ARTIFACT_CLASS", report["blockers"])
            self.assertNotIn("CONTENT_QUALITY_STATUS", report["blockers"])
            self.assertTrue(report["warnings"])
            self.assertEqual(report["validation_ledger"]["current_stage"], "STAGE4")
            self.assertEqual(
                report["validation_ledger"]["stage_history"],
                ["STAGE1", "STAGE2", "STAGE3", "STAGE4"],
            )
            self.assertEqual(
                {item["role"] for item in report["model_inventory"]},
                {"story", "character_image", "safety", "landscape", "portrait"},
            )


    def test_production_release_is_blocked_without_local_evidence_and_external_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self._stage4(Path(temporary))
            report = ReleaseEvaluator().evaluate(package, channel="production")
            self.assertEqual(report["readiness"], "BLOCKED")
            self.assertIn("LOCAL_PROVIDER_MODE", report["blockers"])
            self.assertIn("PRODUCTION_IMAGE_ASSESSMENT", report["blockers"])
            self.assertIn("EXTERNAL_FRAMEWORK_AUDIT", report["blockers"])
            self.assertIn("STRUCTURED_VISUAL_QA", report["blockers"])
            self.assertIn("BENCHMARK_PROMOTION", report["blockers"])
            self.assertIn("IMAGE_BENCHMARK_PROMOTION", report["blockers"])
            self.assertNotIn("HUMAN_VISUAL_REVIEW", report["blockers"])


if __name__ == "__main__":
    unittest.main()
