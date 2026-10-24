from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import run_phase4lr9r7r3r7_vae_instrumented_canary as canary_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R12_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r12-latent-scale0375-probe-v1/phase4lr9r7r3r12-result.json"
)
PRIOR_RESULT = R12_RESULT
PRIOR_STATUS = "PASS_CLEAN_SCALE_0_375"
PHASE = "4L-R9-R7-R3-R13"
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r13-neutral-scale0375-canary-v1"
CANDIDATE = OUTPUT_ROOT / "candidates/neutral-identity/attempt-1.png"
ASSESSMENT_PATH = OUTPUT_ROOT / (
    "candidates/neutral-identity/attempt-1-assessment.json"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r13-result.json"
WORKER_LOG = OUTPUT_ROOT / "worker.log"
SCALE = 0.375
SCALE_SCHEDULE: list[dict[str, float | int]] | None = None
ENTRYPOINT = Path(__file__).resolve()


def configure_runtime() -> None:
    canary_runtime.OUTPUT_ROOT = OUTPUT_ROOT
    canary_runtime.CANDIDATE = CANDIDATE
    canary_runtime.ASSESSMENT_PATH = ASSESSMENT_PATH
    canary_runtime.RESULT_PATH = RESULT_PATH
    canary_runtime.WORKER_LOG = WORKER_LOG
    canary_runtime.IP_ADAPTER_SCALE = SCALE
    canary_runtime.IP_ADAPTER_SCALE_SCHEDULE = SCALE_SCHEDULE


def worker() -> None:
    configure_runtime()
    canary_runtime.worker()


def main() -> None:
    configure_runtime()
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(PRIOR_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != PRIOR_STATUS:
        raise RuntimeError("Required prior checkpoint is not satisfied")
    if (
        not canary_runtime.REFERENCE.is_file()
        or canary_runtime.digest(canary_runtime.REFERENCE)
        != canary_runtime.REFERENCE_SHA256
    ):
        raise RuntimeError("Locked identity reference is missing or changed")
    if CANDIDATE.exists() or RESULT_PATH.exists():
        raise RuntimeError("R3-R13 already started; refusing a second attempt")

    baseline_gpu = canary_runtime.gpu_used_mib()
    env = os.environ.copy()
    env.update(
        {
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TRANSFORMERS_VERBOSITY": "error",
            "DIFFUSERS_VERBOSITY": "error",
            "PYTHONUNBUFFERED": "1",
        }
    )
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with WORKER_LOG.open("w+", encoding="utf-8") as worker_log:
        process = subprocess.Popen(
            [sys.executable, str(ENTRYPOINT), "--worker"],
            stdout=worker_log,
            stderr=worker_log,
            text=True,
            env=env,
        )
        root = psutil.Process(process.pid)
        peak_rss = 0
        peak_gpu = baseline_gpu
        while process.poll() is None:
            try:
                tree = [root, *root.children(recursive=True)]
                peak_rss = max(
                    peak_rss,
                    sum(item.memory_info().rss for item in tree if item.is_running()),
                )
                peak_gpu = max(peak_gpu, canary_runtime.gpu_used_mib())
            except (psutil.NoSuchProcess, subprocess.CalledProcessError):
                pass
            time.sleep(0.5)
        worker_log.flush()
        worker_log.seek(0)
        stdout = worker_log.read()
    if process.returncode != 0:
        raise RuntimeError(f"R3-R13 generation failed: {stdout[-12000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"R3-R13 worker returned no JSON: {stdout[-4000:]}")
    generation = json.loads(lines[-1])
    generation.update(
        {
            "peak_rss_gib": round(peak_rss / 1024**3, 2),
            "gpu_baseline_mib": baseline_gpu,
            "gpu_peak_mib": peak_gpu,
            "gpu_delta_mib": peak_gpu - baseline_gpu,
            "gpu_after_worker_exit_mib": canary_runtime.gpu_used_mib(),
        }
    )
    assessment = canary_runtime.assess_candidate()
    ASSESSMENT_PATH.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    automatic_pass = assessment["status"] == "ASSESSED_PASS"
    result = {
        "schema_version": "1.0",
        "phase": PHASE,
        "status": (
            "AWAITING_MANUAL_REVIEW"
            if automatic_pass
            else "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
        ),
        "case_id": "youth-torn-paper-boat",
        "character_id": "bo",
        "attempt": 1,
        "attempt_count": 1,
        "candidate_path": str(CANDIDATE.resolve()),
        "candidate_sha256": canary_runtime.file_sha256(CANDIDATE),
        "assessment_path": str(ASSESSMENT_PATH.resolve()),
        "prompt": canary_runtime.PROMPT,
        "negative_prompt": canary_runtime.NEGATIVE_PROMPT,
        "automatic_qa": assessment,
        "generation": generation,
        "manual_review_required": True,
        "candidate_promotable": automatic_pass,
        "next_attempt_started": False,
        "climax_generated": False,
        "phase4n_opened": False,
        "production_profile_changed": False,
        "source_package_modified": False,
        "guards": {
            "exactly_one_attempt": True,
            "locked_scale": SCALE,
            "locked_scale_schedule": SCALE_SCHEDULE,
            "vae_boundary_instrumented": True,
            "seven_gate_assessment": assessment["gate_count"] == 7,
        },
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
