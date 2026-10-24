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
from ai_story.workspace import RunWorkspace


class Stage3Tests(unittest.TestCase):
    def _stage2(self, root: Path) -> Path:
        stage1_workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage3-source1")
        stage1 = Stage1Pipeline().run(
            Stage1Request(
                Profile.YOUTH_SAFE,
                "Hai người bạn tìm lại vật kỷ niệm sau cơn mưa",
                confirm_duration(Profile.YOUTH_SAFE, 15),
            ),
            stage1_workspace,
        )
        stage2_workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage3-source2")
        stage2 = Stage2Pipeline().run(
            Stage2Request(Path(stage1.package.archive_path), allow_blocked_fixture_for_testing=True), stage2_workspace
        )
        return Path(stage2.package.archive_path)

    def test_stage3_end_to_end_and_preserves_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage2_package = self._stage2(root)
            workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage3-final")
            result = Stage3Pipeline().run(Stage3Request(stage2_package, allow_blocked_fixture_for_testing=True), workspace)
            self.assertEqual(result.committed_assets, 10)
            self.assertEqual(result.generation_calls, 10)
            verified = PackageVerifier().verify(Path(result.package.archive_path))
            self.assertEqual(verified.package_stage, "STAGE3")
            self.assertEqual(verified.file_count, 32)
            with zipfile.ZipFile(stage2_package) as source, zipfile.ZipFile(result.package.archive_path) as output:
                self.assertEqual(source.read("visual_plan.json"), output.read("visual_plan.json"))
                self.assertEqual(source.read("visual_bible.json"), output.read("visual_bible.json"))
                portraits = [name for name in output.namelist() if name.startswith("portrait/")]
                report = json.loads(output.read("package_quality_report.json"))
                manifest = json.loads(output.read("workflow_manifest.json"))
            self.assertEqual(len(portraits), 10)
            self.assertEqual(report["summary"]["publish_verdict"], "PASS")
            self.assertEqual(report["blockers"], [])
            self.assertEqual(report["image_evidence"]["cross_orientation_pair_count"], 10)
            self.assertEqual(manifest["package_purpose"], "AUDIO_STORY_RELEASE")


if __name__ == "__main__":
    unittest.main()
