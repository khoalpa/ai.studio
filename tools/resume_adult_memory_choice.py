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
SOURCE_RUN = (
    PROJECT_ROOT
    / "artifacts/baselines/real-v1/mini-corpus/adult-memory-choice-repair"
    / "adult-memory-choice-repair-v5"
)
OUTPUT_ROOT = (
    PROJECT_ROOT / "artifacts/baselines/real-v1/mini-corpus/adult-memory-choice-repair"
)
RUN_ID = "adult-memory-choice-repair-v8"


def main() -> None:
    evaluator = BenchmarkEvaluator()
    case = evaluator.case("adult-memory-choice")
    profile = Profile(case["profile"])
    request = Stage1Request(
        profile=profile,
        brief=case["brief"],
        duration=confirm_duration(profile, case["minutes"], case.get("episode_mode")),
        language=case["language"],
        episode_mode=case.get("episode_mode"),
        series_title=case.get("series_title"),
        benchmark_case_id=case["id"],
        generation_seed=case["seed"],
        benchmark_corpus_digest=evaluator.canonical_corpus_digest(),
    )

    workspace_root = OUTPUT_ROOT / RUN_ID
    workspace = (
        RunWorkspace.open(OUTPUT_ROOT, RUN_ID)
        if workspace_root.exists()
        else RunWorkspace.create(OUTPUT_ROOT, profile, RUN_ID)
    )
    checkpoint_path = workspace.root / "stage1_checkpoint.json"
    if not checkpoint_path.exists():
        story = json.loads((SOURCE_RUN / "work/story.json").read_text(encoding="utf-8"))
        contract = json.loads(
            (SOURCE_RUN / "work/story_contract.json").read_text(encoding="utf-8")
        )
        pixel_hashes: dict[str, str] = {}
        for character in story["characters"]:
            reference = character["reference_asset"]
            relative = str(reference["reference_image"])
            source = SOURCE_RUN / "work" / relative
            target = workspace.work_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            pixel_hashes[relative] = str(reference["pixel_sha256"])
        Stage1Pipeline._write_checkpoint(
            checkpoint_path,
            Stage1Pipeline._request_digest(request),
            "CHARACTER_IMAGES_CREATED",
            story,
            contract,
            pixel_hashes,
        )
        workspace.log(
            "STAGE1_RECOVERY_CHECKPOINT_CREATED",
            {"source_run_id": SOURCE_RUN.name, "phase": "CHARACTER_IMAGES_CREATED"},
        )

    models = LocalModelManager(RUNTIME_ROOT)
    story_model = models.active_model("story")
    if story_model is None:
        raise RuntimeError("No active story model")
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

    result = Stage1Pipeline(
        provider_mode="local",
        model_overrides={"story": story_model},
        quality_preset="quality",
        runtime_preparer=prepare_runtime,
    ).run(request, workspace)
    record_path = OUTPUT_ROOT / "adult-memory-choice-v8.json"
    if not record_path.exists():
        evaluator.write_case_record(case["id"], Path(result.package.archive_path), record_path)
    print(
        json.dumps(
            {
                "result": result.to_dict(),
                "record": json.loads(record_path.read_text(encoding="utf-8")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
