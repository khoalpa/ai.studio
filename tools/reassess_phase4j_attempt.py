from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_story.image_qa import LocalImageQualityAssessor
from ai_story.provider_config import configure_job

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = (
    PROJECT_ROOT
    / "artifacts/baselines/real-v1/image/phase4j-prop-first-canary-v1"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reassess a Phase 4J candidate with a localized prop-scale critic."
    )
    parser.add_argument("--attempt", type=int, default=3)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    return parser.parse_args()


def main() -> None:
    options = parse_args()
    candidate_root = (
        options.root
        / "youth-torn-paper-boat/work/candidates/cover"
    )
    candidate = candidate_root / f"attempt-{options.attempt}-inpaint.png"
    sidecar = candidate_root / f"attempt-{options.attempt}-rejected.assessment.json"
    previous = json.loads(sidecar.read_text(encoding="utf-8"))
    crop_box = previous["masked_prop_inpaint"]["crop_box_pixels"]
    probe = {
        "probe_id": "controlled_prop_scale",
        "expected": "one small palm-sized folded paper boat held between two human hands",
        "forbidden": [
            "an oversized paper boat larger than the hands",
            "a person-sized paper boat dominating the scene",
        ],
        "crop_box_pixels": crop_box,
    }
    config = configure_job("local", None, "quality")
    assessor = LocalImageQualityAssessor(config["runtimes"]["diffusers"]["qa"])
    try:
        result = assessor.assess_fidelity_probes(
            candidate.read_bytes(), fidelity_probes=[probe]
        )
    finally:
        assessor.unload()
    result.update({
        "schema_version": "1.0",
        "phase": "4J_LOCALIZED_REASSESSMENT",
        "case_id": "youth-torn-paper-boat",
        "role": "COVER",
        "attempt": options.attempt,
        "candidate": str(candidate.resolve()),
        "source_assessment": str(sidecar.resolve()),
        "image_generation_performed": False,
        "source_story_package_modified": False,
    })
    output = options.root / f"attempt-{options.attempt}-localized-reassessment.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
