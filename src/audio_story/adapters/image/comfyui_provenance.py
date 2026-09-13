"""Fail-closed provenance for an explicitly provisioned local ComfyUI runtime."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ComfyUIProvisioningError(ValueError):
    """Required local ComfyUI evidence is absent or inconsistent."""


def load_provenance(path: Path) -> ComfyUIProvenance:
    """Load and validate a user-supplied, digest-bound evidence record."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComfyUIProvisioningError("evidence JSON cannot be read") from exc
    if not isinstance(record, dict) or record.get("status") != "PASS":
        raise ComfyUIProvisioningError("evidence status must be PASS")
    required = (
        "comfyui_version",
        "install_path",
        "workflow_path",
        "workflow_sha256",
        "model_path",
        "model_sha256",
        "model_license",
        "endpoint",
    )
    if any(not isinstance(record.get(key), str) or not record[key].strip() for key in required):
        raise ComfyUIProvisioningError("evidence record is incomplete")
    provenance = ComfyUIProvenance(
        version=record["comfyui_version"],
        install_path=Path(record["install_path"]),
        workflow_path=Path(record["workflow_path"]),
        workflow_sha256=record["workflow_sha256"],
        model_path=Path(record["model_path"]),
        model_sha256=record["model_sha256"],
        model_license=record["model_license"],
        endpoint=record["endpoint"],
    )
    provenance.validate()
    return provenance


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ComfyUIProvisioningError(f"file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_digest(value: str, label: str) -> str:
    normalized = value.lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ComfyUIProvisioningError(f"{label} must be a SHA-256 digest")
    return normalized


@dataclass(frozen=True, slots=True)
class ComfyUIProvenance:
    version: str
    install_path: Path
    workflow_path: Path
    workflow_sha256: str
    model_path: Path
    model_sha256: str
    model_license: str
    endpoint: str = "http://127.0.0.1:8188"

    def validate(self) -> None:
        parsed = urlsplit(self.endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ComfyUIProvisioningError("ComfyUI endpoint must be HTTP loopback")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ComfyUIProvisioningError("ComfyUI endpoint contains forbidden URL parts")
        if not 1 <= (parsed.port or 8188) <= 65535:
            raise ComfyUIProvisioningError("ComfyUI port is invalid")
        if not self.install_path.is_dir():
            raise ComfyUIProvisioningError(f"install path is missing: {self.install_path}")
        if not self.version.strip() or not self.model_license.strip():
            raise ComfyUIProvisioningError("version and model license are required")
        workflow_digest = _require_digest(self.workflow_sha256, "workflow_sha256")
        model_digest = _require_digest(self.model_sha256, "model_sha256")
        if sha256_file(self.workflow_path) != workflow_digest:
            raise ComfyUIProvisioningError("workflow SHA-256 mismatch")
        if sha256_file(self.model_path) != model_digest:
            raise ComfyUIProvisioningError("model SHA-256 mismatch")

    def offline_launch_args(self) -> tuple[str, ...]:
        self.validate()
        return ("--listen", "127.0.0.1", "--port", str(urlsplit(self.endpoint).port or 80))
