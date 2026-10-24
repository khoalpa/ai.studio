from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from collections import Counter
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 3 recovery over the 27-case corpus.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--case-id", action="append", dest="case_ids",
        help="Run only this benchmark case; repeat for a targeted canary set.",
    )
    parser.add_argument(
        "--source-run-id",
        help="Prefer packages from this prior Phase 3 run before Phase 2E/baseline packages.",
    )
    parser.add_argument(
        "--case-source-run-id", action="append", default=[], metavar="CASE=RUN",
        help="Override the source run for one case; repeat for targeted checkpoint chaining.",
    )
    parser.add_argument(
        "--case-brief-override", action="append", default=[], metavar="CASE=BRIEF",
        help="Use a repaired brief for one recovery case without changing the benchmark corpus.",
    )
    parser.add_argument(
        "--surgical-only", action="store_true",
        help="Disable model repair/finalizer loops; allow only locator-bound deterministic repair.",
    )
    parser.add_argument(
        "--stop-on-p0", action="store_true",
        help="Stop the controlled recovery pilot immediately if a recovered package exposes a P0 defect.",
    )
    parser.add_argument(
        "--max-consecutive-no-improvement", type=int, default=0,
        help="Stop after this many consecutive cases fail to reduce blocker count (0 disables).",
    )
    return parser.parse_args()


def source_package(case_id: str, source_run_id: str | None = None) -> Path:
    if source_run_id:
        phase3 = BASELINE_ROOT / "phase3" / source_run_id / "packages" / f"{case_id}.zip"
        if phase3.is_file():
            return phase3
    phase2e = (
        BASELINE_ROOT / "phase2e/phase2e-surgical-repair-v2/packages" / f"{case_id}.zip"
    )
    return phase2e if phase2e.is_file() else BASELINE_ROOT / "packages" / f"{case_id}.zip"


