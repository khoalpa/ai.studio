from __future__ import annotations

import argparse
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
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/story"
TARGET_PATH = BASELINE_ROOT / "phase1/regression-target.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the immutable Phase 1 targeted story regression set."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--phase", choices=("phase2a", "phase2b", "phase2c", "phase2d", "phase2e"), default="phase2a",
        help="Output namespace; defaults to phase2a for backward compatibility.",
    )
    parser.add_argument(
        "--recover-from", type=Path,
        help="Prior targeted-run root whose completed work/story is used as a checkpoint.",
    )
    parser.add_argument(
        "--reuse-record-from", type=Path,
        help="Prior targeted-run root whose matching record/package may be reused verbatim.",
    )
    parser.add_argument(
        "--reuse-case", action="append", default=[],
        help="Case allowed to reuse from --reuse-record-from; repeat as needed.",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run one target case; repeat to select multiple. Defaults to all target cases.",
    )
    parser.add_argument("--list", action="store_true", help="List selected cases and exit.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target = json.loads(TARGET_PATH.read_text(encoding="utf-8"))
    available = {str(item["case_id"]): item for item in target["cases"]}
    selected_ids = args.case_ids or list(available)
    unknown = sorted(set(selected_ids) - set(available))
    if unknown:
        raise RuntimeError(f"Cases are not in the Phase 1 regression target: {unknown}")
    selected = [available[case_id] for case_id in selected_ids]
    if args.list:
        print(json.dumps({"cases": selected_ids}, ensure_ascii=False, indent=2))
        return

    output_root = BASELINE_ROOT / args.phase / args.run_id
    records_dir = output_root / "records"
    packages_dir = output_root / "packages"
    runs_dir = output_root / "runs"
    for directory in (records_dir, packages_dir, runs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    evaluator = BenchmarkEvaluator()
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

    for position, target_case in enumerate(selected, 1):
        case_id = str(target_case["case_id"])
        case = evaluator.case(case_id)
        record_path = records_dir / f"{case_id}.json"
        package_export = packages_dir / f"{case_id}.zip"
        if record_path.is_file():
            evaluator.validate_canonical_record(evaluator.load_records(record_path)[0])
            if not package_export.is_file():
                raise RuntimeError(f"Package is missing for resumable record: {case_id}")
            print(json.dumps({"case": case_id, "position": position, "status": "RESUMED"}))
            continue
        if args.reuse_record_from and case_id in args.reuse_case:
            reused_record = args.reuse_record_from / "records" / f"{case_id}.json"
            reused_package = args.reuse_record_from / "packages" / f"{case_id}.zip"
            if reused_record.is_file() and reused_package.is_file():
                shutil.copy2(reused_record, record_path)
                shutil.copy2(reused_package, package_export)
                evaluator.validate_canonical_record(evaluator.load_records(record_path)[0])
                print(json.dumps({
                    "case": case_id, "position": position, "status": "REUSED_RECORD",
                }))
                continue

        run_id = f"{args.run_id}-{case_id}"
        workspace = (
            RunWorkspace.open(runs_dir, run_id)
            if (runs_dir / run_id).exists()
            else RunWorkspace.create(runs_dir, Profile(case["profile"]), run_id)
        )
        completed_package = workspace.output_dir / "story.zip"
        if completed_package.is_file() and not (workspace.root / "stage1_checkpoint.json").exists():
            shutil.copy2(completed_package, package_export)
            evaluator.write_case_record(case_id, package_export, record_path)
            continue

        profile = Profile(case["profile"])
        request = Stage1Request(
            profile=profile,
            brief=case["brief"],
            duration=confirm_duration(
                profile, case["minutes"], case.get("episode_mode")
            ),
            language=case["language"],
            episode_mode=case.get("episode_mode"),
            series_title=case.get("series_title"),
            benchmark_case_id=case_id,
            generation_seed=case["seed"],
            benchmark_corpus_digest=evaluator.canonical_corpus_digest(),
        )
        checkpoint_path = workspace.root / "stage1_checkpoint.json"
        if args.recover_from and not checkpoint_path.exists():
            source_run = args.recover_from / "runs" / f"{args.recover_from.name}-{case_id}"
            source_story = source_run / "work" / "story.json"
            source_contract = source_run / "work" / "story_contract.json"
            if not source_story.is_file() or not source_contract.is_file():
                raise RuntimeError(f"Recovery source is incomplete: {source_run}")
            story = json.loads(source_story.read_text(encoding="utf-8"))
            contract = json.loads(source_contract.read_text(encoding="utf-8"))
            pixel_hashes: dict[str, str] = {}
            for character in story["characters"]:
                reference = character["reference_asset"]
                relative = str(reference["reference_image"])
                target_image = workspace.work_dir / relative
                target_image.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_run / "work" / relative, target_image)
                pixel_hashes[relative] = str(reference["pixel_sha256"])
            Stage1Pipeline._write_checkpoint(
                checkpoint_path,
                Stage1Pipeline._request_digest(request),
                "CHARACTER_IMAGES_CREATED",
                story,
                contract,
                pixel_hashes,
            )
            workspace.log("STAGE1_RECOVERY_CHECKPOINT_CREATED", {
                "source_run_id": source_run.name,
                "phase": "CHARACTER_IMAGES_CREATED",
            })
        result = Stage1Pipeline(
            provider_mode="local",
            model_overrides={"story": story_model, "character_image": image_model},
            quality_preset="quality",
            runtime_preparer=prepare_runtime,
        ).run(request, workspace)
        shutil.copy2(Path(result.package.archive_path), package_export)
        record = evaluator.write_case_record(case_id, package_export, record_path)
        print(json.dumps({
            "case": case_id,
            "position": position,
            "status": "GENERATED",
            "blocker_count": record["blocker_count"],
            "outcome_compliant": record["outcome_compliant"],
        }))

    records = evaluator.load_records(records_dir)
    result_path = output_root / "result.json"
    result_document = {
        "schema_version": "1.0",
        "report_kind": "TARGETED_REGRESSION_RESULT",
        "run_id": args.run_id,
        "source_target_digest_sha256": target["report_digest_sha256"],
        "source_baseline_report_digest_sha256": target[
            "source_baseline_report_digest_sha256"
        ],
        "selected_case_ids": selected_ids,
        "metrics": evaluator.summarize(records),
        "records": records,
    }
    result_path.write_text(
        json.dumps(result_document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({
        "status": "COMPLETE",
        "case_count": len(records),
        "result": str(result_path),
    }))


if __name__ == "__main__":
    main()
