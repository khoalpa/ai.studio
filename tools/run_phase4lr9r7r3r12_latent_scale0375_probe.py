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
R11_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r11-latent-scale025-probe-v1/phase4lr9r7r3r11-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / "phase4lr9r7r3r12-latent-scale0375-probe-v1"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r12-result.json"
WORKER_LOG = OUTPUT_ROOT / "worker.log"
SCALE = 0.375


def worker() -> None:
    probe_runtime.SCALE = SCALE
    probe_runtime.worker()


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(R11_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_CLEAN_SCALE_0_25":
        raise RuntimeError("R3-R11 clean checkpoint is required before midpoint probe")
    if probe_runtime.digest(probe_runtime.REFERENCE) != probe_runtime.REFERENCE_SHA256:
        raise RuntimeError("Locked identity reference changed")
    if RESULT_PATH.exists() or OUTPUT_ROOT.exists():
        raise RuntimeError("R3-R12 already started; refusing a second trajectory")

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
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
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
        raise RuntimeError(f"Scale 0.375 worker failed: {stdout[-12000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"Scale 0.375 worker returned no JSON: {stdout[-4000:]}")
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
    execution_valid = (
        probe["ip_adapter_scale"] == SCALE
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
        "phase": "4L-R9-R7-R3-R12",
        "status": (
            "PASS_CLEAN_SCALE_0_375"
            if execution_valid and clean
            else (
                "PASS_BLOCKED_SCALE_0_375"
                if execution_valid
                else "FAIL_EXECUTION"
            )
        ),
        "probe": probe,
        "analysis": {
            "scale_0_375_clean": clean,
            "candidate_upper_bound": SCALE if clean else 0.25,
            "safe_fallback_scale": 0.25,
        },
        "guards": {
            "exactly_one_trajectory": True,
            "scale_probe_count": 1,
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
