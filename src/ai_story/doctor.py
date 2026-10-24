from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys
from typing import Any

from .provider_config import load_provider_config
from .runtime import ProviderRuntimeRegistry


def environment_report() -> dict[str, Any]:
    version_ok = (3, 10) <= sys.version_info[:2] < (3, 13)
    config = load_provider_config()
    mode = config["active_mode"]
    commands = {
        name: shutil.which(name)
        for name in ("py", "python", "ollama", "llama-server", "nvidia-smi", "tesseract")
    }
    gpu = None
    if commands["nvidia-smi"]:
        try:
            result = subprocess.run(
                [commands["nvidia-smi"], "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            gpu = result.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            gpu = None
    core_modules = {"Pillow": "PIL"}
    missing_core = [
        package
        for package, module in core_modules.items()
        if importlib.util.find_spec(module) is None
    ]
    local_image_modules = {
        "torch": "torch",
        "diffusers": "diffusers",
        "transformers": "transformers",
        "accelerate": "accelerate",
        "safetensors": "safetensors",
    }
    missing_local_image = [
        package
        for package, module in local_image_modules.items()
        if importlib.util.find_spec(module) is None
    ]
    text_runtime = commands["ollama"] or commands["llama-server"]
    text_runtime_required = mode in {"local", "hybrid", "text_local"}
    local_image_required = mode == "local"
    checks = [
        {"id": "PYTHON_VERSION", "status": "PASS" if version_ok else "FAIL", "value": platform.python_version()},
        {"id": "PROVIDER_CONFIG", "status": "PASS", "value": config["config_path"]},
        {"id": "PROVIDER_MODE", "status": "PASS", "value": mode},
        {
            "id": "CORE_DEPENDENCIES",
            "status": "NOT_READY" if missing_core else "PASS",
            "value": {"required": list(core_modules), "missing": missing_core},
        },
        {
            "id": "LOCAL_TEXT_RUNTIME",
            "status": (
                "PASS" if text_runtime else "NOT_READY" if text_runtime_required else "NOT_REQUIRED"
            ),
            "value": text_runtime,
        },
        {"id": "NVIDIA_GPU", "status": "PASS" if gpu else "NOT_DETECTED", "value": gpu},
        {
            "id": "LOCAL_IMAGE_DEPENDENCIES",
            "status": (
                "PASS"
                if not missing_local_image
                else "NOT_READY"
                if local_image_required
                else "NOT_REQUIRED"
            ),
            "value": {
                "required_for": "local",
                "missing": missing_local_image,
            },
        },
        {
            "id": "TESSERACT_OCR",
            "status": "PASS" if commands["tesseract"] else "NOT_INSTALLED",
            "value": commands["tesseract"],
        },
    ]
    registry = ProviderRuntimeRegistry()
    runtime_status = registry.status(probe=True)
    registry.close()
    required_failures = [
        check["id"]
        for check in checks
        if check["status"] in {"FAIL", "NOT_READY"}
    ]
    optional_warnings = [
        check["id"]
        for check in checks
        if check["status"] in {"NOT_DETECTED", "NOT_INSTALLED"}
    ]
    return {
        "status": (
            "NOT_READY" if required_failures else "DEGRADED" if optional_warnings else "PASS"
        ),
        "python_executable": sys.executable,
        "selected_provider_mode": mode,
        "required_failures": required_failures,
        "optional_warnings": optional_warnings,
        "checks": checks,
        "provider_registry": runtime_status,
    }
