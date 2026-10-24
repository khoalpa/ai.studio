from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..archive import PackageBuilder, PackageVerifier, extract_inherited
from ..errors import WorkflowError
from ..hashing import sha256_file
from ..models import Operation, PackageResult, Profile, Stage
from ..provider_config import generation_metadata, merge_generation_metadata
from ..validation_ledger import LEDGER_PATH, stage4_records, write_ledger
from ..workspace import RunWorkspace
from .builder import build_video_prompts
from .config import stage4_config, validate_options
from .production import build_production_plan
from .production_validation import validate_production_plan
from .subtitles import derive_subtitles, render_srt, render_webvtt
from .timeline import derive_timeline
from .tts import render_tts, voice_inventory
from .validation import validate_video_prompts


@dataclass(frozen=True)
class Stage4Request:
    input_package: Path
    aspect_ratio: str = "LANDSCAPE_16_9"
    coverage_mode: str = "FULL_STORY"
    confirm_large_plan: bool = False
    operation: Operation = Operation.CREATE
    render_tts: bool = False
    piper_voice_model: Path | None = None
    visual_review_approved: bool = False
    allow_blocked_fixture_for_testing: bool = False


@dataclass(frozen=True)
class Stage4Result:
    run_id: str
    video_prompts_path: str
    clip_count: int
    story_duration_seconds: float
    planned_video_duration_seconds: int
    package: PackageResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "video_prompts_path": self.video_prompts_path,
            "clip_count": self.clip_count,
            "story_duration_seconds": self.story_duration_seconds,
            "planned_video_duration_seconds": self.planned_video_duration_seconds,
            "package": self.package.to_dict(),
        }


