"""Run or preflight the Stage 3 portrait pilot against local ComfyUI."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from stage3_qwen_assessor import build_assessor

from audio_story.adapters.image import ComfyUIConfig, ComfyUIImageAdapter
from audio_story.domain.state import WorkflowStatus
from audio_story.validation.stage3 import load_stage2_package
from audio_story.workflows.kernel import WorkflowKernel
from audio_story.workflows.recovery import recover
from audio_story.workflows.stage3_execution import Stage3PortraitExecutor
from audio_story.workflows.stage3_planning import (
    build_stage3_portrait_plan,
    compile_stage3_invocation,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("package", type=Path)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--workflow", type=Path, required=True)
    p.add_argument("--canonical", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--execute-all", action="store_true")
    p.add_argument("--workflow-id")
    p.add_argument("--stage-id")
    args = p.parse_args()
    source = load_stage2_package(args.package, test_mode=False)
    plan = build_stage3_portrait_plan(source)
    invocation = compile_stage3_invocation(source, plan, "cover.png")
    result = {
        "status": "PREFLIGHT_ONLY",
        "pilot": invocation.target_basename,
        "width": invocation.requested_width,
        "height": invocation.requested_height,
    }
    if args.execute or args.execute_all:
        kernel = WorkflowKernel(args.workspace)
        try:
            wd = hashlib.sha256(args.workflow.read_bytes()).hexdigest()
            cd = hashlib.sha256(args.canonical.read_bytes()).hexdigest()
            if args.workflow_id and args.stage_id:
                workflow_id, stage_id = args.workflow_id, args.stage_id
                recover(kernel, workflow_id)
            else:
                workflow_id = kernel.create_workflow(
                    str(source.manifest["active_profile"]), "STAGE3", "CREATE", cd, wd
                )
                kernel.transition_workflow(workflow_id, WorkflowStatus.RUNNING)
                stage_id = kernel.start_stage(workflow_id, "STAGE3", cd)
            adapter = ComfyUIImageAdapter(
                ComfyUIConfig(workflow_path=args.workflow, timeout_seconds=300.0)
            )
            executor = Stage3PortraitExecutor(
                kernel,
                stage_id,
                source,
                plan,
                adapter,
                build_assessor(args.model),
                workflow_digest=wd,
                model_identity="sd_xl_base_1.0.safetensors",
                timeout_seconds=300.0,
            )
            outcome = executor.execute_all() if args.execute_all else executor.execute_next()
            result.update(
                {
                    "status": outcome.status,
                    "committed_count": outcome.committed_count,
                    "next": outcome.next_pending_basename,
                }
            )
        finally:
            kernel.close()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
