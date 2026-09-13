from pathlib import Path

import pytest

from audio_story.adapters.image import (
    ComfyUIProvenance,
    ComfyUIProvisioningError,
    load_provenance,
)


def _provenance(tmp_path: Path, *, endpoint: str = "http://127.0.0.1:8188") -> ComfyUIProvenance:
    workflow = tmp_path / "workflow.json"
    model = tmp_path / "model.safetensors"
    workflow.write_bytes(b"{}")
    model.write_bytes(b"model")
    import hashlib

    return ComfyUIProvenance(
        "1.0",
        tmp_path,
        workflow,
        hashlib.sha256(b"{}").hexdigest(),
        model,
        hashlib.sha256(b"model").hexdigest(),
        "local-license",
        endpoint,
    )


def test_valid_provenance_returns_loopback_launch_args(tmp_path: Path) -> None:
    assert _provenance(tmp_path).offline_launch_args() == (
        "--listen",
        "127.0.0.1",
        "--port",
        "8188",
    )


@pytest.mark.parametrize("endpoint", ["https://example.com:8188", "http://192.168.1.2:8188"])
def test_non_loopback_is_rejected(tmp_path: Path, endpoint: str) -> None:
    with pytest.raises(ComfyUIProvisioningError, match="loopback"):
        _provenance(tmp_path, endpoint=endpoint).validate()


def test_digest_drift_is_rejected(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    provenance.workflow_path.write_bytes(b"changed")
    with pytest.raises(ComfyUIProvisioningError, match="workflow SHA-256"):
        provenance.validate()


def test_malformed_digest_is_rejected(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    malformed = provenance.__class__(
        provenance.version,
        provenance.install_path,
        provenance.workflow_path,
        "not-a-digest",
        provenance.model_path,
        provenance.model_sha256,
        provenance.model_license,
    )
    with pytest.raises(ComfyUIProvisioningError, match="SHA-256 digest"):
        malformed.validate()


def test_evidence_must_be_explicitly_pass_and_digest_bound(tmp_path: Path) -> None:
    import json

    provenance = _provenance(tmp_path)
    record = {
        "status": "PASS",
        "comfyui_version": provenance.version,
        "install_path": str(provenance.install_path),
        "workflow_path": str(provenance.workflow_path),
        "workflow_sha256": provenance.workflow_sha256,
        "model_path": str(provenance.model_path),
        "model_sha256": provenance.model_sha256,
        "model_license": provenance.model_license,
        "endpoint": provenance.endpoint,
    }
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(record), encoding="utf-8")
    assert load_provenance(evidence).offline_launch_args()[-1] == "8188"


def test_not_verified_evidence_is_rejected(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"status":"NOT_VERIFIED"}', encoding="utf-8")
    with pytest.raises(ComfyUIProvisioningError, match="status must be PASS"):
        load_provenance(evidence)
