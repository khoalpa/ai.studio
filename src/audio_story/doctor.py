"""Local, side-effect-free environment inventory for offline readiness."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from audio_story.config import DEFAULT_CONFIG


def _command(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {"available": path is not None, "path": path}


def _gpu() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return {"available": False, "devices": [], "error": "nvidia-smi not found"}
    command = [
        executable,
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "devices": [], "error": str(exc)}
    devices = []
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) == 3:
            devices.append(
                {"name": fields[0], "memory_total_mib": int(fields[1]), "driver": fields[2]}
            )
    return {"available": bool(devices), "devices": devices}


def _memory_bytes() -> int | None:
    if os.name != "nt":
        page_size = getattr(os, "sysconf", lambda _: 0)("SC_PAGE_SIZE")
        pages = getattr(os, "sysconf", lambda _: 0)("SC_PHYS_PAGES")
        return int(page_size * pages) or None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_phys", ctypes.c_ulonglong),
            ("avail_phys", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("avail_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("avail_virtual", ctypes.c_ulonglong),
            ("avail_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.total_phys)


def collect_report(path: Path | None = None) -> dict[str, Any]:
    target = path or Path.cwd()
    disk = shutil.disk_usage(target)
    return {
        "schema_version": "1.0",
        "status": "ok",
        "offline_probe": True,
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "supported": sys.version_info >= (3, 11),
        },
        "cuda": _command("nvcc"),
        "gpu": _gpu(),
        "ram": {"total_bytes": _memory_bytes()},
        "disk": {"path": str(target.resolve()), "free_bytes": disk.free, "total_bytes": disk.total},
        "services": {
            "llama_cpp": {**_command("llama-server"), "url": DEFAULT_CONFIG.llama_cpp_url},
            "comfyui": {**_command("comfyui"), "url": DEFAULT_CONFIG.comfyui_url},
            "ocr": _command("paddleocr"),
        },
        "config": {
            "host": DEFAULT_CONFIG.host,
            "max_parallel_gpu_jobs": DEFAULT_CONFIG.max_parallel_gpu_jobs,
        },
    }


def report_json(path: Path | None = None) -> str:
    return json.dumps(collect_report(path), ensure_ascii=False, sort_keys=True)
