from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def promote_cover_in_bundle(
    *, source_bundle: Path, approved_cover: Path, output_bundle: Path, backup_cover: Path,
    metadata_updates: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Replace only landscape/cover.png while retaining a byte-exact rollback copy."""
    cover_entry = "landscape/cover.png"
    with zipfile.ZipFile(source_bundle, "r") as source:
        entries = {info.filename: source.read(info.filename) for info in source.infolist()}
    if cover_entry not in entries:
        raise ValueError(f"Source bundle does not contain {cover_entry}")

    original_cover = entries[cover_entry]
    promoted_cover = approved_cover.read_bytes()
    if original_cover == promoted_cover:
        raise ValueError("Approved cover is byte-identical to the current bundle cover")

    backup_cover.parent.mkdir(parents=True, exist_ok=True)
    backup_cover.write_bytes(original_cover)
    replacements = {cover_entry: promoted_cover, **(metadata_updates or {})}
    missing_metadata = sorted(set(replacements) - set(entries))
    if missing_metadata:
        raise ValueError(f"Source bundle lacks metadata entries: {missing_metadata}")
    output_bundle.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_bundle, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, data in entries.items():
            target.writestr(name, replacements.get(name, data))

    with zipfile.ZipFile(output_bundle, "r") as promoted:
        promoted_entries = {
            info.filename: promoted.read(info.filename) for info in promoted.infolist()
        }
    if set(promoted_entries) != set(entries):
        raise RuntimeError("Promotion changed the bundle entry set")
    changed = [name for name in entries if entries[name] != promoted_entries[name]]
    expected_changed = [name for name in entries if name in replacements]
    if changed != expected_changed:
        raise RuntimeError(f"Promotion changed unexpected entries: {changed}")
    if backup_cover.read_bytes() != original_cover:
        raise RuntimeError("Rollback cover does not match the original bundle cover")

    return {
        "source_bundle_sha256": sha256_bytes(source_bundle.read_bytes()),
        "promoted_bundle_sha256": sha256_bytes(output_bundle.read_bytes()),
        "original_cover_sha256": sha256_bytes(original_cover),
        "approved_cover_sha256": sha256_bytes(promoted_cover),
        "rollback_cover_sha256": sha256_bytes(backup_cover.read_bytes()),
        "entry_count": len(entries),
        "changed_entries": changed,
        "rollback_verified": True,
    }
