from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

from pytest import MonkeyPatch

import audio_story.doctor as doctor


def test_report_is_machine_readable_and_offline(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doctor, "_memory_bytes", lambda: 128 * 1024**3)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    report = json.loads(doctor.report_json(tmp_path))
    assert report["schema_version"] == "1.0"
    assert report["offline_probe"] is True
    assert report["config"]["max_parallel_gpu_jobs"] == 1
    assert report["gpu"]["available"] is False


def test_gpu_inventory(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor.shutil,
        "which",
        lambda name: "nvidia-smi" if name == "nvidia-smi" else None,
    )
    completed = subprocess.CompletedProcess(
        [], 0, "NVIDIA RTX A4500 Laptop GPU, 16384, 596.52\n", ""
    )
    run = Mock(return_value=completed)
    monkeypatch.setattr(doctor.subprocess, "run", run)
    report = doctor._gpu()
    assert report["devices"][0]["memory_total_mib"] == 16384
    run.assert_called_once()


def test_gpu_command_failure_is_reported(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "nvidia-smi")
    monkeypatch.setattr(
        doctor.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("nvidia-smi", 5))
    )
    assert doctor._gpu()["available"] is False


def test_memory_probe_on_posix(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.os, "name", "posix")
    values = {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 1000}
    monkeypatch.setattr(doctor.os, "sysconf", values.__getitem__, raising=False)
    assert doctor._memory_bytes() == 4_096_000


def test_memory_probe_on_windows() -> None:
    assert doctor._memory_bytes() is not None
