from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ai_story.errors import WorkflowError
from ai_story.models import Profile
from ai_story.operations import PackageRepairSession, RunIndex
from ai_story.serial import validate_anchor
from ai_story.stage1 import Stage1Pipeline, Stage1Request
from ai_story.stage1.config import confirm_duration
from ai_story.stage2 import Stage2Pipeline, Stage2Request
from ai_story.stage3 import Stage3Pipeline, Stage3Request
from ai_story.stage4 import Stage4Pipeline, Stage4Request
from ai_story.workspace import RunWorkspace


class Stage6Tests(unittest.TestCase):
    def _serial_stage1(self, root: Path) -> Path:
        workspace = RunWorkspace.create(root, Profile.SERIAL_DETECTIVE, "run-serial-episode1")
        result = Stage1Pipeline().run(
            Stage1Request(
                Profile.SERIAL_DETECTIVE,
                "Một bức thư xuất hiện trong căn phòng khóa kín",
                confirm_duration(Profile.SERIAL_DETECTIVE, 42, "START_SERIES"),
                episode_mode="START_SERIES",
                series_title="Hồ Sơ Mưa Đêm",
                planned_arc_episodes=12,
            ),
            workspace,
        )
        return Path(result.package.archive_path)

    def test_serial_start_and_stage2_anchor_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1_package = self._serial_stage1(root)
            with zipfile.ZipFile(stage1_package) as archive:
                anchor_bytes = archive.read("series_anchor.json")
                story = json.loads(archive.read("story.json"))
                anchor = json.loads(anchor_bytes)
            validate_anchor(anchor)
            self.assertEqual(anchor["continuity"]["latest_episode"], 1)
            self.assertEqual(story["meta"]["series"], "Hồ Sơ Mưa Đêm")
            workspace = RunWorkspace.create(root, Profile.SERIAL_DETECTIVE, "run-serial-stage2")
            stage2 = Stage2Pipeline().run(Stage2Request(stage1_package, allow_blocked_fixture_for_testing=True), workspace)
            with zipfile.ZipFile(stage2.package.archive_path) as archive:
                self.assertEqual(archive.read("series_anchor.json"), anchor_bytes)

    def test_serial_route_reaches_stage4_without_mutating_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1_package = self._serial_stage1(root)
            with zipfile.ZipFile(stage1_package) as archive:
                anchor_bytes = archive.read("series_anchor.json")
            workspace2 = RunWorkspace.create(root, Profile.SERIAL_DETECTIVE, "run-serial-route2")
            stage2 = Stage2Pipeline().run(Stage2Request(stage1_package, allow_blocked_fixture_for_testing=True), workspace2)
            workspace3 = RunWorkspace.create(root, Profile.SERIAL_DETECTIVE, "run-serial-route3")
            stage3 = Stage3Pipeline().run(
                Stage3Request(Path(stage2.package.archive_path), allow_blocked_fixture_for_testing=True), workspace3
            )
            workspace4 = RunWorkspace.create(root, Profile.SERIAL_DETECTIVE, "run-serial-route4")
            stage4 = Stage4Pipeline().run(
                Stage4Request(Path(stage3.package.archive_path), confirm_large_plan=True, visual_review_approved=True, allow_blocked_fixture_for_testing=True),
                workspace4,
            )
            with zipfile.ZipFile(stage4.package.archive_path) as archive:
                self.assertEqual(archive.read("series_anchor.json"), anchor_bytes)
                manifest = json.loads(archive.read("workflow_manifest.json"))
            self.assertEqual(manifest["package_stage"], "STAGE4")

    def test_serial_continue_increments_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_package = self._serial_stage1(root)
            anchor_path = root / "episode1-anchor.json"
            with zipfile.ZipFile(first_package) as archive:
                anchor_path.write_bytes(archive.read("series_anchor.json"))
            workspace = RunWorkspace.create(root, Profile.SERIAL_DETECTIVE, "run-serial-episode2")
            second = Stage1Pipeline().run(
                Stage1Request(
                    Profile.SERIAL_DETECTIVE,
                    "Một nhân chứng cũ quay lại với lời khai mâu thuẫn",
                    confirm_duration(Profile.SERIAL_DETECTIVE, 36, "CONTINUE_SERIES"),
                    episode_mode="CONTINUE_SERIES",
                    input_anchor=anchor_path,
                ),
                workspace,
            )
            with zipfile.ZipFile(second.package.archive_path) as archive:
                anchor = json.loads(archive.read("series_anchor.json"))
                story = json.loads(archive.read("story.json"))
            self.assertEqual(anchor["continuity"]["latest_episode"], 2)
            self.assertEqual(anchor["continuity"]["revision"], 2)
            self.assertEqual([item["episode_number"] for item in anchor["episode_ledger"]], [1, 2])
            self.assertEqual(story["meta"]["episode"], "2")

    def test_repair_rejects_inherited_member_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1_package = self._serial_stage1(root)
            stage2_workspace = RunWorkspace.create(
                root, Profile.SERIAL_DETECTIVE, "run-repair-source-stage2"
            )
            stage2_package = Path(
                Stage2Pipeline().run(
                    Stage2Request(stage1_package, allow_blocked_fixture_for_testing=True), stage2_workspace
                ).package.archive_path
            )
            workspace = RunWorkspace.create(root, Profile.SERIAL_DETECTIVE, "run-repair-denied")

            def mutate(work: Path) -> None:
                (work / "story.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(WorkflowError):
                PackageRepairSession().run(
                    input_package=stage2_package, workspace=workspace, mutate=mutate
                )

    def test_run_index_reports_last_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-index-0001")
            workspace.log("CUSTOM_EVENT", {"value": 1})
            runs = RunIndex().list_runs(root)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["last_event"], "CUSTOM_EVENT")


if __name__ == "__main__":
    unittest.main()
