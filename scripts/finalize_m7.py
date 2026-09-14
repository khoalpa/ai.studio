"""Evaluate production M7 gates and build the Stage 2 checkpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from audio_story.validation.stage2 import load_stage1_package
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.stage2_gates import (
    SemanticAssessment,
    evaluate_stage2_landscape_gates,
)
from audio_story.workflows.stage2_package import build_stage2_checkpoint
from audio_story.workflows.stage2_planning import build_stage2_zone_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage1_zip", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--stage-id", required=True)
    parser.add_argument("--assessments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = load_stage1_package(args.stage1_zip, test_mode=False)
    plan = build_stage2_zone_plan(source)
    assessments: dict[str, SemanticAssessment] = {}
    for path in args.assessments.glob("*.assessment.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        item = value["assessment"]
        basename = path.name.removesuffix(".assessment.json") + ".png"
        assessments[basename] = SemanticAssessment(
            basename=basename,
            status=item["status"],
            method=item["method"],
            evidence_digest_sha256=value["evidence_digest_sha256"],
            observable_findings=tuple(item["observable_findings"]),
        )

    kernel = WorkflowKernel(args.workspace)
    try:
        result = evaluate_stage2_landscape_gates(kernel, args.stage_id, plan, assessments)
        digest = build_stage2_checkpoint(kernel, args.stage_id, source, plan, result, args.output)
        print(
            json.dumps(
                {
                    "status": result.status,
                    "authoritative_count": result.authoritative_count,
                    "semantic_pass_count": result.semantic_pass_count,
                    "evidence_digest_sha256": result.evidence_digest_sha256,
                    "package_digest_sha256": digest,
                    "output": str(args.output),
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        kernel.close()


if __name__ == "__main__":
    raise SystemExit(main())
