from __future__ import annotations

import json
import shutil
from pathlib import Path

from ai_story.local_models import LocalModelManager
from ai_story.local_runtime import LlamaServerSupervisor
from ai_story.model_operations import BenchmarkEvaluator
from ai_story.models import Profile
from ai_story.stage1 import Stage1Pipeline, Stage1Request
from ai_story.stage1.config import confirm_duration
from ai_story.workspace import RunWorkspace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / ".runtime"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/story"
SEED_PACKAGES = {
    "youth-torn-paper-boat": (
        PROJECT_ROOT
        / "artifacts/baselines/real-v1/canary-quality-v9-resume"
        / "run-20261002081639-14506b07/output/story.zip"
    ),
    "adult-memory-choice": (
        PROJECT_ROOT
        / "artifacts/baselines/real-v1/mini-corpus/adult-memory-choice-repair"
        / "adult-memory-choice-repair-v8/output/story.zip"
    ),
    "serial-locked-room": (
        PROJECT_ROOT
        / "artifacts/baselines/real-v1/mini-corpus/serial-locked-room-repair"
        / "serial-locked-room-repair-v6/output/story.zip"
    ),
}


def main() -> None:
    evaluator = BenchmarkEvaluator()
    plan = evaluator.plan()
    records_dir = OUTPUT_ROOT / "records"
    packages_dir = OUTPUT_ROOT / "packages"
    runs_dir = OUTPUT_ROOT / "runs"
    for directory in (records_dir, packages_dir, runs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for case_id, source_package in SEED_PACKAGES.items():
        record_path = records_dir / f"{case_id}.json"
        package_path = packages_dir / f"{case_id}.zip"
        if not record_path.exists():
            if not source_package.is_file():
                raise RuntimeError(f"Seed package is missing: {source_package}")
            shutil.copy2(source_package, package_path)
            evaluator.write_case_record(case_id, package_path, record_path)
        evaluator.validate_canonical_record(evaluator.load_records(record_path)[0])

    models = LocalModelManager(RUNTIME_ROOT)
    story_model = models.active_model("story")
    image_model = models.active_model("character_image")
    if story_model is None or image_model is None:
        raise RuntimeError("Active story and character-image models are required")
    supervisor = LlamaServerSupervisor(RUNTIME_ROOT)

    def prepare_runtime(role: str, binding: dict[str, object]) -> None:
        if role == "story":
            supervisor.ensure(
                story_model,
                timeout_seconds=180,
                force_restart=binding.get("recovery_reason") in {
                    "HARD_TIMEOUT", "CIRCUIT_OPEN",
                },
            )

    for position, case in enumerate(plan["cases"], 1):
        case_id = case["id"]
        record_path = records_dir / f"{case_id}.json"
        package_export = packages_dir / f"{case_id}.zip"
        if record_path.exists():
            evaluator.validate_canonical_record(evaluator.load_records(record_path)[0])
            if not package_export.is_file():
                raise RuntimeError(f"Package is missing for resumable record: {case_id}")
            print(json.dumps({"case": case_id, "position": position, "status": "RESUMED"}))
            continue

        run_id = f"benchmark-{case_id}"
        workspace = (
            RunWorkspace.open(runs_dir, run_id)
            if (runs_dir / run_id).exists()
            else RunWorkspace.create(runs_dir, Profile(case["profile"]), run_id)
        )
        completed_package = workspace.output_dir / "story.zip"
        if completed_package.is_file() and not (workspace.root / "stage1_checkpoint.json").exists():
            shutil.copy2(completed_package, package_export)
            evaluator.write_case_record(case_id, package_export, record_path)
            print(json.dumps({"case": case_id, "position": position, "status": "RECOVERED_OUTPUT"}))
            continue

        profile = Profile(case["profile"])
        result = Stage1Pipeline(
            provider_mode="local",
            model_overrides={"story": story_model, "character_image": image_model},
            quality_preset="quality",
            runtime_preparer=prepare_runtime,
        ).run(
            Stage1Request(
                profile=profile,
                brief=case["brief"],
                duration=confirm_duration(profile, case["minutes"], case.get("episode_mode")),
                language=case["language"],
                episode_mode=case.get("episode_mode"),
                series_title=case.get("series_title"),
                benchmark_case_id=case_id,
                generation_seed=case["seed"],
                benchmark_corpus_digest=evaluator.canonical_corpus_digest(),
            ),
            workspace,
        )
        shutil.copy2(Path(result.package.archive_path), package_export)
        record = evaluator.write_case_record(case_id, package_export, record_path)
        print(json.dumps({
            "case": case_id,
            "position": position,
            "status": "GENERATED",
            "blocker_count": record["blocker_count"],
            "advancement_allowed": record["advancement_allowed"],
        }))

    records = evaluator.load_records(records_dir)
    baseline_path = OUTPUT_ROOT / "baseline.json"
    if not baseline_path.exists():
        evaluator.write_baseline_report(records, baseline_path)
        evaluator.write_human_review_template(
            records, "reviewer-a", OUTPUT_ROOT / "reviews/reviewer-a.json"
        )
        evaluator.write_human_review_template(
            records, "reviewer-b", OUTPUT_ROOT / "reviews/reviewer-b.json"
        )
    print(json.dumps({
        "status": "COMPLETE",
        "case_count": len(records),
        "baseline_path": str(baseline_path),
    }))


if __name__ == "__main__":
    main()
