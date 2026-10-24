from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

from .archive import PackageBuilder, PackageVerifier
from .doctor import environment_report
from .errors import WorkflowError
from .gpt_image_web_assist import GPTImageWebAssist
from .image_baseline import ImageBaselineEvaluator
from .job_engine import read_job_history
from .local_models import LocalModelManager
from .model_cache import download_image_models, image_model_status
from .model_operations import QUALITY_PRESETS, BenchmarkEvaluator
from .models import Operation, Profile, Stage
from .operations import RunIndex
from .provider_config import PROVIDER_MODES, load_provider_config
from .real_baseline import RealBaselineEvaluator
from .release import ReleaseBundleBuilder, ReleaseBundleVerifier, ReleaseEvaluator
from .runtime import ProviderRuntimeRegistry
from .smoke import run_deterministic_smoke
from .stage1 import Stage1Pipeline, Stage1Request
from .stage1.config import confirm_duration, suggested_duration
from .stage2 import Stage2Pipeline, Stage2Request
from .stage3 import Stage3Pipeline, Stage3Request
from .stage4 import Stage4Pipeline, Stage4Request
from .workspace import RunWorkspace


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="ai-story")
    commands = root.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init-run", help="Create an isolated run workspace")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--profile", choices=[item.value for item in Profile], required=True)
    init.add_argument("--run-id")

    build = commands.add_parser("build-package", help="Build and reopen-verify story.zip")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--stage", choices=[item.value for item in Stage], required=True)
    build.add_argument("--operation", choices=[item.value for item in Operation], default="CREATE")
    build.add_argument("--profile", choices=[item.value for item in Profile], required=True)
    build.add_argument("--source-stage", choices=[item.value for item in Stage])
    build.add_argument("--parent-package-digest")

    verify = commands.add_parser("verify-package", help="Verify package integrity")
    verify.add_argument("archive", type=Path)

    inspect = commands.add_parser("inspect-package", help="Print the package manifest")
    inspect.add_argument("archive", type=Path)

    duration = commands.add_parser("suggest-duration", help="Show the canonical Stage 1 duration")
    duration.add_argument("--profile", choices=[item.value for item in Profile], required=True)
    duration.add_argument("--episode-mode", choices=["START_SERIES", "CONTINUE_SERIES", "FINALIZE_SERIES"])

    generate = commands.add_parser("generate-stage1", help="Generate and package Stage 1 with configured providers")
    generate.add_argument("--root", type=Path, required=True)
    generate.add_argument("--profile", choices=[item.value for item in Profile], required=True)
    generate.add_argument("--brief", required=True)
    generate.add_argument("--language", choices=["vi", "en"], default="vi")
    generate.add_argument("--minutes", type=int)
    generate.add_argument("--confirm-duration", action="store_true", required=True)
    generate.add_argument("--run-id")
    generate.add_argument("--episode-mode", choices=["START_SERIES", "CONTINUE_SERIES", "FINALIZE_SERIES"])
    generate.add_argument("--anchor", type=Path)
    generate.add_argument("--series-title")
    generate.add_argument("--planned-arc-episodes", type=int, default=12)
    generate.add_argument(
        "--provider-mode", choices=sorted(PROVIDER_MODES)
    )
    generate.add_argument("--quality-preset", choices=QUALITY_PRESETS, default="balanced")

    stage2 = commands.add_parser("generate-stage2", help="Generate Stage 2 ZONE landscape package")
    stage2.add_argument("--root", type=Path, required=True)
    stage2.add_argument("--input-package", type=Path, required=True)
    stage2.add_argument("--mode", choices=["ZONE", "SCENE"], default="ZONE")
    stage2.add_argument("--run-id")
    stage2.add_argument("--provider-mode", choices=sorted(PROVIDER_MODES))
    stage2.add_argument("--quality-preset", choices=QUALITY_PRESETS, default="balanced")

    stage3 = commands.add_parser("generate-stage3", help="Generate Stage 3 portrait package")
    stage3.add_argument("--root", type=Path, required=True)
    stage3.add_argument("--input-package", type=Path, required=True)
    stage3.add_argument("--run-id")
    stage3.add_argument("--provider-mode", choices=sorted(PROVIDER_MODES))
    stage3.add_argument("--quality-preset", choices=QUALITY_PRESETS, default="balanced")

    stage4 = commands.add_parser("generate-stage4", help="Generate canonical video_prompts.json package")
    stage4.add_argument("--root", type=Path, required=True)
    stage4.add_argument("--input-package", type=Path, required=True)
    stage4.add_argument("--aspect-ratio", choices=["LANDSCAPE_16_9", "PORTRAIT_9_16"], default="LANDSCAPE_16_9")
    stage4.add_argument("--coverage-mode", choices=["FULL_STORY"], default="FULL_STORY")
    stage4.add_argument("--confirm-large-plan", action="store_true")
    stage4.add_argument("--run-id")
    stage4.add_argument("--render-tts", action="store_true")
    stage4.add_argument("--piper-voice-model", type=Path)
    stage4.add_argument("--approve-visual-review", action="store_true")

    commands.add_parser("benchmark-plan", help="Print the canonical three-profile benchmark suite")
    generate_benchmark = commands.add_parser(
        "generate-benchmark-case", help="Generate a Stage 1 package bound to a canonical benchmark case"
    )
    generate_benchmark.add_argument("--root", type=Path, required=True)
    generate_benchmark.add_argument("--case-id", required=True)
    generate_benchmark.add_argument(
        "--provider-mode", choices=sorted(PROVIDER_MODES)
    )
    generate_benchmark.add_argument("--quality-preset", choices=QUALITY_PRESETS, default="balanced")
    record_case = commands.add_parser(
        "record-benchmark-case", help="Write immutable evidence for one Stage 1 benchmark package"
    )
    record_case.add_argument("--case-id", required=True)
    record_case.add_argument("--package", type=Path, required=True)
    record_case.add_argument("--output", type=Path, required=True)
    benchmark = commands.add_parser("evaluate-benchmark", help="Compare candidate metrics with a baseline")
    benchmark.add_argument("--candidate", type=Path, required=True)
    benchmark.add_argument("--baseline", type=Path, required=True)
    baseline = commands.add_parser(
        "summarize-benchmark", help="Write an immutable benchmark baseline report"
    )
    baseline.add_argument("--records", type=Path, required=True)
    baseline.add_argument("--output", type=Path, required=True)
    suite = commands.add_parser(
        "run-benchmark-suite",
        help="Generate, record and summarize the complete canonical benchmark in one command",
    )
    suite.add_argument("--output", type=Path, required=True)
    suite.add_argument(
        "--provider-mode", choices=sorted(PROVIDER_MODES)
    )
    suite.add_argument("--quality-preset", choices=QUALITY_PRESETS, default="balanced")
    suite.add_argument(
        "--resume", action="store_true",
        help="Resume an interrupted suite without overwriting existing case evidence",
    )
    human_reviews = commands.add_parser(
        "evaluate-human-reviews", help="Measure blocker agreement between two human reviewers"
    )
    human_reviews.add_argument("--review-a", type=Path, required=True)
    human_reviews.add_argument("--review-b", type=Path, required=True)
    human_reviews.add_argument("--output", type=Path, required=True)
    review_template = commands.add_parser(
        "create-human-review-template", help="Create a package-bound golden-set review template"
    )
    review_template.add_argument("--records", type=Path, required=True)
    review_template.add_argument("--reviewer-id", required=True)
    review_template.add_argument("--output", type=Path, required=True)

    commands.add_parser(
        "image-baseline-plan", help="Print the immutable visual golden-set baseline plan"
    )
    image_record = commands.add_parser(
        "record-image-baseline-case", help="Record visual evidence from one Stage 3 package"
    )
    image_record.add_argument("--case-id", required=True)
    image_record.add_argument("--package", type=Path, required=True)
    image_record.add_argument("--output", type=Path, required=True)
    image_summary = commands.add_parser(
        "summarize-image-baseline", help="Write an immutable visual baseline report"
    )
    image_summary.add_argument("--records", type=Path, required=True)
    image_summary.add_argument("--output", type=Path, required=True)
    image_review = commands.add_parser(
        "create-image-review-template", help="Create a digest-bound visual review form"
    )
    image_review.add_argument("--records", type=Path, required=True)
    image_review.add_argument("--reviewer-id", required=True)
    image_review.add_argument("--output", type=Path, required=True)
    image_review_report = commands.add_parser(
        "evaluate-image-reviews", help="Measure visual blocker agreement and human scores"
    )
    image_review_report.add_argument("--review-a", type=Path, required=True)
    image_review_report.add_argument("--review-b", type=Path, required=True)
    image_review_report.add_argument("--output", type=Path, required=True)
    image_compare = commands.add_parser(
        "evaluate-image-benchmark",
        help="Compare image baseline and candidate promotion evidence",
    )
    image_compare.add_argument("--baseline", type=Path, required=True)
    image_compare.add_argument("--candidate", type=Path, required=True)
    image_compare.add_argument("--human-review", type=Path)
    image_compare.add_argument("--output", type=Path, required=True)
    image_suite = commands.add_parser(
        "run-image-baseline-suite",
        help="Run Stage 2-3 for the visual golden set and lock its baseline",
    )
    image_suite.add_argument("--source-packages", type=Path, required=True)
    image_suite.add_argument("--output", type=Path, required=True)
    image_suite.add_argument(
        "--provider-mode", choices=sorted(PROVIDER_MODES), default="local"
    )
    image_suite.add_argument("--quality-preset", choices=QUALITY_PRESETS, default="balanced")
    image_suite.add_argument("--resume", action="store_true")

    commands.add_parser(
        "real-baseline-plan",
        help="Print the frozen combined story, image and human-review baseline plan",
    )
    real_baseline = commands.add_parser(
        "assemble-real-baseline",
        help="Bind story, image and independent human evidence into an immutable baseline",
    )
    real_baseline.add_argument("--story-baseline", type=Path, required=True)
    real_baseline.add_argument("--image-baseline", type=Path, required=True)
    real_baseline.add_argument("--story-review", type=Path, required=True)
    real_baseline.add_argument("--image-review", type=Path, required=True)
    real_baseline.add_argument(
        "--provider-mode", choices=["local", "local_sd35"], required=True
    )
    real_baseline.add_argument("--quality-preset", choices=QUALITY_PRESETS, default="quality")
    real_baseline.add_argument("--run-label", required=True)
    real_baseline.add_argument("--output", type=Path, required=True)

    runs = commands.add_parser("list-runs", help="List local workflow runs and their last event")
    runs.add_argument("--root", type=Path, required=True)

    jobs = commands.add_parser("list-jobs", help="List persistent local job history")
    jobs.add_argument("--root", type=Path, required=True)
    jobs.add_argument("--limit", type=int, default=100)

    evaluate_release = commands.add_parser(
        "evaluate-release", help="Evaluate a Stage 4 package against release gates"
    )
    evaluate_release.add_argument("package", type=Path)
    evaluate_release.add_argument(
        "--channel", choices=["development", "production"], default="development"
    )
    evaluate_release.add_argument("--framework-audit", type=Path)
    evaluate_release.add_argument("--benchmark-evidence", type=Path)
    evaluate_release.add_argument("--image-benchmark-evidence", type=Path)
    evaluate_release.add_argument("--output", type=Path)

    build_release = commands.add_parser(
        "build-release", help="Build a verified distributable release bundle"
    )
    build_release.add_argument("package", type=Path)
    build_release.add_argument("--output", type=Path, required=True)
    build_release.add_argument(
        "--channel", choices=["development", "production"], default="development"
    )
    build_release.add_argument("--framework-audit", type=Path)
    build_release.add_argument("--benchmark-evidence", type=Path)
    build_release.add_argument("--image-benchmark-evidence", type=Path)

    verify_release = commands.add_parser(
        "verify-release", help="Verify a distributable release bundle"
    )
    verify_release.add_argument("bundle", type=Path)

    commands.add_parser("doctor", help="Check Python, provider configuration and local AI runtimes")
    smoke = commands.add_parser(
        "smoke-workflow",
        help="Run the deterministic Stage 1-4 workflow and development release evaluation",
    )
    smoke.add_argument("--root", type=Path, required=True)
    providers = commands.add_parser("provider-status", help="Show provider bindings and runtime capabilities")
    providers.add_argument("--mode", choices=sorted(PROVIDER_MODES))
    providers.add_argument("--no-probe", action="store_true")
    image_models = commands.add_parser(
        "prepare-image-models", help="Check or explicitly download local image model weights"
    )
    image_models.add_argument(
        "--mode", choices=["local", "local_sd35"], default="local"
    )
    image_models.add_argument("--download", action="store_true")

    assist_export = commands.add_parser(
        "export-gpt-image-web-assist",
        help="Export an optional manual GPT Image Web prompt/reference bundle",
    )
    assist_export.add_argument("--input-package", type=Path, required=True)
    assist_export.add_argument("--output", type=Path, required=True)
    assist_export.add_argument(
        "--asset", action="append",
        help="Canonical PNG basename to include; repeat for multiple assets (default: all)",
    )
    assist_apply = commands.add_parser(
        "apply-gpt-image-web-assist",
        help="Validate manually reviewed GPT Image Web results and build a Stage 2 repair package",
    )
    assist_apply.add_argument("--root", type=Path, required=True)
    assist_apply.add_argument("--input-package", type=Path, required=True)
    assist_apply.add_argument("--assist-bundle", type=Path, required=True)
    assist_apply.add_argument("--run-id")
    assist_apply.add_argument("--confirm-human-reviewed", action="store_true", required=True)

    models = commands.add_parser("models", help="Manage the workspace-local model catalog")
    models.add_argument("--root", type=Path, default=Path(".runtime"))
    model_commands = models.add_subparsers(dest="model_command", required=True)
    model_commands.add_parser("list", help="List registered models")
    register_model = model_commands.add_parser("register", help="Register a model asset")
    register_model.add_argument("--id", required=True)
    register_model.add_argument("--name")
    register_model.add_argument("--kind", choices=["text", "image", "vision", "voice"], required=True)
    source = register_model.add_mutually_exclusive_group(required=True)
    source.add_argument("--path")
    source.add_argument("--model-id")
    register_model.add_argument("--quantization")
    register_model.add_argument(
        "--model-profile", choices=["sd35_medium"]
    )
    activate_model = model_commands.add_parser("activate", help="Select a model for a role")
    activate_model.add_argument("model_id")
    activate_model.add_argument(
        "--role", choices=["story", "safety", "character_image", "landscape", "portrait", "tts"], required=True
    )
    remove_model = model_commands.add_parser("remove", help="Remove a catalog entry, preserving weights")
    remove_model.add_argument("model_id")

    web = commands.add_parser("serve", help="Start the local AI Story web dashboard")
    web.add_argument("--root", type=Path, default=Path(".runtime"))
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    return root


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args(argv)
    try:
        if args.command == "init-run":
            result = RunWorkspace.create(args.root, Profile(args.profile), args.run_id).to_dict()
        elif args.command == "build-package":
            result = PackageBuilder().build(
                source_dir=args.source,
                output_path=args.output,
                stage=Stage(args.stage),
                operation=Operation(args.operation),
                profile=Profile(args.profile),
                parent_package_digest_sha256=args.parent_package_digest,
                source_stage=Stage(args.source_stage) if args.source_stage else None,
            ).to_dict()
        elif args.command == "verify-package":
            result = PackageVerifier().verify(args.archive).to_dict()
        elif args.command == "inspect-package":
            PackageVerifier().verify(args.archive)
            with zipfile.ZipFile(args.archive, "r") as archive:
                result = json.loads(archive.read("workflow_manifest.json").decode("utf-8"))
        elif args.command == "suggest-duration":
            duration = suggested_duration(Profile(args.profile), args.episode_mode)
            result = {
                "profile": args.profile,
                "length_min": duration.length_min,
                "length_max": duration.length_max,
                "length_target": duration.length_target,
                "target_wpm": duration.target_wpm,
                "confirmed": duration.confirmed,
            }
        elif args.command == "generate-stage1":
            profile = Profile(args.profile)
            duration = confirm_duration(profile, args.minutes, args.episode_mode)
            workspace = RunWorkspace.create(args.root, profile, args.run_id)
            result = Stage1Pipeline(provider_mode=args.provider_mode, quality_preset=args.quality_preset).run(
                Stage1Request(
                    profile, args.brief, duration, args.language,
                    episode_mode=args.episode_mode,
                    input_anchor=args.anchor,
                    series_title=args.series_title,
                    planned_arc_episodes=args.planned_arc_episodes,
                ),
                workspace,
            ).to_dict()
        elif args.command == "generate-stage2":
            PackageVerifier().verify(args.input_package)
            with zipfile.ZipFile(args.input_package, "r") as archive:
                source_manifest = json.loads(archive.read("workflow_manifest.json").decode("utf-8"))
            profile = Profile(source_manifest["active_profile"])
            workspace = RunWorkspace.create(args.root, profile, args.run_id)
            result = Stage2Pipeline(provider_mode=args.provider_mode, quality_preset=args.quality_preset).run(
                Stage2Request(args.input_package, args.mode), workspace
            ).to_dict()
        elif args.command == "generate-stage3":
            PackageVerifier().verify(args.input_package)
            with zipfile.ZipFile(args.input_package, "r") as archive:
                source_manifest = json.loads(archive.read("workflow_manifest.json").decode("utf-8"))
            profile = Profile(source_manifest["active_profile"])
            workspace = RunWorkspace.create(args.root, profile, args.run_id)
            result = Stage3Pipeline(provider_mode=args.provider_mode, quality_preset=args.quality_preset).run(
                Stage3Request(args.input_package), workspace
            ).to_dict()
        elif args.command == "generate-stage4":
            PackageVerifier().verify(args.input_package)
            with zipfile.ZipFile(args.input_package, "r") as archive:
                source_manifest = json.loads(archive.read("workflow_manifest.json").decode("utf-8"))
            profile = Profile(source_manifest["active_profile"])
            workspace = RunWorkspace.create(args.root, profile, args.run_id)
            result = Stage4Pipeline().run(
                Stage4Request(
                    args.input_package, args.aspect_ratio, args.coverage_mode,
                    args.confirm_large_plan,
                    render_tts=args.render_tts,
                    piper_voice_model=args.piper_voice_model,
                    visual_review_approved=args.approve_visual_review,
                ),
                workspace,
            ).to_dict()
        elif args.command == "list-runs":
            result = {"runs": RunIndex().list_runs(args.root)}
        elif args.command == "list-jobs":
            result = {"jobs": read_job_history(args.root.resolve() / ".jobs", args.limit)}
        elif args.command == "benchmark-plan":
            result = BenchmarkEvaluator().plan()
        elif args.command == "generate-benchmark-case":
            evaluator = BenchmarkEvaluator()
            case = evaluator.case(args.case_id)
            profile = Profile(case["profile"])
            workspace = RunWorkspace.create(args.root, profile)
            result = Stage1Pipeline(
                provider_mode=args.provider_mode, quality_preset=args.quality_preset
            ).run(
                Stage1Request(
                    profile,
                    case["brief"],
                    confirm_duration(profile, case["minutes"], case.get("episode_mode")),
                    case["language"],
                    episode_mode=case.get("episode_mode"),
                    series_title=case.get("series_title"),
                    benchmark_case_id=case["id"],
                    generation_seed=case["seed"],
                    benchmark_corpus_digest=evaluator.canonical_corpus_digest(),
                ),
                workspace,
            ).to_dict()
        elif args.command == "record-benchmark-case":
            result = BenchmarkEvaluator().write_case_record(
                args.case_id, args.package, args.output
            )
        elif args.command == "evaluate-benchmark":
            result = BenchmarkEvaluator().evaluate(
                json.loads(args.candidate.read_text(encoding="utf-8")),
                json.loads(args.baseline.read_text(encoding="utf-8")),
            )
        elif args.command == "summarize-benchmark":
            records = BenchmarkEvaluator.load_records(args.records)
            result = BenchmarkEvaluator().write_baseline_report(records, args.output)
        elif args.command == "run-benchmark-suite":
            output = args.output.resolve()
            evaluator = BenchmarkEvaluator()
            plan = evaluator.plan()
            if output.exists() and not args.resume:
                raise FileExistsError(
                    f"Benchmark output already exists; use --resume for an interrupted run: {output}"
                )
            baseline_path = output / "baseline.json"
            if baseline_path.exists():
                raise FileExistsError(f"Benchmark suite is already complete: {baseline_path}")
            records_dir = output / "records"
            runs_dir = output / "runs"
            packages_dir = output / "packages"
            records_dir.mkdir(parents=True, exist_ok=True)
            runs_dir.mkdir(parents=True, exist_ok=True)
            packages_dir.mkdir(parents=True, exist_ok=True)
            generated = 0
            resumed = 0
            for case in plan["cases"]:
                record_path = records_dir / f"{case['id']}.json"
                package_export = packages_dir / f"{case['id']}.zip"
                if record_path.exists():
                    record = evaluator.load_records(record_path)
                    if len(record) != 1:
                        raise WorkflowError(f"Invalid resumable benchmark record: {record_path}")
                    evaluator.validate_canonical_record(record[0])
                    if not package_export.is_file():
                        raise WorkflowError(
                            f"Resumable benchmark package is missing: {package_export}"
                        )
                    resumed += 1
                    continue
                profile = Profile(case["profile"])
                resumable_run_id = f"benchmark-{case['id']}"
                resumable_root = runs_dir / resumable_run_id
                workspace = (
                    RunWorkspace.open(runs_dir, resumable_run_id)
                    if args.resume and resumable_root.exists()
                    else RunWorkspace.create(runs_dir, profile, resumable_run_id)
                )
                stage_result = Stage1Pipeline(
                    provider_mode=args.provider_mode,
                    quality_preset=args.quality_preset,
                ).run(
                    Stage1Request(
                        profile,
                        case["brief"],
                        confirm_duration(profile, case["minutes"], case.get("episode_mode")),
                        case["language"],
                        episode_mode=case.get("episode_mode"),
                        series_title=case.get("series_title"),
                        benchmark_case_id=case["id"],
                        generation_seed=case["seed"],
                        benchmark_corpus_digest=evaluator.canonical_corpus_digest(),
                    ),
                    workspace,
                )
                shutil.copy2(Path(stage_result.package.archive_path), package_export)
                evaluator.write_case_record(case["id"], package_export, record_path)
                generated += 1
            records = evaluator.load_records(records_dir)
            report = evaluator.write_baseline_report(records, baseline_path)
            evaluator.write_human_review_template(
                records, "reviewer-a", output / "reviews" / "reviewer-a.json"
            )
            evaluator.write_human_review_template(
                records, "reviewer-b", output / "reviews" / "reviewer-b.json"
            )
            result = {
                "suite_id": plan["suite_id"],
                "corpus_digest_sha256": plan["corpus_digest_sha256"],
                "case_count": len(plan["cases"]),
                "generated_case_count": generated,
                "resumed_case_count": resumed,
                "records_directory": str(records_dir),
                "packages_directory": str(packages_dir),
                "baseline_path": str(baseline_path),
                "report_digest_sha256": report["report_digest_sha256"],
            }
        elif args.command == "evaluate-human-reviews":
            result = BenchmarkEvaluator().write_human_review_report(
                json.loads(args.review_a.read_text(encoding="utf-8")),
                json.loads(args.review_b.read_text(encoding="utf-8")),
                args.output,
            )
        elif args.command == "create-human-review-template":
            result = BenchmarkEvaluator().write_human_review_template(
                BenchmarkEvaluator.load_records(args.records),
                args.reviewer_id,
                args.output,
            )
        elif args.command == "image-baseline-plan":
            result = ImageBaselineEvaluator().plan()
        elif args.command == "record-image-baseline-case":
            result = ImageBaselineEvaluator().write_record(
                args.case_id, args.package, args.output
            )
        elif args.command == "summarize-image-baseline":
            evaluator = ImageBaselineEvaluator()
            result = evaluator.write_baseline(
                evaluator.load_records(args.records), args.output
            )
        elif args.command == "create-image-review-template":
            evaluator = ImageBaselineEvaluator()
            result = evaluator.write_human_review_template(
                evaluator.load_records(args.records), args.reviewer_id, args.output
            )
        elif args.command == "evaluate-image-reviews":
            evaluator = ImageBaselineEvaluator()
            result = evaluator.write_human_review_report(
                json.loads(args.review_a.read_text(encoding="utf-8")),
                json.loads(args.review_b.read_text(encoding="utf-8")),
                args.output,
            )
        elif args.command == "evaluate-image-benchmark":
            evaluator = ImageBaselineEvaluator()
            result = evaluator.write_candidate_evaluation(
                json.loads(args.baseline.read_text(encoding="utf-8")),
                json.loads(args.candidate.read_text(encoding="utf-8")),
                args.output,
                json.loads(args.human_review.read_text(encoding="utf-8"))
                if args.human_review else None,
            )
        elif args.command == "run-image-baseline-suite":
            output = args.output.resolve()
            evaluator = ImageBaselineEvaluator()
            baseline_path = output / "baseline.json"
            if baseline_path.exists():
                raise FileExistsError(f"Image baseline suite is already complete: {baseline_path}")
            if output.exists() and not args.resume:
                raise FileExistsError(
                    f"Image baseline output already exists; use --resume: {output}"
                )
            records_dir = output / "records"
            runs_dir = output / "runs"
            records_dir.mkdir(parents=True, exist_ok=True)
            runs_dir.mkdir(parents=True, exist_ok=True)
            generated = resumed = 0
            for case in evaluator.plan()["cases"]:
                case_id = str(case["id"])
                record_path = records_dir / f"{case_id}.json"
                if record_path.exists():
                    record = evaluator.load_records(record_path)[0]
                    if record.get("case_id") != case_id:
                        raise WorkflowError(f"Invalid resumable image record: {record_path}")
                    resumed += 1
                    continue
                source = args.source_packages / f"{case_id}.zip"
                if not source.is_file():
                    source = args.source_packages / case_id / "story.zip"
                if not source.is_file():
                    raise FileNotFoundError(f"Missing Stage 1 package for {case_id}")
                profile = Profile(case["profile"])
                case_runs = runs_dir / case_id
                stage2_ids = ["run-stage2"]
                stage2_ids.extend(
                    f"run-stage2-retry-{index}"
                    for index in range(1, 1000)
                    if (case_runs / f"run-stage2-retry-{index}").exists()
                )
                completed_stage2 = next(
                    (run_id for run_id in stage2_ids
                     if (case_runs / run_id / "output" / "story.zip").is_file()),
                    None,
                )
                if completed_stage2 is not None:
                    stage2_workspace = RunWorkspace.open(case_runs, completed_stage2)
                else:
                    checkpointed_stage2 = next(
                        (run_id for run_id in reversed(stage2_ids)
                         if (case_runs / run_id / "stage2_checkpoint.json").is_file()),
                        None,
                    )
                    if checkpointed_stage2 is not None:
                        stage2_workspace = RunWorkspace.open(case_runs, checkpointed_stage2)
                    else:
                        retry = 0
                        run_id = "run-stage2"
                        while (case_runs / run_id).exists():
                            retry += 1
                            run_id = f"run-stage2-retry-{retry}"
                        stage2_workspace = RunWorkspace.create(case_runs, profile, run_id)
                stage2_package = stage2_workspace.output_dir / "story.zip"
                if not stage2_package.is_file():
                    stage2 = Stage2Pipeline(
                        provider_mode=args.provider_mode, quality_preset=args.quality_preset
                    ).run(Stage2Request(source), stage2_workspace)
                    stage2_package = Path(stage2.package.archive_path)
                # Stage 3 has no transaction checkpoint. A failed CREATE leaves
                # inherited files in work/, so it cannot safely reopen that
                # workspace. Keep every failed attempt for diagnosis and use a
                # fresh run while still reusing a completed Stage 3 package.
                stage3_ids = ["run-stage3"]
                stage3_ids.extend(
                    f"run-stage3-retry-{index}"
                    for index in range(1, 1000)
                    if (case_runs / f"run-stage3-retry-{index}").exists()
                )
                completed_stage3 = next(
                    (run_id for run_id in stage3_ids
                     if (case_runs / run_id / "output" / "story.zip").is_file()),
                    None,
                )
                if completed_stage3 is not None:
                    stage3_workspace = RunWorkspace.open(case_runs, completed_stage3)
                else:
                    retry = 0
                    run_id = "run-stage3"
                    while (case_runs / run_id).exists():
                        retry += 1
                        run_id = f"run-stage3-retry-{retry}"
                    stage3_workspace = RunWorkspace.create(case_runs, profile, run_id)
                stage3_package = stage3_workspace.output_dir / "story.zip"
                if not stage3_package.is_file():
                    stage3 = Stage3Pipeline(
                        provider_mode=args.provider_mode, quality_preset=args.quality_preset
                    ).run(Stage3Request(stage2_package), stage3_workspace)
                    stage3_package = Path(stage3.package.archive_path)
                evaluator.write_record(
                    case_id, stage3_package, record_path,
                    stage2_package=stage2_package, source_package=source,
                )
                generated += 1
            records = evaluator.load_records(records_dir)
            report = evaluator.write_baseline(records, baseline_path)
            evaluator.write_human_review_template(
                records, "reviewer-a", output / "reviews" / "reviewer-a.json"
            )
            evaluator.write_human_review_template(
                records, "reviewer-b", output / "reviews" / "reviewer-b.json"
            )
            result = {
                "suite_id": evaluator.plan()["suite_id"],
                "generated_case_count": generated,
                "resumed_case_count": resumed,
                "baseline_path": str(baseline_path),
                "report_digest_sha256": report["report_digest_sha256"],
                "metrics": report["metrics"],
            }
        elif args.command == "real-baseline-plan":
            result = RealBaselineEvaluator().plan()
        elif args.command == "assemble-real-baseline":
            result = RealBaselineEvaluator().write_report(
                args.story_baseline,
                args.image_baseline,
                args.story_review,
                args.image_review,
                args.output,
                provider_mode=args.provider_mode,
                quality_preset=args.quality_preset,
                run_label=args.run_label,
            )
        elif args.command == "evaluate-release":
            result = ReleaseEvaluator().evaluate(
                args.package,
                channel=args.channel,
                framework_audit=args.framework_audit,
                benchmark_evidence=args.benchmark_evidence,
                image_benchmark_evidence=args.image_benchmark_evidence,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        elif args.command == "build-release":
            result = ReleaseBundleBuilder().build(
                args.package,
                args.output,
                channel=args.channel,
                framework_audit=args.framework_audit,
                benchmark_evidence=args.benchmark_evidence,
                image_benchmark_evidence=args.image_benchmark_evidence,
            )
        elif args.command == "verify-release":
            result = ReleaseBundleVerifier().verify(args.bundle)
        elif args.command == "doctor":
            result = environment_report()
        elif args.command == "smoke-workflow":
            result = run_deterministic_smoke(args.root)
        elif args.command == "provider-status":
            provider_registry = ProviderRuntimeRegistry(args.mode)
            try:
                result = provider_registry.status(probe=not args.no_probe)
            finally:
                provider_registry.close()
        elif args.command == "prepare-image-models":
            config = load_provider_config(args.mode)
            result = (
                download_image_models(config) if args.download else image_model_status(config)
            )
        elif args.command == "export-gpt-image-web-assist":
            result = GPTImageWebAssist().export(
                args.input_package, args.output, args.asset
            )
        elif args.command == "apply-gpt-image-web-assist":
            PackageVerifier().verify(args.input_package)
            with zipfile.ZipFile(args.input_package, "r") as archive:
                source_manifest = json.loads(archive.read("workflow_manifest.json").decode("utf-8"))
            workspace = RunWorkspace.create(
                args.root, Profile(source_manifest["active_profile"]), args.run_id
            )
            result = GPTImageWebAssist().apply(
                args.input_package,
                args.assist_bundle,
                workspace,
                human_reviewed=args.confirm_human_reviewed,
            )
        elif args.command == "models":
            manager = LocalModelManager(args.root)
            if args.model_command == "list":
                result = manager.inventory()
            elif args.model_command == "register":
                result = manager.register(
                    {
                        "id": args.id,
                        "name": args.name,
                        "kind": args.kind,
                        "path": args.path,
                        "model_id": args.model_id,
                        "quantization": args.quantization,
                        "model_profile": args.model_profile,
                    }
                )
            elif args.model_command == "activate":
                result = manager.activate(args.model_id, args.role)
            else:
                result = manager.remove(args.model_id)
        else:
            from .web import serve

            serve(args.root, args.host, args.port)
            return 0
    except (WorkflowError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "doctor" and result.get("status") == "NOT_READY":
        return 1
    return 0
