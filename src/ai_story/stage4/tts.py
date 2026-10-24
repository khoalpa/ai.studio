from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

from ..config import project_root
from ..errors import ConfigurationError, WorkflowError
from ..hashing import sha256_file


def voice_inventory(
    model_path: Path | None = None, locale: str = "vi-VN"
) -> dict[str, Any]:
    config = json.loads((project_root() / "spec" / "voices.json").read_text(encoding="utf-8"))
    executable = shutil.which(config["providers"]["piper"]["executable"])
    voices = []
    if model_path is not None and model_path.is_file():
        voices.append(
            {
                "voice_id": model_path.stem,
                "provider": "piper",
                "model_filename": model_path.name,
                "model_sha256": sha256_file(model_path),
                "locale": locale,
                "accent": "CONFIGURED_MODEL",
                "status": "AVAILABLE" if executable else "RUNTIME_MISSING",
            }
        )
    return {
        "provider": "piper",
        "runtime_path": executable,
        "capability_status": "PASS" if executable and voices else "NOT_VERIFIED",
        "voices": voices,
        "fallback": config["fallback"],
    }


def render_tts(
    root: Path, clips: list[dict[str, Any]], model_path: Path, inventory: dict[str, Any]
) -> list[dict[str, Any]]:
    executable = inventory.get("runtime_path")
    if not executable:
        raise ConfigurationError("Piper executable is required for --render-tts")
    if not model_path.is_file():
        raise ConfigurationError(f"Piper voice model does not exist: {model_path}")
    directory = root / "audio"
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    for clip in clips:
        text = " ".join(item["text"] for item in clip["voice_plan"]["segments"])
        relative = f"audio/{clip['clip_id']}.wav"
        target = root / relative
        text_path = directory / f".{clip['clip_id']}.txt"
        text_path.write_text(text, encoding="utf-8")
        try:
            result = _run_piper(executable, model_path, text_path, target)
            if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
                detail = result.stderr.decode("utf-8", errors="replace").strip()[-500:]
                raise WorkflowError(f"Piper failed for {clip['clip_id']}: {detail}")
        finally:
            text_path.unlink(missing_ok=True)
        with wave.open(str(target), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
            sample_rate = stream.getframerate()
            channels = stream.getnchannels()
        length_scale = 1.0
        for _ in range(3):
            if duration <= clip["duration_seconds"] + 0.05:
                break
            # Piper's natural speaking rate varies by voice. Fit the exact
            # source text to the precomputed clip without paraphrasing it.
            length_scale = max(
                0.30,
                min(length_scale, length_scale * clip["duration_seconds"] / duration * 0.94),
            )
            text_path.write_text(text, encoding="utf-8")
            try:
                result = _run_piper(
                    executable, model_path, text_path, target, length_scale=length_scale
                )
                if result.returncode != 0:
                    detail = result.stderr.decode("utf-8", errors="replace").strip()[-500:]
                    raise WorkflowError(f"Piper retry failed for {clip['clip_id']}: {detail}")
            finally:
                text_path.unlink(missing_ok=True)
            with wave.open(str(target), "rb") as stream:
                duration = stream.getnframes() / stream.getframerate()
                sample_rate = stream.getframerate()
                channels = stream.getnchannels()
        if duration > clip["duration_seconds"] + 0.05:
            raise WorkflowError(
                f"Rendered voice exceeds clip duration for {clip['clip_id']}: {duration:.3f}s"
            )
        records.append(
            {
                "clip_id": clip["clip_id"],
                "path": relative,
                "sha256": sha256_file(target),
                "duration_seconds": round(duration, 3),
                "sample_rate": sample_rate,
                "channels": channels,
                "voice_id": model_path.stem,
                "status": "RENDERED",
            }
        )
    return records


def _run_piper(
    executable: str,
    model_path: Path,
    text_path: Path,
    target: Path,
    *,
    length_scale: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    command = [
        executable,
        "--model",
        str(model_path),
        "--input_file",
        str(text_path),
        "--output_file",
        str(target),
    ]
    if length_scale is not None:
        command.extend(["--length_scale", f"{length_scale:.4f}"])
    return subprocess.run(command, capture_output=True, timeout=120, check=False)
