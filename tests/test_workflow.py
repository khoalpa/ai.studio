from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ai_story.archive import PackageBuilder, PackageVerifier, extract_inherited
from ai_story.errors import PackageError, TransitionError
from ai_story.models import Operation, Profile, Stage
from ai_story.state_machine import TransitionRequest, WorkflowStateMachine
from ai_story.validation_ledger import write_ledger
from ai_story.workspace import RunWorkspace


def write_stage1(
    root: Path,
    artifact_class: str = "PRODUCTION_CANDIDATE",
    advancement_status: str = "ALLOWED",
) -> None:
    (root / "characters").mkdir(parents=True)
    (root / "story.json").write_text('{"schema_version":"2.3"}', encoding="utf-8")
    (root / "story_validation.json").write_text('{"schema_version":"2.0"}', encoding="utf-8")
    contract = {
        "schema_version": "1.0", "language": "vi", "scenario": "GENERAL",
        "entities": [], "relationships": [], "requirements": [], "invariants": [],
        "forbidden_outcomes": [],
    }
    contract_bytes = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (root / "story_contract.json").write_bytes(contract_bytes)
    (root / "outline_evidence.json").write_text(json.dumps({
        "schema_version": "1.0",
        "story_contract_digest_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "requirement_bindings": [],
        "unbound_requirement_count": 0,
    }, separators=(",", ":")), encoding="utf-8")
    decision = {
        "schema_version": "1.0", "workflow_status": "SUCCEEDED", "technical_status": "PASS",
        "safety_status": "PASS", "editorial_status": "NOT_ASSESSED", "release_status": "BLOCKED",
        "advancement_status": advancement_status,
        "continuation_policy": "BLOCKED" if advancement_status == "BLOCKED" else "CONTINUE_WITH_WARNINGS",
        "artifact_class": artifact_class,
        "assessment_basis": "DETERMINISTIC_PREFLIGHT_ONLY", "failed_gate_ids": [],
        "warning_count": 0, "evidence_ids": [], "reasons": [], "decision_digest_sha256": None,
    }
    decision["decision_digest_sha256"] = hashlib.sha256(
        json.dumps(decision, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    (root / "quality_decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    write_ledger(root / "validation_ledger.json", "STAGE1", [])
    (root / "characters" / "hero.png").write_bytes(b"fake-png-for-workflow-test")


def add_stage2(root: Path) -> None:
    (root / "visual_plan.json").write_text('{"resolved_mode":"ZONE"}', encoding="utf-8")
    (root / "visual_bible.json").write_text('{"schema_version":"1.0"}', encoding="utf-8")
    landscape = root / "landscape"
    landscape.mkdir()
    for basename in (
        "cover.png", "greeting.png", "opening.png", "introduction.png", "development.png",
        "climax.png", "falling.png", "ending.png", "farewell.png", "outro.png",
    ):
        (landscape / basename).write_bytes(f"landscape:{basename}".encode())


class WorkflowTests(unittest.TestCase):
    def test_state_machine_rejects_skip(self) -> None:
        request = TransitionRequest(
            Profile.YOUTH_SAFE, Stage.STAGE3, Operation.CREATE, source_stage=Stage.STAGE1
        )
        with self.assertRaises(TransitionError):
            WorkflowStateMachine().validate(request)

    def test_workspace_is_isolated_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = RunWorkspace.create(
                Path(temporary), Profile.YOUTH_SAFE, run_id="run-test-0001"
            )
            self.assertTrue(workspace.input_dir.is_dir())
            self.assertTrue((workspace.logs_dir / "events.ndjson").is_file())
            metadata = json.loads((workspace.root / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "INITIALIZED")
            workspace.update_status("FAILED", progress_percent=42)
            reopened = RunWorkspace.open(Path(temporary), "run-test-0001")
            updated = json.loads((reopened.root / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["status"], "FAILED")
            self.assertEqual(updated["progress_percent"], 42)

    def test_build_reopen_and_inherit_stage1(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            write_stage1(source)
            archive = root / "story.zip"
            result = PackageBuilder().build(
                source_dir=source,
                output_path=archive,
                stage=Stage.STAGE1,
                operation=Operation.CREATE,
                profile=Profile.YOUTH_SAFE,
            )
            self.assertEqual(result.package_stage, "STAGE1")
            self.assertEqual(result.file_count, 8)
            inherited = root / "inherited"
            digest = extract_inherited(archive, inherited)
            self.assertEqual(digest, result.package_digest_sha256)
            self.assertFalse((inherited / "workflow_manifest.json").exists())
            self.assertTrue((inherited / "story.json").exists())

    def test_stage2_preserves_inherited_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage1_source = root / "stage1"
            stage1_source.mkdir()
            write_stage1(stage1_source)
            stage1_zip = root / "stage1.zip"
            first = PackageBuilder().build(
                source_dir=stage1_source,
                output_path=stage1_zip,
                stage=Stage.STAGE1,
                operation=Operation.CREATE,
                profile=Profile.ADULT_STANDARD,
            )
            stage2_source = root / "stage2"
            parent_digest = extract_inherited(stage1_zip, stage2_source)
            add_stage2(stage2_source)
            stage2_zip = root / "stage2.zip"
            second = PackageBuilder().build(
                source_dir=stage2_source,
                output_path=stage2_zip,
                stage=Stage.STAGE2,
                operation=Operation.CREATE,
                profile=Profile.ADULT_STANDARD,
                source_stage=Stage.STAGE1,
                parent_package_digest_sha256=parent_digest,
            )
            self.assertEqual(second.package_stage, "STAGE2")
            with zipfile.ZipFile(stage1_zip) as old, zipfile.ZipFile(stage2_zip) as new:
                self.assertEqual(old.read("story.json"), new.read("story.json"))
                manifest = json.loads(new.read("workflow_manifest.json"))
                self.assertEqual(manifest["parent_package_digest_sha256"], first.package_digest_sha256)

    def test_missing_required_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "story.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(Exception):
                PackageBuilder().build(
                    source_dir=source,
                    output_path=Path(temporary) / "story.zip",
                    stage=Stage.STAGE1,
                    operation=Operation.CREATE,
                    profile=Profile.YOUTH_SAFE,
                )

    def test_zip_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../escape.txt", b"bad")
            with self.assertRaises(Exception):
                PackageVerifier().verify(archive)

    def test_stage1_parent_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            write_stage1(source)
            with self.assertRaises(PackageError):
                PackageBuilder().build(
                    source_dir=source,
                    output_path=Path(temporary) / "story.zip",
                    stage=Stage.STAGE1,
                    operation=Operation.CREATE,
                    profile=Profile.YOUTH_SAFE,
                    parent_package_digest_sha256="a" * 64,
                )

    def test_test_fixture_can_advance_with_advisory_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            write_stage1(source, artifact_class="TEST_FIXTURE")
            result = PackageBuilder().build(
                source_dir=source,
                output_path=Path(temporary) / "story.zip",
                stage=Stage.STAGE1,
                operation=Operation.CREATE,
                profile=Profile.YOUTH_SAFE,
                artifact_class="TEST_FIXTURE",
                content_quality_status="BLOCKED",
                allow_next_stage=True,
            )
            with zipfile.ZipFile(result.archive_path) as archive:
                manifest = json.loads(archive.read("workflow_manifest.json"))
            self.assertEqual(manifest["allowed_next_stage"], "STAGE2")

    def test_quality_blocked_package_cannot_claim_advancement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            write_stage1(source, advancement_status="BLOCKED")
            result = PackageBuilder().build(
                source_dir=source,
                output_path=Path(temporary) / "story.zip",
                stage=Stage.STAGE1,
                operation=Operation.CREATE,
                profile=Profile.YOUTH_SAFE,
                content_quality_status="BLOCKED",
                allow_next_stage=False,
            )
            with zipfile.ZipFile(result.archive_path) as archive:
                manifest = json.loads(archive.read("workflow_manifest.json"))
            self.assertIsNone(manifest["allowed_next_stage"])
            self.assertEqual(manifest["validation"]["execution_status"], "COMPLETED_WITH_WARNINGS")
            self.assertEqual(manifest["validation"]["continuation_policy"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
