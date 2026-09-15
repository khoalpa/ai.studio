"""Offline release-bundle manifest, lock file and SBOM generation."""

from __future__ import annotations

import json
import shutil
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any, cast

from audio_story.persistence.migrations import migration_directory
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes

RELEASE_SCHEMA_VERSION = "1.0"
INSTALL_SCRIPT = """param([string]$Python = "python")
$ErrorActionPreference = 'Stop'
$bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
& $Python "$bundle\\verify-release.py" "$bundle"
& $Python -m pip install --no-index --find-links "$bundle\\wheelhouse" `
  --require-hashes -r "$bundle\\requirements-runtime.lock"
"""
VERIFY_SCRIPT = r"""from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
for item in manifest["files"]:
    path = (root / item["path"]).resolve()
    if root not in path.parents or not path.is_file():
        raise SystemExit("missing or unsafe release member: " + item["path"])
    data = path.read_bytes()
    if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise SystemExit("release member mismatch: " + item["path"])
print(json.dumps({"status": "PASS", "files": len(manifest["files"])}, separators=(",", ":")))
"""


class ReleaseError(RuntimeError):
    pass


def _wheel_metadata(path: Path) -> dict[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ReleaseError(f"wheel has no unique METADATA: {path.name}")
            message = BytesParser().parsebytes(archive.read(names[0]))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleaseError(f"invalid wheel {path.name}: {exc}") from exc
    name = message.get("Name")
    version = message.get("Version")
    license_value = message.get("License") or "NOASSERTION"
    if not name or not version:
        raise ReleaseError(f"wheel metadata lacks name/version: {path.name}")
    return {"name": name, "version": version, "license": license_value}


def _validate_application_wheel(path: Path) -> None:
    expected = {
        f"audio_story/migrations/{migration.name}": migration.read_bytes()
        for migration in sorted(migration_directory().glob("[0-9][0-9][0-9]_*.sql"))
    }
    try:
        with zipfile.ZipFile(path) as archive:
            actual = {
                name: archive.read(name)
                for name in archive.namelist()
                if name.startswith("audio_story/migrations/") and name.endswith(".sql")
            }
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleaseError(f"invalid application wheel {path.name}: {exc}") from exc
    if actual != expected:
        raise ReleaseError("application wheel migration resources are missing or changed")


def build_release_bundle(
    wheelhouse: Path,
    output: Path,
    *,
    external_inventory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build metadata around pre-provisioned wheels without network access."""
    wheels = sorted(wheelhouse.glob("*.whl"), key=lambda path: path.name.lower())
    if not wheels:
        raise ReleaseError("wheelhouse contains no wheels")
    records = [(path, _wheel_metadata(path), sha256_bytes(path.read_bytes())) for path in wheels]
    normalized_names = {metadata["name"].lower().replace("_", "-") for _, metadata, _ in records}
    if "audio-story-offline" not in normalized_names or "pillow" not in normalized_names:
        raise ReleaseError("wheelhouse must contain audio-story-offline and Pillow")
    for path, metadata, _ in records:
        if metadata["name"].lower().replace("_", "-") == "audio-story-offline":
            _validate_application_wheel(path)
    output.mkdir(parents=True, exist_ok=False)
    destination_wheels = output / "wheelhouse"
    destination_wheels.mkdir()
    for source, _, _ in records:
        shutil.copy2(source, destination_wheels / source.name)
    lock = "".join(
        f"{metadata['name']}=={metadata['version']} --hash=sha256:{digest}\n"
        for _, metadata, digest in records
    )
    (output / "requirements-runtime.lock").write_text(lock, encoding="utf-8", newline="\n")
    components = [
        {
            "type": "library",
            "name": metadata["name"],
            "version": metadata["version"],
            "licenses": [{"license": {"name": metadata["license"]}}],
            "hashes": [{"alg": "SHA-256", "content": digest}],
        }
        for _, metadata, digest in records
    ]
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "components": components,
    }
    (output / "sbom.cdx.json").write_bytes(canonical_json_bytes(sbom))
    inventory = {
        "schema_version": "1.0",
        "policy": "NO_AUTOMATIC_DOWNLOAD",
        "components": external_inventory or [],
    }
    (output / "external-runtime-inventory.json").write_bytes(canonical_json_bytes(inventory))
    (output / "install.ps1").write_text(INSTALL_SCRIPT, encoding="utf-8", newline="\n")
    (output / "verify-release.py").write_text(VERIFY_SCRIPT, encoding="utf-8", newline="\n")
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "release-manifest.json":
            data = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(output).as_posix(),
                    "size": len(data),
                    "sha256": sha256_bytes(data),
                }
            )
    manifest = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "network_policy": "OFFLINE_ONLY",
        "installer": "pip --no-index --require-hashes",
        "files": files,
    }
    (output / "release-manifest.json").write_bytes(canonical_json_bytes(manifest))
    return cast(dict[str, Any], manifest)


def verify_release_bundle(root: Path) -> dict[str, Any]:
    manifest_path = root / "release-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"invalid release manifest: {exc}") from exc
    if manifest.get("schema_version") != RELEASE_SCHEMA_VERSION:
        raise ReleaseError("unsupported release schema")
    for item in manifest.get("files", []):
        relative = Path(str(item.get("path", "")))
        path = (root / relative).resolve()
        resolved_root = root.resolve()
        if resolved_root not in path.parents or not path.is_file():
            raise ReleaseError(f"missing or unsafe release member: {relative}")
        data = path.read_bytes()
        if len(data) != item.get("size") or sha256_bytes(data) != item.get("sha256"):
            raise ReleaseError(f"release member mismatch: {relative}")
    return cast(dict[str, Any], manifest)
