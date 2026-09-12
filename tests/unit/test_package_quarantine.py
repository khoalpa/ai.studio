from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from audio_story.artifacts.store import ArtifactStore
from audio_story.workflows.package_quarantine import (
    CrossFileEvidence,
    ImageManifestEntry,
    image_digest,
    validate_cross_file_evidence,
    validate_image_package,
    verify_artifact_store_entry,
)


def _entry() -> ImageManifestEntry:
    return ImageManifestEntry(
        "cover.png",
        "STAGE1",
        "character:1",
        "a" * 64,
        10,
        "AUTHORITATIVE",
        "images/cover.png",
        transaction_id="tx",
        generation_call_id="call",
        evidence_digest="b" * 64,
    )


@pytest.mark.parametrize(
    ("entries", "allowlist", "code"),
    [
        ((_entry(), _entry()), ("cover.png",), "PKG001"),
        ((_entry(),), ("other.png",), "PKG002"),
        ((replace(_entry(), status="DRAFT_ONLY"),), ("cover.png",), "PKG003"),
        ((replace(_entry(), digest="bad"),), ("cover.png",), "PKG004"),
        ((replace(_entry(), size=0),), ("cover.png",), "PKG005"),
        ((replace(_entry(), relative_path="../cover.png"),), ("cover.png",), "PKG006"),
        ((replace(_entry(), media_type="text/plain"),), ("cover.png",), "PKG007"),
        ((replace(_entry(), mutation_status="MUTATED"),), ("cover.png",), "PKG008"),
        ((replace(_entry(), evidence_digest=""),), ("cover.png",), "PKG009"),
    ],
)
def test_quarantine_reject_codes(
    entries: tuple[ImageManifestEntry, ...], allowlist: tuple[str, ...], code: str
) -> None:
    with pytest.raises(ValueError, match=code):
        validate_image_package(entries, allowlist)


def test_store_entry_missing_and_mutated_bytes(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="PKG010"):
        verify_artifact_store_entry(_entry(), store)
    stored = store.put(b"0123456789")
    entry = replace(_entry(), digest=stored.digest)
    store.path_for(stored.digest).write_bytes(b"mutated!!!")
    with pytest.raises(ValueError, match="PKG011"):
        verify_artifact_store_entry(entry, store)


def _cross(entry: ImageManifestEntry) -> CrossFileEvidence:
    return CrossFileEvidence(
        entry.character_id,
        entry.digest,
        entry.owner_stage,
        entry.digest,
        "c" * 64,
        "c" * 64,
        image_digest(b"manifest"),
        image_digest(b"authority"),
    )


def test_cross_file_evidence_passes_for_exact_dependencies() -> None:
    entry = _entry()
    validate_cross_file_evidence(
        entry,
        _cross(entry),
        expected_character_id="character:1",
        expected_owner_stage="STAGE1",
        manifest_bytes=b"manifest",
        authority_set_bytes=b"authority",
    )


@pytest.mark.parametrize(
    ("evidence", "entry", "character", "owner", "manifest", "authority", "code"),
    [
        (_cross(_entry()), _entry(), "character:2", "STAGE1", b"manifest", b"authority", "PKG020"),
        (_cross(_entry()), _entry(), "character:1", "STAGE2", b"manifest", b"authority", "PKG021"),
        (
            replace(_cross(_entry()), ocr_image_digest="d" * 64),
            _entry(),
            "character:1",
            "STAGE1",
            b"manifest",
            b"authority",
            "PKG022",
        ),
        (
            replace(_cross(_entry()), typography_base_digest="d" * 64),
            _entry(),
            "character:1",
            "STAGE1",
            b"manifest",
            b"authority",
            "PKG023",
        ),
        (_cross(_entry()), _entry(), "character:1", "STAGE1", b"changed", b"authority", "PKG024"),
        (_cross(_entry()), _entry(), "character:1", "STAGE1", b"manifest", b"changed", "PKG025"),
        (
            replace(_cross(_entry()), anchor_required=True),
            _entry(),
            "character:1",
            "STAGE1",
            b"manifest",
            b"authority",
            "PKG026",
        ),
    ],
)
def test_cross_file_mutation_is_stale(
    evidence: CrossFileEvidence,
    entry: ImageManifestEntry,
    character: str,
    owner: str,
    manifest: bytes,
    authority: bytes,
    code: str,
) -> None:
    with pytest.raises(ValueError, match=code):
        validate_cross_file_evidence(
            entry,
            evidence,
            expected_character_id=character,
            expected_owner_stage=owner,
            manifest_bytes=manifest,
            authority_set_bytes=authority,
        )
