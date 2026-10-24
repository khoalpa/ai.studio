from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from ai_story.archive import PackageVerifier
from ai_story.errors import WorkflowError
from ai_story.gpt_image_web_assist import GPTImageWebAssist
from ai_story.models import Profile
from ai_story.stage1 import Stage1Pipeline, Stage1Request
from ai_story.stage1.config import confirm_duration
from ai_story.stage2 import Stage2Pipeline, Stage2Request
from ai_story.stage2.cover import render_cover_typography
from ai_story.stage2.providers import DeterministicLandscapeProvider
from ai_story.workspace import RunWorkspace


class Stage2Tests(unittest.TestCase):
    def test_cover_typography_is_rendered_in_declared_safe_region(self) -> None:
        source = io.BytesIO()
        Image.new("RGB", (800, 450), (80, 100, 120)).save(source, format="PNG")
        rendered, evidence = render_cover_typography(source.getvalue(), "Lời Hứa Dưới Mưa")
        self.assertNotEqual(rendered, source.getvalue())
        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["method"], "CONTROLLED_POSTPROCESS")
        self.assertEqual(len(evidence["safe_region"]), 4)
    def _stage1(self, root: Path) -> Path:
        workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage2-source")
        result = Stage1Pipeline().run(
            Stage1Request(
                Profile.YOUTH_SAFE,
                "Hai người bạn tìm lại vật kỷ niệm sau cơn mưa",
                confirm_duration(Profile.YOUTH_SAFE, 15),
            ),
            workspace,
        )
        return Path(result.package.archive_path)

    def test_zone_stage2_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1_package = self._stage1(root)
            workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage2-zone")
            result = Stage2Pipeline().run(Stage2Request(stage1_package, allow_blocked_fixture_for_testing=True), workspace)
            self.assertEqual(result.committed_assets, 10)
            self.assertEqual(result.generation_calls, 10)
            verified = PackageVerifier().verify(Path(result.package.archive_path))
            self.assertEqual(verified.package_stage, "STAGE2")
            self.assertEqual(verified.file_count, 21)
            with zipfile.ZipFile(stage1_package) as source, zipfile.ZipFile(result.package.archive_path) as output:
                self.assertEqual(source.read("story.json"), output.read("story.json"))
                self.assertEqual(source.read("story_validation.json"), output.read("story_validation.json"))
                plan = json.loads(output.read("visual_plan.json"))
                bible = json.loads(output.read("visual_bible.json"))
                landscape = [name for name in output.namelist() if name.startswith("landscape/")]
            self.assertEqual(plan["resolved_mode"], "ZONE")
            self.assertEqual(len(plan["assets"]), 10)
            self.assertEqual(len(landscape), 10)
            self.assertEqual(plan["schema_version"], "1.2")
            self.assertEqual(bible["schema_version"], "2.2")
            cover = plan["assets"][0]
            self.assertIn("shot_spec", cover)
            self.assertEqual(
                [item["character_id"] for item in cover["shot_spec"]["subjects"]],
                cover["focal_character_ids"],
            )
            self.assertEqual(cover["shot_spec"]["control_guidance"]["priority"][0], "depth")
            self.assertIn("composition:title_safe_area", cover["shot_spec"]["required_elements"])
            self.assertIn("presentation", bible["character_identity_locks"][0])
            self.assertEqual(
                {item["view_id"] for item in bible["character_identity_locks"][0]["master_reference_set"]["views"]},
                {"full_body_front", "face_closeup", "three_quarter"},
            )
            self.assertIn(
                bible["character_identity_locks"][0]["presentation"],
                {"MASCULINE", "FEMININE", "ANDROGYNOUS", "UNSPECIFIED"},
            )
            self.assertIn(
                plan["assets"][0]["landscape_image"]["quality_assessment"]["structured_visual_qa"]["status"],
                {"ASSESSED_PASS", "NOT_ASSESSED"},
            )

    def test_stage2_continues_blocked_fixture_package_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1_package = self._stage1(root)
            workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage2-blocked-fixture")
            result = Stage2Pipeline().run(Stage2Request(stage1_package), workspace)
            with zipfile.ZipFile(result.package.archive_path) as archive:
                manifest = json.loads(archive.read("workflow_manifest.json"))
            self.assertEqual(manifest["allowed_next_stage"], "STAGE3")

    def test_scene_mode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1_package = self._stage1(root)
            workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage2-scene")
            with self.assertRaises(WorkflowError):
                Stage2Pipeline().run(Stage2Request(stage1_package, "SCENE", allow_blocked_fixture_for_testing=True), workspace)

    def test_optional_gpt_image_web_assist_exports_and_applies_reviewed_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1_package = self._stage1(root)
            stage2_workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-assist-source")
            stage2 = Stage2Pipeline().run(
                Stage2Request(stage1_package, allow_blocked_fixture_for_testing=True),
                stage2_workspace,
            )
            bundle = root / "assist"
            exported = GPTImageWebAssist().export(
                Path(stage2.package.archive_path), bundle, ["opening.png"]
            )
            self.assertEqual(exported["asset_count"], 1)
            self.assertTrue((bundle / "prompts" / "opening.txt").is_file())
            self.assertIn("MANUAL_OPTIONAL_NO_API", (bundle / "assist_manifest.json").read_text())

            image = Image.new("RGB", (2, 2))
            image.putdata([(20, 30, 40), (220, 40, 80), (30, 210, 100), (220, 220, 180)])
            image = image.resize((3840, 2160), Image.Resampling.BILINEAR)
            image.save(bundle / "results" / "opening.png", format="PNG")
            repair_workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-assist-repair")
            applied = GPTImageWebAssist().apply(
                Path(stage2.package.archive_path), bundle, repair_workspace,
                human_reviewed=True,
            )
            repaired = Path(applied["package"]["archive_path"])
            verified = PackageVerifier().verify(repaired)
            self.assertEqual(verified.package_stage, "STAGE2")
            with zipfile.ZipFile(repaired) as archive:
                manifest = json.loads(archive.read("workflow_manifest.json"))
                plan = json.loads(archive.read("visual_plan.json"))
            self.assertEqual(manifest["operation_mode"], "REPAIR")
            opening = next(item for item in plan["assets"] if item["basename"] == "opening.png")
            assessment = opening["landscape_image"]["quality_assessment"]
            self.assertEqual(assessment["method"], "GPT_IMAGE_WEB_HUMAN_ASSIST_TECHNICAL")
            self.assertTrue(assessment["assist_provenance"]["human_review_confirmed"])

    def test_transaction_retries_without_duplicate_commit(self) -> None:
        class RetryOnceProvider(DeterministicLandscapeProvider):
            provider_id = "retry-once-provider/1.0"

            def generate(self, **kwargs):
                if kwargs["basename"] == "cover.png" and kwargs["attempt"] == 1:
                    return b"invalid-png"
                return super().generate(**kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1_package = self._stage1(root)
            workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage2-retry")
            result = Stage2Pipeline(RetryOnceProvider()).run(
                Stage2Request(stage1_package, allow_blocked_fixture_for_testing=True), workspace
            )
            self.assertEqual(result.committed_assets, 10)
            self.assertEqual(result.generation_calls, 11)
            with zipfile.ZipFile(result.package.archive_path) as archive:
                plan = json.loads(archive.read("visual_plan.json"))
            history = plan["assets"][0]["landscape_image"]["quality_assessment"]["repair_history"]
            self.assertEqual(history[0]["repair_plan"]["planner"], "RULE_BASED_LAYERED_IMAGE_REPAIR_V2")
            self.assertEqual(history[0]["repair_plan"]["attempt"], 1)

    def test_failed_stage2_resumes_from_committed_asset(self) -> None:
        class FailAfterCover(DeterministicLandscapeProvider):
            def __init__(self): self.calls = []
            def generate(self, **kwargs):
                self.calls.append(kwargs["basename"])
                if kwargs["basename"] == "greeting.png":
                    return b"invalid-png"
                return super().generate(**kwargs)

        class RecordingProvider(DeterministicLandscapeProvider):
            def __init__(self): self.calls = []
            def generate(self, **kwargs):
                self.calls.append(kwargs["basename"])
                return super().generate(**kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1_package = self._stage1(root)
            workspace = RunWorkspace.create(root, Profile.YOUTH_SAFE, "run-stage2-resume")
            first = FailAfterCover()
            with self.assertRaises(Exception):
                Stage2Pipeline(first).run(Stage2Request(stage1_package, allow_blocked_fixture_for_testing=True), workspace)
            self.assertTrue((workspace.root / "stage2_checkpoint.json").is_file())
            self.assertTrue((workspace.work_dir / "landscape" / "cover.png").is_file())

            second = RecordingProvider()
            result = Stage2Pipeline(second).run(Stage2Request(stage1_package, allow_blocked_fixture_for_testing=True), workspace)
            self.assertNotIn("cover.png", second.calls)
            self.assertEqual(result.committed_assets, 10)
            self.assertFalse((workspace.root / "stage2_checkpoint.json").exists())


if __name__ == "__main__":
    unittest.main()
