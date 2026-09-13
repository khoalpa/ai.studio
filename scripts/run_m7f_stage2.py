"""Run one gated Stage 2 landscape transaction against local ComfyUI."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from audio_story.adapters.image import ComfyUIConfig, ComfyUIImageAdapter
from audio_story.domain.state import WorkflowStatus
from audio_story.validation.stage2 import load_stage1_package
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.stage2_execution import Stage2ZoneExecutor
from audio_story.workflows.stage2_planning import build_stage2_zone_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage1_zip", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    source = load_stage1_package(args.stage1_zip, test_mode=args.test_mode)
    plan = build_stage2_zone_plan(source)
    canonical_digest = hashlib.sha256(args.canonical.read_bytes()).hexdigest()
    workflow_digest = hashlib.sha256(args.workflow.read_bytes()).hexdigest()
    kernel = WorkflowKernel(args.workspace)
    try:
        workflow_id = kernel.create_workflow(
            str(source.manifest["active_profile"]),
            "STAGE2",
            "CREATE",
            canonical_digest,
            workflow_digest,
        )
        kernel.transition_workflow(workflow_id, WorkflowStatus.RUNNING)
        stage_id = kernel.start_stage(workflow_id, "STAGE2", canonical_digest)
        result = {
            "workflow_id": workflow_id,
            "stage_id": stage_id,
            "status": "PREFLIGHT_ONLY",
            "next_basename": plan.execution_queue[0],
        }
        if args.execute:
            adapter = ComfyUIImageAdapter(
                ComfyUIConfig(workflow_path=args.workflow, timeout_seconds=300.0)
            )
            progress = args.workspace / "progress" / "stage2_image_progress.json"
            execution = Stage2ZoneExecutor(kernel, stage_id, source, plan, adapter, progress)
            outcome = execution.execute_next()
            result.update(
                {
                    "status": outcome.status,
                    "committed_count": outcome.committed_count,
                    "next_basename": outcome.next_pending_basename,
                }
            )
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    finally:
        kernel.close()


if __name__ == "__main__":
    raise SystemExit(main())