def main() -> None:
    args = parse_args()
    case_source_runs: dict[str, str] = {}
    for value in args.case_source_run_id:
        if "=" not in value:
            raise ValueError("--case-source-run-id must use CASE=RUN")
        case_id, run_id = value.split("=", 1)
        case_source_runs[case_id] = run_id
    case_brief_overrides: dict[str, str] = {}
    for value in args.case_brief_override:
        if "=" not in value:
            raise ValueError("--case-brief-override must use CASE=BRIEF")
        case_id, brief = value.split("=", 1)
        if not brief.strip():
            raise ValueError("--case-brief-override requires a non-empty brief")
        case_brief_overrides[case_id] = brief.strip()
    evaluator = BenchmarkEvaluator()
    plan = evaluator.plan()
    selected_ids = set(args.case_ids or [])
    known_ids = {str(case["id"]) for case in plan["cases"]}
    unknown_ids = selected_ids - known_ids
    unknown_ids.update(set(case_source_runs) - known_ids)
    unknown_ids.update(set(case_brief_overrides) - known_ids)
    if unknown_ids:
        raise ValueError(f"Unknown benchmark case ids: {sorted(unknown_ids)}")
    cases = [
        case for case in plan["cases"]
        if not selected_ids or str(case["id"]) in selected_ids
    ]
    output_root = BASELINE_ROOT / "phase3" / args.run_id
    records_dir = output_root / "records"
    packages_dir = output_root / "packages"
    runs_dir = output_root / "runs"
    for directory in (records_dir, packages_dir, runs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    models = LocalModelManager(RUNTIME_ROOT)
    story_model = models.active_model("story")
    image_model = models.active_model("character_image")
    if story_model is None or image_model is None:
        raise RuntimeError("Active story and character-image models are required")
    supervisor = LlamaServerSupervisor(RUNTIME_ROOT)
    pilot_observations: list[dict[str, object]] = []
    consecutive_no_improvement = 0
    stop_reason: str | None = None

    def prepare_runtime(role: str, binding: dict[str, object]) -> None:
        if role == "story":
            supervisor.ensure(
                story_model,
                timeout_seconds=180,
                force_restart=binding.get("recovery_reason") in {
                    "HARD_TIMEOUT", "CIRCUIT_OPEN",
                },
            )

    for position, case in enumerate(cases, 1):
        case_id = str(case["id"])
        record_path = records_dir / f"{case_id}.json"
        package_export = packages_dir / f"{case_id}.zip"
        if record_path.is_file() and package_export.is_file():
            resumed_record = evaluator.load_records(record_path)[0]
            evaluator.validate_canonical_record(resumed_record)
            print(json.dumps({"case": case_id, "position": position, "status": "RESUMED"}))
            continue

        package = source_package(
            case_id, case_source_runs.get(case_id, args.source_run_id)
        )
        if not package.is_file():
            raise RuntimeError(f"Recovery package is missing: {package}")
        source_record = evaluator.record_from_package(
            case, package, seed=int(case["seed"]),
        )

        profile = Profile(case["profile"])
        request = Stage1Request(
            profile=profile,
            brief=case_brief_overrides.get(case_id, case["brief"]),
            duration=confirm_duration(profile, case["minutes"], case.get("episode_mode")),
            language=case["language"],
            episode_mode=case.get("episode_mode"),
            series_title=case.get("series_title"),
            benchmark_case_id=case_id,
            generation_seed=case["seed"],
            benchmark_corpus_digest=evaluator.canonical_corpus_digest(),
        )
        run_id = f"{args.run_id}-{case_id}"
        workspace = (
            RunWorkspace.open(runs_dir, run_id)
            if (runs_dir / run_id).exists()
            else RunWorkspace.create(runs_dir, profile, run_id)
        )
        checkpoint_path = workspace.root / "stage1_checkpoint.json"
        if not checkpoint_path.exists():
            with zipfile.ZipFile(package) as archive:
                story = json.loads(archive.read("story.json"))
                contract = json.loads(archive.read("story_contract.json"))
                pixel_hashes: dict[str, str] = {}
                for character in story["characters"]:
                    reference = character["reference_asset"]
                    relative = str(reference["reference_image"])
                    target = workspace.work_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(relative))
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
                "source_package": str(package),
                "phase": "CHARACTER_IMAGES_CREATED",
            })

        result = Stage1Pipeline(
            provider_mode="local",
            model_overrides={"story": story_model, "character_image": image_model},
            quality_preset="quality",
            runtime_preparer=prepare_runtime,
            repair_strategy="surgical_only" if args.surgical_only else "full",
        ).run(request, workspace)
        shutil.copy2(Path(result.package.archive_path), package_export)
        record = evaluator.write_case_record(case_id, package_export, record_path)
        blockers_before = int(source_record["blocker_count"])
        blockers_after = int(record["blocker_count"])
        improved = blockers_after < blockers_before
        consecutive_no_improvement = 0 if improved else consecutive_no_improvement + 1
        observation = {
            "case_id": case_id,
            "source_package": str(package),
            "blockers_before": blockers_before,
            "blockers_after": blockers_after,
            "blockers_removed": blockers_before - blockers_after,
            "improved": improved,
            "p0_defect_count": int(record["p0_defect_count"]),
        }
        pilot_observations.append(observation)
        print(json.dumps({
            "case": case_id,
            "position": position,
            "status": "RECOVERED",
            "blocker_count_before": blockers_before,
            "blocker_count": blockers_after,
            "improved": improved,
            "advancement_allowed": record["advancement_allowed"],
        }))
        if args.stop_on_p0 and int(record["p0_defect_count"]) > 0:
            stop_reason = f"P0_DEFECT:{case_id}"
            break
        if (
            args.max_consecutive_no_improvement > 0
            and consecutive_no_improvement >= args.max_consecutive_no_improvement
        ):
            stop_reason = (
                "CONSECUTIVE_NO_IMPROVEMENT:"
                f"{args.max_consecutive_no_improvement}"
            )
            break

    records = evaluator.load_records(records_dir)
    result = {
        "schema_version": "1.0",
        "report_kind": "PHASE3_RECOVERY_REGRESSION",
        "run_id": args.run_id,
        "controlled_recovery": {
            "requested_case_count": len(cases),
            "executed_case_count": len(pilot_observations),
            "surgical_only": bool(args.surgical_only),
            "stop_on_p0": bool(args.stop_on_p0),
            "max_consecutive_no_improvement": args.max_consecutive_no_improvement,
            "stop_reason": stop_reason,
            "observations": pilot_observations,
        },
        "metrics": evaluator.summarize(records),
        "records": records,
    }
    (output_root / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )

    statuses: Counter[str] = Counter()
    encoding_warning_count = 0
    character_count = 0
    for package in packages_dir.glob("*.zip"):
        with zipfile.ZipFile(package) as archive:
            story = json.loads(archive.read("story.json"))
        for character in story.get("characters", []):
            character_count += 1
            assessment = character.get("reference_asset", {}).get("quality_assessment", {})
            statuses[str(assessment.get("status", "MISSING"))] += 1
            visual = json.dumps(character.get("visual_identity", {}), ensure_ascii=False)
            encoding_warning_count += visual.count("�")
    visual_audit = {
        "schema_version": "1.0",
        "report_kind": "PHASE3_VISUAL_SIGNAL_AUDIT",
        "character_count": character_count,
        "quality_status_counts": dict(sorted(statuses.items())),
        "encoding_replacement_character_count": encoding_warning_count,
        "manual_realism_review_required": True,
        "note": "Automated package audit; realism and cross-image identity require sampled visual review.",
    }
    (output_root / "visual_audit.json").write_text(
        json.dumps(visual_audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({
        "status": "STOPPED" if stop_reason else "COMPLETE", "case_count": len(records),
        "stop_reason": stop_reason,
        "result": str(output_root / "result.json"),
        "visual_audit": str(output_root / "visual_audit.json"),
    }))


if __name__ == "__main__":
    main()
