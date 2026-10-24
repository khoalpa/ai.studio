from __future__ import annotations

import hashlib
import json
from pathlib import Path

import diffusers

from ai_story.provider_config import configure_job
from ai_story.runtime import ProviderRuntimeRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE4LR7 = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr7-critic-identity-lock-v1"
SOURCE_WORK = (
    PROJECT_ROOT
    / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1/youth-torn-paper-boat/work"
)
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr8-identity-capability-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    prior = json.loads(
        (PHASE4LR7 / "phase4lr7-result.json").read_text(encoding="utf-8")
    )
    if prior.get("status") != "PASS_WITH_GENERATION_BLOCKED":
        raise RuntimeError("Phase 4L-R7 lock is not valid")

    references = {
        character_id: SOURCE_WORK / f"characters/{character_id}.png"
        for character_id in ("bo", "me")
    }
    reference_evidence = {
        character_id: {
            "path": str(path.resolve()),
            "exists": path.is_file(),
            "sha256": sha256(path) if path.is_file() else None,
        }
        for character_id, path in references.items()
    }

    config = configure_job("local", None, "quality")
    registry = ProviderRuntimeRegistry(config=config)
    try:
        runtime = registry.runtime_for("landscape")
        report = runtime.reference_conditioning_report()
    finally:
        registry.close()

    pipeline_class = getattr(diffusers, "StableDiffusion3Pipeline", None)
    installed_stack = {
        "diffusers_version": diffusers.__version__,
        "pipeline_class": "StableDiffusion3Pipeline",
        "pipeline_available": pipeline_class is not None,
        "load_ip_adapter_available": bool(
            pipeline_class is not None and hasattr(pipeline_class, "load_ip_adapter")
        ),
    }
    candidate_backend = {
        "adapter": "InstantX/SD3.5-Large-IP-Adapter",
        "documented_base_model": "stabilityai/stable-diffusion-3.5-large",
        "required_image_encoder": "google/siglip-so400m-patch14-384",
        "configured_base_model": report["model_id"],
        "compatibility": "INCOMPATIBLE_BASE_PROFILE",
        "selected": False,
        "weights_downloaded": False,
        "reason": (
            "The documented adapter targets SD3.5 Large while this project is configured "
            "for SD3.5 Medium; architecture compatibility is not proven."
        ),
    }
    preconditions_pass = bool(
        report["status"] == "PASS"
        and installed_stack["load_ip_adapter_available"]
        and all(item["exists"] for item in reference_evidence.values())
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R8",
        "status": "PASS" if preconditions_pass else "BLOCKED_NO_COMPATIBLE_REFERENCE_BACKEND",
        "case_id": "youth-torn-paper-boat",
        "role": "IDENTITY_REFERENCE_CAPABILITY_SPIKE",
        "installed_stack": installed_stack,
        "runtime_reference_conditioning": report,
        "reference_inputs": reference_evidence,
        "candidate_backend_review": candidate_backend,
        "neutral_identity_smoke": {
            "status": "NOT_RUN_PRECONDITION_FAILED" if not preconditions_pass else "READY",
            "required_identity_similarity": 0.55,
            "generation_performed": False,
            "climax_generation_performed": False,
        },
        "new_image_generation_performed": False,
        "next_climax_attempt_authorized": False,
        "phase4n_opened": False,
        "source_package_modified": False,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / "phase4lr8-result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
