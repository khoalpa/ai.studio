"""Deterministic package-level image quarantine and cross-file gates."""

from __future__ import annotations

import json
import tempfile
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from audio_story.artifacts.store import ArtifactStore, StoreError
from audio_story.validation.archives import inspect_zip, safe_extract
from audio_story.validation.canonical import canonical_json_bytes


@dataclass(frozen=True, slots=True)
class ImageManifestEntry:
    basename: str
    owner_stage: str
    character_id: str
    digest: str
    size: int
    status: str
    relative_path: str = ""
    media_type: str = "image/png"
    mutation_status: str = "UNMUTATED"
    transaction_id: str = ""
    generation_call_id: str = ""
    evidence_digest: str = ""


@dataclass(frozen=True, slots=True)
class CrossFileEvidence:
    character_id: str
    image_digest: str
    owner_stage: str
    ocr_image_digest: str
    typography_base_digest: str
    expected_base_digest: str
    manifest_digest: str
    authority_set_digest: str
    anchor_required: bool = False
    anchor_digest: str | None = None


def validate_image_package(
    entries: tuple[ImageManifestEntry, ...], allowlist: tuple[str, ...]
) -> None:
    names = tuple(item.basename for item in entries)
    if len(names) != len(set(names)):
        raise ValueError("PKG001_DUPLICATE_BASENAME")
    if set(names) != set(allowlist):
        raise ValueError("PKG002_ALLOWLIST_MISMATCH")
    for item in entries:
        if item.status != "AUTHORITATIVE":
            raise ValueError("PKG003_NON_AUTHORITATIVE")
        if len(item.digest) != 64 or any(c not in "0123456789abcdef" for c in item.digest):
            raise ValueError("PKG004_DIGEST_INVALID")
        if item.size <= 0:
            raise ValueError("PKG005_SIZE_INVALID")
        if (
            not item.relative_path
            or item.relative_path.startswith("/")
            or ".." in item.relative_path.split("/")
        ):
            raise ValueError("PKG006_PATH_INVALID")
        if item.media_type != "image/png":
            raise ValueError("PKG007_MEDIA_TYPE")
        if item.mutation_status != "UNMUTATED":
            raise ValueError("PKG008_MUTATED_ARTIFACT")
        if (
            not item.transaction_id
            or not item.generation_call_id
            or len(item.evidence_digest) != 64
        ):
            raise ValueError("PKG009_PROVENANCE_MISSING")


def image_digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def validate_cross_file_evidence(
    entry: ImageManifestEntry,
    evidence: CrossFileEvidence,
    *,
    expected_character_id: str,
    expected_owner_stage: str,
    manifest_bytes: bytes,
    authority_set_bytes: bytes,
) -> None:
    """Bind current image authority to identity, OCR, typography and manifest bytes."""
    if (
        entry.character_id != expected_character_id
        or evidence.character_id != expected_character_id
    ):
        raise ValueError("PKG020_CHARACTER_IDENTITY")
    if entry.owner_stage != expected_owner_stage or evidence.owner_stage != expected_owner_stage:
        raise ValueError("PKG021_OWNER_STAGE")
    if evidence.image_digest != entry.digest or evidence.ocr_image_digest != entry.digest:
        raise ValueError("PKG022_STALE_OCR_EVIDENCE")
    if evidence.typography_base_digest != evidence.expected_base_digest:
        raise ValueError("PKG023_STALE_TYPOGRAPHY_EVIDENCE")
    if image_digest(manifest_bytes) != evidence.manifest_digest:
        raise ValueError("PKG024_STALE_MANIFEST")
    if image_digest(authority_set_bytes) != evidence.authority_set_digest:
        raise ValueError("PKG025_STALE_AUTHORITY_SET")
    if evidence.anchor_required != (evidence.anchor_digest is not None):
        raise ValueError("PKG026_ANCHOR_APPLICABILITY")


def verify_artifact_store_entry(entry: ImageManifestEntry, store: ArtifactStore) -> bytes:
    """Read and verify immutable content-addressed bytes before packaging."""
    try:
        path = store.path_for(entry.digest)
        data = path.read_bytes()
    except (OSError, StoreError) as exc:
        raise ValueError("PKG010_ARTIFACT_MISSING") from exc
    if len(data) != entry.size or image_digest(data) != entry.digest:
        raise ValueError("PKG011_ARTIFACT_DIGEST_SIZE")
    expected = Path(entry.relative_path).as_posix()
    if not expected or expected.startswith("/") or ".." in expected.split("/"):
        raise ValueError("PKG006_PATH_INVALID")
    return data


def build_authoritative_image_package(
    output: Path,
    entries: tuple[ImageManifestEntry, ...],
    allowlist: tuple[str, ...],
    store: ArtifactStore,
) -> str:
    """Freeze verified artifacts, build a deterministic ZIP, and revalidate extraction."""
    validate_image_package(entries, allowlist)
    frozen: OrderedDict[str, bytes] = OrderedDict()
    manifest_entries: list[dict[str, object]] = []
    for entry in entries:
        data = verify_artifact_store_entry(entry, store)
        store.verify_artifact_ownership(
            entry.digest,
            owner_stage=entry.owner_stage,
            transaction_id=entry.transaction_id,
            generation_call_id=entry.generation_call_id,
        )
        store.verify_artifact_provenance(entry.digest)
        store.verify_current_pass_gate(entry.digest)
        frozen[entry.relative_path] = data
        manifest_entries.append(
            {
                "path": entry.relative_path,
                "sha256": entry.digest,
                "size_bytes": entry.size,
                "media_type": entry.media_type,
                "owner_stage": entry.owner_stage,
                "mutation_status": entry.mutation_status,
                "transaction_id": entry.transaction_id,
                "generation_call_id": entry.generation_call_id,
                "evidence_digest": entry.evidence_digest,
            }
        )
    manifest = canonical_json_bytes(
        {"schema_version": "M6A-1", "file_count": len(frozen), "files": manifest_entries}
    )
    members: OrderedDict[str, bytes] = OrderedDict(
        [("image_manifest.json", manifest), *frozen.items()]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with tempfile.TemporaryDirectory(prefix="audio-story-m6a-") as parent:
        actual_order = tuple(item.path for item in inspect_zip(output))
        if actual_order != tuple(members):
            raise ValueError("PKG012_MEMBER_ORDER")
        root = safe_extract(output, Path(parent))
        extracted_manifest = json.loads((root / "image_manifest.json").read_bytes())
        if extracted_manifest["files"] != manifest_entries:
            raise ValueError("PKG013_MANIFEST_MISMATCH")
        for name, source in frozen.items():
            if (root / name).read_bytes() != source:
                raise ValueError("PKG014_SOURCE_EXTRACTED_MISMATCH")
    return image_digest(output.read_bytes())