class Stage4Pipeline:
    def run(self, request: Stage4Request, workspace: RunWorkspace) -> Stage4Result:
        if request.operation is not Operation.CREATE:
            raise WorkflowError("Stage 4 REPAIR is not enabled in this milestone")
        validate_options(request.aspect_ratio, request.coverage_mode)
        source = PackageVerifier().verify(request.input_package)
        if source.package_stage != Stage.STAGE3.value:
            raise WorkflowError("Stage 4 CREATE requires an authoritative STAGE3 package")
        manifest = self._read_manifest(request.input_package)
        if manifest.get("allowed_next_stage") != Stage.STAGE4.value:
            raise WorkflowError("Stage 3 package has no canonical Stage 4 transition")
        source_validation = manifest.get("validation", {})
        artifact_class = source_validation.get("artifact_class", "PRODUCTION_CANDIDATE")
        content_quality_status = source_validation.get("content_quality_status", "NOT_ASSESSED")
        profile = Profile(manifest["active_profile"])
        parent_digest = extract_inherited(request.input_package, workspace.work_dir)
        story = json.loads((workspace.work_dir / "story.json").read_text(encoding="utf-8"))
        story_validation = json.loads((workspace.work_dir / "story_validation.json").read_text(encoding="utf-8"))
        quality_report = json.loads((workspace.work_dir / "package_quality_report.json").read_text(encoding="utf-8"))
        visual_plan = json.loads((workspace.work_dir / "visual_plan.json").read_text(encoding="utf-8"))
        if quality_report["summary"]["publish_verdict"] != "PASS":
            workspace.log(
                "INHERITED_GATE_WARNINGS",
                {"count": len(quality_report.get("blockers", [])), "stage": "STAGE3"},
            )
        review_sample = quality_report.get("image_evidence", {}).get("visual_review_sample", [])
        if review_sample:
            approved = request.visual_review_approved
            review = {
                "schema_version": "1.0",
                "decision": "APPROVED" if approved else "PENDING",
                "review_method": (
                    "OPERATOR_EXPLICIT_CONFIRMATION" if approved else "NOT_REVIEWED"
                ),
                "approved_at_utc": datetime.now(timezone.utc).isoformat() if approved else None,
                "source_quality_report_sha256": sha256_file(workspace.work_dir / "package_quality_report.json"),
                "items": [
                    {
                        **self._review_item(workspace.work_dir, item),
                        "decision": "APPROVED" if approved else "PENDING",
                    }
                    for item in review_sample
                ],
            }
            (workspace.work_dir / "visual_review.json").write_text(
                json.dumps(review, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
            )
            workspace.log(
                "VISUAL_REVIEW_APPROVED" if approved else "VISUAL_REVIEW_WARNING",
                {"sample_count": len(review_sample), "decision": review["decision"]},
            )
        if visual_plan["resolved_mode"] != "ZONE":
            raise WorkflowError("Stage 4 MVP currently accepts ZONE visual plans only")

        segments, total_seconds = derive_timeline(story, profile.value)
        threshold = stage4_config()["large_plan_confirmation_threshold"]
        if len(segments) > threshold and not request.confirm_large_plan:
            raise WorkflowError(
                f"FULL_STORY requires explicit confirmation for {len(segments)} clips (threshold {threshold})"
            )
        workspace.log("STAGE4_STARTED", {"source_package_digest": parent_digest, "projected_clip_count": len(segments)})
        voice_locale = "vi-VN" if story["meta"]["language"] == "vi" else "en-US"
        inventory = voice_inventory(request.piper_voice_model, voice_locale)
        if request.render_tts and request.piper_voice_model is None:
            raise WorkflowError("--render-tts requires --piper-voice-model")
        document = build_video_prompts(
            root=workspace.work_dir,
            story=story,
            story_validation=story_validation,
            quality_report=quality_report,
            visual_plan=visual_plan,
            profile=profile.value,
            segments=segments,
            total_seconds=total_seconds,
            aspect_ratio=request.aspect_ratio,
            voice_inventory=inventory,
        )
        output_path = workspace.work_dir / "video_prompts.json"
        output_path.write_bytes(self._json_bytes(document))
        parsed = json.loads(output_path.read_text(encoding="utf-8"))
        validate_video_prompts(parsed, workspace.work_dir, segments)

        subtitles = derive_subtitles(parsed["clips"])
        (workspace.work_dir / "subtitles.srt").write_bytes(render_srt(subtitles))
        (workspace.work_dir / "subtitles.vtt").write_bytes(render_webvtt(subtitles))
        audio_records = (
            render_tts(
                workspace.work_dir,
                parsed["clips"],
                request.piper_voice_model,
                inventory,
            )
            if request.render_tts and request.piper_voice_model is not None
            else []
        )
        production = build_production_plan(
            root=workspace.work_dir,
            video_prompts=parsed,
            subtitles=subtitles,
            inventory=inventory,
            audio_records=audio_records,
        )
        production_path = workspace.work_dir / "production_plan.json"
        production_path.write_bytes(self._json_bytes(production))
        parsed_production = json.loads(production_path.read_text(encoding="utf-8"))
        validate_production_plan(parsed_production, workspace.work_dir, len(parsed["clips"]))
        review_document = json.loads(
            (workspace.work_dir / "visual_review.json").read_text(encoding="utf-8")
        )
        write_ledger(
            workspace.work_dir / LEDGER_PATH,
            "STAGE4",
            stage4_records(review_document, parsed_production),
        )

        package = PackageBuilder().build(
            source_dir=workspace.work_dir,
            output_path=workspace.output_dir / "story.zip",
            stage=Stage.STAGE4,
            operation=Operation.CREATE,
            profile=profile,
            parent_package_digest_sha256=parent_digest,
            source_stage=Stage.STAGE3,
            generation=merge_generation_metadata(
                manifest["generation"],
                generation_metadata(
                    [],
                    f"video-{stage4_config()['video_prompt_schema_version']}+production-{stage4_config()['production_plan_schema_version']}",
                    manifest["generation"].get("provider_mode"),
                ),
            ),
            allow_next_stage=False,
            artifact_class=artifact_class,
            content_quality_status=content_quality_status,
        )
        workspace.log("STAGE4_COMPLETED", package.to_dict())
        return Stage4Result(
            workspace.run_id,
            str(output_path),
            len(document["clips"]),
            total_seconds,
            document["project"]["planned_video_duration_seconds"],
            package,
        )

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        with zipfile.ZipFile(path, "r") as archive:
            return json.loads(archive.read("workflow_manifest.json").decode("utf-8"))

    @staticmethod
    def _review_item(root: Path, item: dict[str, Any]) -> dict[str, Any]:
        common = {
            "review_id": item["review_id"],
            "asset_type": item["asset_type"],
            "decision": "APPROVED",
            "review_reasons": item.get("review_reasons", []),
        }
        if item["asset_type"] == "CHARACTER_REFERENCE":
            return {
                **common,
                "character_id": item["character_id"],
                "reference_sha256": sha256_file(root / item["reference_path"]),
            }
        return {
            **common,
            "basename": item["basename"],
            "landscape_sha256": sha256_file(root / item["landscape_path"]),
            "portrait_sha256": sha256_file(root / item["portrait_path"]),
        }

    @staticmethod
    def _json_bytes(value: dict[str, Any]) -> bytes:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
