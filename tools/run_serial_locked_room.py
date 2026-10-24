from __future__ import annotations

import json
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
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/mini-corpus/serial-locked-room"
RUN_ID = "serial-locked-room-v1"


def main() -> None:
    evaluator = BenchmarkEvaluator()
    case = evaluator.case("serial-locked-room")
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
    workspace = (
        RunWorkspace.open(OUTPUT_ROOT, RUN_ID)
        if (OUTPUT_ROOT / RUN_ID).exists()
        else RunWorkspace.create(OUTPUT_ROOT, profile, RUN_ID)
    )
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

    result = Stage1Pipeline(
        provider_mode="local",
        model_overrides={"story": story_model, "character_image": image_model},
        quality_preset="quality",
        runtime_preparer=prepare_runtime,
    ).run(request, workspace)
    record_path = OUTPUT_ROOT / "serial-locked-room.json"
    if not record_path.exists():
        evaluator.write_case_record(case["id"], Path(result.package.archive_path), record_path)
    print(json.dumps({
        "result": result.to_dict(),
        "record": json.loads(record_path.read_text(encoding="utf-8")),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
