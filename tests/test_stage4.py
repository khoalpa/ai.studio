from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ai_story.archive import PackageVerifier
from ai_story.models import Profile
from ai_story.stage1 import Stage1Pipeline, Stage1Request
from ai_story.stage1.config import confirm_duration
from ai_story.stage2 import Stage2Pipeline, Stage2Request
from ai_story.stage3 import Stage3Pipeline, Stage3Request
from ai_story.stage4 import Stage4Pipeline, Stage4Request
from ai_story.workspace import RunWorkspace


class Stage4Tests(unittest.TestCase):
    def _stage3(self, root: Path) -> Path:
        workspace1 = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage4-source1")
        stage1 = Stage1Pipeline().run(
            Stage1Request(
                Profile.YOUTH_SAFE,
                "Hai người bạn tìm lại vật kỷ niệm sau cơn mưa",
                confirm_duration(Profile.YOUTH_SAFE, 15),
            ),
            workspace1,
        )
        workspace2 = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage4-source2")
        stage2 = Stage2Pipeline().run(
            Stage2Request(Path(stage1.package.archive_path), allow_blocked_fixture_for_testing=True), workspace2
        )
        workspace3 = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage4-source3")
        stage3 = Stage3Pipeline().run(
            Stage3Request(Path(stage2.package.archive_path), allow_blocked_fixture_for_testing=True), workspace3
        )
        return Path(stage3.package.archive_path)

    def test_stage4_end_to_end_and_character_only_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage3_package = self._stage3(root)
            workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage4-final")
            result = Stage4Pipeline().run(
                Stage4Request(stage3_package, confirm_large_plan=True, visual_review_approved=True, allow_blocked_fixture_for_testing=True), workspace
            )
            self.assertGreater(result.clip_count, 0)
            verified = PackageVerifier().verify(Path(result.package.archive_path))
            self.assertEqual(verified.package_stage, "STAGE4")
            self.assertEqual(verified.file_count, 37)
            with zipfile.ZipFile(stage3_package) as source, zipfile.ZipFile(result.package.archive_path) as output:
                self.assertEqual(source.read("visual_plan.json"), output.read("visual_plan.json"))
                self.assertEqual(source.read("package_quality_report.json"), output.read("package_quality_report.json"))
                prompts = json.loads(output.read("video_prompts.json"))
                production = json.loads(output.read("production_plan.json"))
                subtitles_srt = output.read("subtitles.srt").decode("utf-8")
                subtitles_vtt = output.read("subtitles.vtt").decode("utf-8")
                manifest = json.loads(output.read("workflow_manifest.json"))
                review = json.loads(output.read("visual_review.json"))
            self.assertEqual(len(prompts), 8)
            self.assertEqual(prompts["project"]["clip_count"], len(prompts["clips"]))
            self.assertEqual(prompts["validation"]["status"], "PASS")
            self.assertEqual(manifest["package_purpose"], "VIDEO_PRODUCTION_RELEASE")
            self.assertEqual(review["decision"], "APPROVED")
            self.assertEqual(len(review["items"]), 5)
            self.assertEqual(review["items"][0]["asset_type"], "CHARACTER_REFERENCE")
            self.assertEqual(len(production["shot_registry"]), len(prompts["clips"]))
            self.assertEqual(production["continuity_graph"]["status"], "PASS")
            self.assertEqual(production["subtitle_delivery"]["status"], "PASS")
            self.assertEqual(production["audio_delivery"]["status"], "PLANNED_NOT_RENDERED")
            self.assertTrue(subtitles_srt.startswith("1\n00:00:00,000"))
            self.assertTrue(subtitles_vtt.startswith("WEBVTT\n"))
            for clip in prompts["clips"]:
                for reference in clip["reference_inputs"]["character_images"]:
                    self.assertTrue(reference.startswith("characters/"))
                serialized = json.dumps(clip)
                self.assertNotIn("landscape/", serialized)
                self.assertNotIn("portrait/", serialized)


if __name__ == "__main__":
    unittest.main()
