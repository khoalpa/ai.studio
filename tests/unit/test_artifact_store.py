from __future__ import annotations

import hashlib
from pathlib import Path, PureWindowsPath

import pytest

from audio_story.artifacts.store import ArtifactStore, FaultPoint, StoreError


def test_content_addressed_store_is_atomic_reopened_and_deduplicated(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    first = store.put(b"exact bytes")
    second = store.put(b"exact bytes")
    assert first.digest == hashlib.sha256(b"exact bytes").hexdigest()
    assert store.read(first.relative_path) == b"exact bytes"
    assert second.deduplicated is True


def test_fault_boundaries_before_temp_after_temp_and_after_rename(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(StoreError):
        store.put(b"before", FaultPoint.BEFORE_TEMP_WRITE)
    assert not store.orphan_temps()
    with pytest.raises(StoreError):
        store.put(b"temporary", FaultPoint.AFTER_TEMP_WRITE)
    assert len(store.orphan_temps()) == 1
    with pytest.raises(StoreError):
        store.put(b"renamed", FaultPoint.AFTER_RENAME)
    digest = hashlib.sha256(b"renamed").hexdigest()
    assert store.path_for(digest).read_bytes() == b"renamed"


def test_invalid_digest_path_escape_and_cross_volume_guard(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store = ArtifactStore(tmp_path)
    with pytest.raises(StoreError, match="lowercase"):
        store.path_for("BAD")
    with pytest.raises(StoreError, match="escapes"):
        store.read("../outside")
    with pytest.raises(StoreError, match="escapes"):
        store.read(str(PureWindowsPath("C:/outside.bin")))
    monkeypatch.setattr(store, "_same_volume", lambda temporary, parent: False)
    with pytest.raises(StoreError, match="different volumes"):
        store.put(b"cross-volume")
