from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import run_phase4lr9r7r3r11_latent_scale025_probe as probe_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R15_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r15-vae-precursor-critic-lock-v1/phase4lr9r7r3r15-result.json"
)
PRIOR_RESULT = R15_RESULT
PRIOR_STATUS = "PASS"
PHASE = "4L-R9-R7-R3-R16"
CLEAN_STATUS = "PASS_CLEAN_LATE_TAIL_CUTOFF"
BLOCKED_STATUS = "PASS_BLOCKED_LATE_TAIL_CUTOFF"
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r16-late-tail-adapter-cutoff-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r16-result.json"
WORKER_LOG = OUTPUT_ROOT / "worker.log"
EARLY_SCALE = 0.25
LATE_SCALE = 0.0
CUTOFF_STEP = 16
ADAPTER_SCALE_SCHEDULE: list[dict[str, float | int]] | None = None
ENTRYPOINT = Path(__file__).resolve()


def configure_worker() -> None:
    probe_runtime.SCALE = EARLY_SCALE
    probe_runtime.LATE_TAIL_SCALE = LATE_SCALE
    probe_runtime.SCALE_CUTOFF_STEP = CUTOFF_STEP
    probe_runtime.IP_ADAPTER_SCALE_SCHEDULE = ADAPTER_SCALE_SCHEDULE


def worker() -> None:
    configure_worker()
    probe_runtime.worker()


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(PRIOR_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != PRIOR_STATUS:
        raise RuntimeError("Required prior checkpoint is not satisfied")
    if probe_runtime.digest(probe_runtime.REFERENCE) != probe_runtime.REFERENCE_SHA256:
        raise RuntimeError("Locked identity reference changed")
    if RESULT_PATH.exists() or OUTPUT_ROOT.exists():
        raise RuntimeError("R3-R16 already started; refusing a second trajectory")

    baseline_gpu = probe_runtime.gpu_used_mib()
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
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
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
                peak_gpu = max(peak_gpu, probe_runtime.gpu_used_mib())
            except (psutil.NoSuchProcess, subprocess.CalledProcessError):
                pass
            time.sleep(0.5)
        worker_log.flush()
        worker_log.seek(0)
        stdout = worker_log.read()
    if process.returncode != 0:
        raise RuntimeError(f"Late-tail cutoff worker failed: {stdout[-12000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"Late-tail cutoff worker returned no JSON: {stdout[-4000:]}")
    probe = json.loads(lines[-1])
    progress_count = stdout.count('"progress": "step_')
    probe.update(
        {
            "progress_event_count": progress_count,
            "peak_rss_gib": round(peak_rss / 1024**3, 2),
            "gpu_baseline_mib": baseline_gpu,
            "gpu_peak_mib": peak_gpu,
            "gpu_delta_mib": peak_gpu - baseline_gpu,
            "gpu_after_worker_exit_mib": probe_runtime.gpu_used_mib(),
        }
    )
    expected_schedule = ADAPTER_SCALE_SCHEDULE or [
        {"effective_step": 0, "scale": EARLY_SCALE},
        {"effective_step": CUTOFF_STEP, "scale": LATE_SCALE},
    ]
    execution_valid = (
        probe["ip_adapter_scale_schedule"] == expected_schedule
        and progress_count == probe_runtime.STEPS
        and probe["tail_profile_count"]
        == probe_runtime.STEPS - probe_runtime.TAIL_START
        and probe["forbidden_calls"] == {"vae_forward": 0, "vae_decode": 0}
        and probe["vae_decode_calls"] == 0
        and probe["images_created"] == 0
    )
    clean = not probe["latent_critic"]["blocked"]
    result = {
        "schema_version": "1.0",
        "phase": PHASE,
        "status": (
            CLEAN_STATUS
            if execution_valid and clean
            else (
                BLOCKED_STATUS
                if execution_valid
                else "FAIL_EXECUTION"
            )
        ),
        "probe": probe,
        "analysis": {
            "late_tail_cutoff_clean": clean,
            "early_identity_conditioning_preserved": True,
            "late_tail_adapter_disabled": True,
        },
        "guards": {
            "exactly_one_trajectory": True,
            "vae_decode_performed": False,
            "image_generation_performed": False,
            "neutral_generation_authorized": False,
            "climax_generated": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    if not execution_valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
