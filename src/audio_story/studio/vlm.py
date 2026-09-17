"""Strict subprocess boundary for the existing offline Qwen2.5-VL assessor."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

from audio_story.adapters.image.base import ImageAdapterError


class VlmAssessmentError(ImageAdapterError):
    """Local semantic-assessment failure that image transactions can record."""


@dataclass(frozen=True, slots=True)
class VlmAssessment:
    status: str
    observable_findings: tuple[str, ...]
    evidence_digest_sha256: str


class LocalQwenVlmAssessor:  # pragma: no cover - GPU subprocess is exercised by local smoke tests
    def __init__(self, model_path: Path, runner_path: Path, timeout_seconds: float = 300) -> None:
        self.model_path = model_path.resolve()
        self.runner_path = runner_path.resolve()
        self.timeout_seconds = timeout_seconds

    def assess(
        self, image_bytes: bytes, basename: str, asset_record: dict[str, Any], cancellation: Event
    ) -> VlmAssessment:
        if not self.model_path.is_dir() or not self.runner_path.is_file():
            raise VlmAssessmentError(
                "VLM001_LOCAL_RUNTIME_MISSING", "local VLM runtime is unavailable"
            )
        image_digest = hashlib.sha256(image_bytes).hexdigest()
        with tempfile.TemporaryDirectory(prefix="audio-story-vlm-") as temporary:
            root = Path(temporary)
            image_path = root / basename
            record_path = root / "asset.json"
            output_path = root / "assessment.json"
            image_path.write_bytes(image_bytes)
            record_path.write_text(
                json.dumps(asset_record, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.update(
                {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(self.runner_path),
                    str(image_path),
                    "--model",
                    str(self.model_path),
                    "--asset-record",
                    str(record_path),
                    "--output",
                    str(output_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                if cancellation.is_set():
                    process.kill()
                    process.communicate()
                    raise VlmAssessmentError(
                        "VLM003_CANCELLED", "local VLM assessment was cancelled"
                    )
                try:
                    stdout, stderr = process.communicate(
                        timeout=max(0.01, min(0.25, deadline - time.monotonic()))
                    )
                    break
                except subprocess.TimeoutExpired as exc:
                    if time.monotonic() >= deadline:
                        process.kill()
                        process.communicate()
                        raise VlmAssessmentError(
                            "VLM002_TIMEOUT", "local VLM assessment timed out"
                        ) from exc
            if process.returncode != 0 or not output_path.is_file():
                raise VlmAssessmentError(
                    "VLM004_BACKEND_FAILURE", (stderr or stdout or "VLM process failed")[-500:]
                )
            try:
                value = json.loads(output_path.read_text(encoding="utf-8"))
                assessment = value["assessment"]
                findings = assessment["observable_findings"]
                status = assessment["status"]
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise VlmAssessmentError(
                    "VLM005_INVALID_OUTPUT", "VLM output is not strict JSON"
                ) from exc
            if value.get("image_sha256") != image_digest:
                raise VlmAssessmentError("VLM006_DIGEST_MISMATCH", "VLM evidence is stale")
            if isinstance(findings, str):
                findings = [findings]
            if status not in {"PASS", "FAIL"} or not isinstance(findings, list) or not findings:
                raise VlmAssessmentError(
                    "VLM005_INVALID_OUTPUT", "VLM assessment fields are invalid"
                )
            if any(not isinstance(item, str) or not item.strip() for item in findings):
                raise VlmAssessmentError("VLM005_INVALID_OUTPUT", "VLM findings are invalid")
            digest = value.get("evidence_digest_sha256")
            if not isinstance(digest, str) or len(digest) != 64:
                raise VlmAssessmentError("VLM005_INVALID_OUTPUT", "VLM evidence digest is invalid")
            return VlmAssessment(status, tuple(item.strip() for item in findings), digest)
