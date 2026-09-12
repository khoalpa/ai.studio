from __future__ import annotations

import io
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from audio_story.domain.state import (
    CallStatus,
    DetectorClass,
    GateStatus,
    StageStatus,
    WorkflowStatus,
)
from audio_story.workflows import KernelError, WorkflowKernel
from audio_story.workflows.package_publication import (
    PublicationFault,
    inventory_package_path,
    publish_package,
    recover_package_publication,
)
from audio_story.workflows.package_quarantine import (
    ImageManifestEntry,
    build_authoritative_image_package,
)

PROMPT = "4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27"
CAPSULE = "a" * 64


def _kernel(tmp_path: Path) -> tuple[WorkflowKernel, str, str]:
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("YOUTH_SAFE", "STAGE1", "CREATE", PROMPT, "b" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE1", CAPSULE)
    kernel.transition_stage(stage, StageStatus.GENERATING)
    return kernel, workflow, stage


def _candidate(
    kernel: WorkflowKernel, stage: str, payload: bytes = b"asset"
) -> tuple[str, str, str]:
    transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "cover.png")
    call = kernel.begin_generation_call(transaction, "c" * 64)
    artifact = kernel.register_candidate(
        call,
        payload,
        "image/png",
        "STAGE1",
        artifact_role="CHARACTER_ASSET",
        dependency_digest="d" * 64,
    )
    kernel.finish_generation_call(call, CallStatus.FINISHED, "e" * 64)
    return transaction, call, artifact


def _pass_gate(kernel: WorkflowKernel, stage: str, artifact: str) -> None:
    kernel.record_gate(
        stage,
        artifact,
        "VALIDATE",
        DetectorClass.DETERMINISTIC,
        GateStatus.PASS,
        {"ok": True},
        PROMPT,
        CAPSULE,
        "1.0",
    )


def test_transaction_retry_commit_progress_events_and_restart(tmp_path: Path) -> None:
    kernel, workflow, stage = _kernel(tmp_path)
    transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "cover.png")
    assert kernel.get_or_create_transaction(stage, "LANDSCAPE", "cover.png") == transaction
    first_call = kernel.begin_generation_call(transaction, "c" * 64)
    kernel.finish_generation_call(first_call, CallStatus.TIMED_OUT, failure_code="TIMEOUT")
    second_call = kernel.begin_generation_call(transaction, "c" * 64)
    assert second_call != first_call
    artifact = kernel.register_candidate(second_call, b"final", "image/png", "STAGE1")
    kernel.finish_generation_call(second_call, CallStatus.FINISHED, "d" * 64)
    assert kernel.progress(stage) == (0, 1)
    _pass_gate(kernel, stage, artifact)
    assert kernel.commit_artifact(transaction, artifact) == artifact
    assert kernel.commit_artifact(transaction, artifact) == artifact
    assert kernel.progress(stage) == (1, 1)
    events = kernel.db.connection.execute(
        "SELECT sequence_no,payload_json,payload_digest FROM events WHERE workflow_id=? ORDER BY sequence_no",
        (workflow,),
    ).fetchall()
    assert [row["sequence_no"] for row in events] == list(range(1, len(events) + 1))
    from audio_story.validation.canonical import sha256_bytes

    assert all(
        sha256_bytes(row["payload_json"].encode()) == row["payload_digest"] for row in events
    )
    kernel.close()
    reopened = WorkflowKernel(tmp_path)
    assert reopened.progress(stage) == (1, 1)
    assert reopened.inspect_workflow(workflow)["canonical_prompt_sha256"] == PROMPT
    reopened.close()


def test_image_authority_metadata_survives_fresh_store_instance(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction, call, artifact = _candidate(kernel, stage, b"image-authority")
    digest = kernel.db.connection.execute(
        "SELECT sha256 FROM artifacts WHERE id=?", (artifact,)
    ).fetchone()[0]
    kernel.store.register_image_candidate(
        digest,
        owner_stage="STAGE1",
        transaction_id=transaction,
        generation_call_id=call,
        delivery_status="AUTHORITATIVE",
        provenance_digest="a" * 64,
        evidence_digest="b" * 64,
        gate_status="PASS",
    )
    kernel.close()

    reopened = WorkflowKernel(tmp_path)
    reopened.store.verify_artifact_ownership(
        digest,
        owner_stage="STAGE1",
        transaction_id=transaction,
        generation_call_id=call,
    )
    reopened.store.verify_artifact_provenance(digest)
    reopened.store.verify_current_pass_gate(digest)
    assert reopened.store.bind_authoritative_artifact(digest) == b"image-authority"
    reopened.store.quarantine_artifact(digest, "PKG900_TEST")
    row = reopened.db.connection.execute(
        "SELECT immutable,quarantine_code,delivery_status FROM image_artifact_authority "
        "WHERE artifact_sha256=?",
        (digest,),
    ).fetchone()
    assert tuple(row) == (1, "PKG900_TEST", "QUARANTINED")
    reopened.close()

    second = WorkflowKernel(tmp_path)
    assert second.store.reconcile_artifact(digest) is True
    second.store.quarantine_artifact(digest, "PKG900_TEST")
    assert (
        second.db.connection.execute(
            "SELECT COUNT(*) FROM image_artifact_authority WHERE artifact_sha256=?", (digest,)
        ).fetchone()[0]
        == 1
    )
    second.close()


def test_authoritative_image_package_reopens_exact_store_bytes(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction, call, artifact = _candidate(kernel, stage, b"image-package")
    row = kernel.db.connection.execute(
        "SELECT sha256,byte_size FROM artifacts WHERE id=?", (artifact,)
    ).fetchone()
    digest, size = row
    kernel.store.register_image_candidate(
        digest,
        owner_stage="STAGE1",
        transaction_id=transaction,
        generation_call_id=call,
        delivery_status="AUTHORITATIVE",
        provenance_digest="a" * 64,
        evidence_digest="b" * 64,
        gate_status="PASS",
    )
    entry = ImageManifestEntry(
        "cover.png",
        "STAGE1",
        "character:1",
        digest,
        size,
        "AUTHORITATIVE",
        "images/cover.png",
        transaction_id=transaction,
        generation_call_id=call,
        evidence_digest="b" * 64,
    )
    first = build_authoritative_image_package(
        tmp_path / "first.zip", (entry,), ("cover.png",), kernel.store
    )
    second = build_authoritative_image_package(
        tmp_path / "second.zip", (entry,), ("cover.png",), kernel.store
    )
    assert first == second
    assert (tmp_path / "first.zip").read_bytes() == (tmp_path / "second.zip").read_bytes()
    kernel.close()


def test_m6_call_transaction_mismatch_has_non_conflicting_stable_code(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    first_tx, _, first_artifact = _candidate(kernel, stage, b"first-lineage")
    second_tx = kernel.get_or_create_transaction(stage, "LANDSCAPE", "second.png")
    second_call = kernel.begin_generation_call(second_tx, "f" * 64)
    with pytest.raises(KernelError) as caught:
        kernel.record_cross_file_result(
            first_tx,
            second_call,
            first_artifact,
            status="PASS",
            error_code=None,
            dependency_digest="1" * 64,
            evidence_digest="2" * 64,
        )
    assert caught.value.code == "RK049_CALL_TRANSACTION_MISMATCH"
    assert (
        kernel.db.connection.execute("SELECT COUNT(*) FROM cross_file_gate_results").fetchone()[0]
        == 0
    )
    kernel.close()


@pytest.mark.parametrize("code", [f"PKG0{value}" for value in range(20, 27)])
def test_cross_file_reject_is_persisted_idempotent_and_blocks_progress(
    tmp_path: Path, code: str
) -> None:
    kernel, workflow, stage = _kernel(tmp_path)
    transaction, call, artifact = _candidate(kernel, stage, code.encode())
    _pass_gate(kernel, stage, artifact)
    digest = kernel.db.connection.execute(
        "SELECT sha256 FROM artifacts WHERE id=?", (artifact,)
    ).fetchone()[0]
    kernel.store.register_image_candidate(
        digest,
        owner_stage="STAGE1",
        transaction_id=transaction,
        generation_call_id=call,
        delivery_status="AUTHORITATIVE",
        provenance_digest="a" * 64,
        evidence_digest="b" * 64,
        gate_status="PASS",
    )
    first = kernel.record_cross_file_result(
        transaction,
        call,
        artifact,
        status="STALE",
        error_code=code,
        dependency_digest="c" * 64,
        evidence_digest="d" * 64,
    )
    second = kernel.record_cross_file_result(
        transaction,
        call,
        artifact,
        status="STALE",
        error_code=code,
        dependency_digest="c" * 64,
        evidence_digest="d" * 64,
    )
    assert first == second
    assert kernel.progress(stage) == (0, 1)
    assert (
        kernel.db.connection.execute(
            "SELECT COUNT(*) FROM artifact_bindings WHERE transaction_id=?", (transaction,)
        ).fetchone()[0]
        == 0
    )
    assert (
        kernel.db.connection.execute(
            "SELECT COUNT(*) FROM cross_file_gate_results WHERE id=?", (first,)
        ).fetchone()[0]
        == 1
    )
    assert (
        kernel.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE workflow_id=? AND event_type='CROSS_FILE_GATE_RECORDED'",
            (workflow,),
        ).fetchone()[0]
        == 1
    )
    kernel.close()

    reopened = WorkflowKernel(tmp_path)
    row = reopened.db.connection.execute(
        "SELECT status,error_code FROM cross_file_gate_results WHERE id=?", (first,)
    ).fetchone()
    assert tuple(row) == ("STALE", code)
    assert reopened.store._image_record(digest)["delivery_status"] == "QUARANTINED"
    assert reopened.progress(stage) == (0, 1)
    reopened.close()


def test_package_lifecycle_stale_restart_and_fresh_republish(tmp_path: Path) -> None:
    kernel, workflow, stage = _kernel(tmp_path)
    old_tx, old_call, old_artifact = _candidate(kernel, stage, b"old-package")
    old_package = kernel.create_image_package(
        old_tx,
        old_call,
        authority_set_digest="a" * 64,
        manifest_digest="b" * 64,
        dependency_digest="c" * 64,
        evidence_digest="d" * 64,
    )
    kernel.pass_image_package(old_package, old_artifact, "e" * 64)
    kernel.publish_image_package(old_package)
    assert kernel.mark_image_packages_stale("a" * 64, "PKG025_STALE_AUTHORITY_SET") == 1
    assert kernel.mark_image_packages_stale("a" * 64, "PKG025_STALE_AUTHORITY_SET") == 0
    kernel.close()

    reopened = WorkflowKernel(tmp_path)
    assert (
        reopened.db.connection.execute(
            "SELECT status FROM image_packages WHERE id=?", (old_package,)
        ).fetchone()[0]
        == "STALE"
    )
    new_tx = reopened.get_or_create_transaction(stage, "LANDSCAPE", "package-v2.zip")
    new_call = reopened.begin_generation_call(new_tx, "f" * 64)
    new_artifact = reopened.register_candidate(
        new_call, b"new-package", "application/zip", "STAGE1", artifact_role="STAGE1_MANIFEST"
    )
    new_package = reopened.create_image_package(
        new_tx,
        new_call,
        authority_set_digest="f" * 64,
        manifest_digest="1" * 64,
        dependency_digest="2" * 64,
        evidence_digest="3" * 64,
        supersedes_id=old_package,
    )
    reopened.pass_image_package(new_package, new_artifact, "4" * 64)
    reopened.publish_image_package(new_package)
    rows = reopened.db.connection.execute(
        "SELECT id,status,supersedes_id,superseded_by_id FROM image_packages ORDER BY created_at,id"
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    assert by_id[old_package]["status"] == "SUPERSEDED"
    assert by_id[old_package]["superseded_by_id"] == new_package
    assert by_id[new_package]["status"] == "PUBLISHED"
    assert by_id[new_package]["supersedes_id"] == old_package
    assert old_tx != new_tx and old_call != new_call
    stale_events = reopened.db.connection.execute(
        "SELECT COUNT(*) FROM events WHERE workflow_id=? AND event_type='IMAGE_PACKAGE_STALE'",
        (workflow,),
    ).fetchone()[0]
    assert stale_events == 1
    reopened.close()


def test_package_state_machine_rejects_invalid_and_duplicate_publish(tmp_path: Path) -> None:
    kernel, workflow, stage = _kernel(tmp_path)
    transaction, call, artifact = _candidate(kernel, stage, b"package-state")
    package = kernel.create_image_package(
        transaction,
        call,
        authority_set_digest="a" * 64,
        manifest_digest="b" * 64,
        dependency_digest="c" * 64,
        evidence_digest="d" * 64,
    )
    with pytest.raises(KernelError, match="only a PASS"):
        kernel.publish_image_package(package)
    kernel.pass_image_package(package, artifact, "e" * 64)
    with pytest.raises(KernelError, match="only a candidate"):
        kernel.pass_image_package(package, artifact, "e" * 64)
    kernel.publish_image_package(package)
    with pytest.raises(KernelError, match="only a PASS"):
        kernel.publish_image_package(package)
    with pytest.raises(KernelError, match="cannot be quarantined"):
        kernel.quarantine_image_package(package, "PKG900")
    assert (
        kernel.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE workflow_id=? AND event_type='IMAGE_PACKAGE_PUBLISHED'",
            (workflow,),
        ).fetchone()[0]
        == 1
    )
    kernel.close()


def test_two_instances_allow_only_one_republish_successor(tmp_path: Path) -> None:
    first, _, stage = _kernel(tmp_path)
    old_tx, old_call, old_artifact = _candidate(first, stage, b"old")
    old = first.create_image_package(
        old_tx,
        old_call,
        authority_set_digest="a" * 64,
        manifest_digest="b" * 64,
        dependency_digest="c" * 64,
        evidence_digest="d" * 64,
    )
    first.pass_image_package(old, old_artifact, "e" * 64)
    first.publish_image_package(old)
    first.mark_image_packages_stale("a" * 64, "PKG025_STALE_AUTHORITY_SET")
    first.close()

    winner = WorkflowKernel(tmp_path)
    loser = WorkflowKernel(tmp_path)
    winner_tx = winner.get_or_create_transaction(stage, "LANDSCAPE", "winner.zip")
    winner_call = winner.begin_generation_call(winner_tx, "1" * 64)
    winner_package = winner.create_image_package(
        winner_tx,
        winner_call,
        authority_set_digest="2" * 64,
        manifest_digest="3" * 64,
        dependency_digest="4" * 64,
        evidence_digest="5" * 64,
        supersedes_id=old,
    )
    loser_tx = loser.get_or_create_transaction(stage, "LANDSCAPE", "loser.zip")
    loser_call = loser.begin_generation_call(loser_tx, "6" * 64)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        loser.create_image_package(
            loser_tx,
            loser_call,
            authority_set_digest="7" * 64,
            manifest_digest="8" * 64,
            dependency_digest="9" * 64,
            evidence_digest="0" * 64,
            supersedes_id=old,
        )
    assert (
        winner.db.connection.execute(
            "SELECT COUNT(*) FROM image_packages WHERE supersedes_id=?", (old,)
        ).fetchone()[0]
        == 1
    )
    assert (
        winner.db.connection.execute(
            "SELECT status FROM image_packages WHERE id=?", (winner_package,)
        ).fetchone()[0]
        == "CANDIDATE"
    )
    winner.close()
    loser.close()


def test_atomic_package_publication_and_recovery_after_rename(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("image_manifest.json", b"{}")
    zip_bytes = buffer.getvalue()
    kernel, _, stage = _kernel(tmp_path)
    transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "publish.zip")
    call = kernel.begin_generation_call(transaction, "a" * 64)
    artifact = kernel.register_candidate(
        call, zip_bytes, "application/zip", "STAGE1", artifact_role="STAGE1_MANIFEST"
    )
    package = kernel.create_image_package(
        transaction,
        call,
        authority_set_digest="b" * 64,
        manifest_digest="c" * 64,
        dependency_digest="d" * 64,
        evidence_digest="e" * 64,
    )
    from audio_story.validation.canonical import sha256_bytes

    kernel.pass_image_package(package, artifact, sha256_bytes(zip_bytes))
    with pytest.raises(KernelError, match="AFTER_RENAME"):
        publish_package(
            kernel,
            package,
            zip_bytes,
            "published/images.zip",
            fault=PublicationFault.AFTER_RENAME,
        )
    assert (
        kernel.db.connection.execute(
            "SELECT status FROM image_packages WHERE id=?", (package,)
        ).fetchone()[0]
        == "PASS"
    )
    kernel.close()

    recovered = WorkflowKernel(tmp_path)
    assert recover_package_publication(recovered, package, "published/images.zip") == "PUBLISHED"
    assert recover_package_publication(recovered, package, "published/images.zip") == "PUBLISHED"
    assert (
        recovered.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_PUBLISHED'"
        ).fetchone()[0]
        == 1
    )
    (tmp_path / "published" / "images.zip").write_bytes(b"tampered")
    assert recover_package_publication(recovered, package) == "QUARANTINED"
    assert recover_package_publication(recovered, package) == "QUARANTINED"
    assert (
        recovered.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_RECOVERY_QUARANTINED'"
        ).fetchone()[0]
        == 1
    )
    recovered.close()


def _publication_candidate(
    tmp_path: Path,
) -> tuple[WorkflowKernel, str, bytes]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("image_manifest.json", b"{}")
    data = buffer.getvalue()
    kernel, _, stage = _kernel(tmp_path)
    transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "fault-package.zip")
    call = kernel.begin_generation_call(transaction, "a" * 64)
    artifact = kernel.register_candidate(
        call, data, "application/zip", "STAGE1", artifact_role="STAGE1_MANIFEST"
    )
    package = kernel.create_image_package(
        transaction,
        call,
        authority_set_digest="b" * 64,
        manifest_digest="c" * 64,
        dependency_digest="d" * 64,
        evidence_digest="e" * 64,
    )
    from audio_story.validation.canonical import sha256_bytes

    kernel.pass_image_package(package, artifact, sha256_bytes(data))
    return kernel, package, data


def test_publication_reject_and_fault_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, package, data = _publication_candidate(tmp_path)
    with pytest.raises(KernelError, match="escapes workspace"):
        publish_package(kernel, package, data, "../escape.zip")
    with pytest.raises(KernelError, match="digest differs"):
        publish_package(kernel, package, data + b"tamper", "published/digest.zip")
    with pytest.raises(KernelError, match="AFTER_TEMP_WRITE"):
        publish_package(
            kernel,
            package,
            data,
            "published/temp.zip",
            fault=PublicationFault.AFTER_TEMP_WRITE,
        )
    with pytest.raises(KernelError, match="BEFORE_SQLITE_COMMIT"):
        publish_package(
            kernel,
            package,
            data,
            "published/temp.zip",
            fault=PublicationFault.BEFORE_SQLITE_COMMIT,
        )
    assert (
        kernel.db.connection.execute(
            "SELECT status FROM image_packages WHERE id=?", (package,)
        ).fetchone()[0]
        == "PASS"
    )
    assert recover_package_publication(kernel, package) == "PUBLISHED"
    with pytest.raises(KernelError, match="does not exist"):
        recover_package_publication(kernel, "missing")
    kernel.close()


def test_publication_temp_reopen_and_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, package, data = _publication_candidate(tmp_path)
    original_read = Path.read_bytes

    def corrupt_temp(path: Path) -> bytes:
        value = original_read(path)
        return b"corrupt" if path.suffix == ".tmp" else value

    monkeypatch.setattr(Path, "read_bytes", corrupt_temp)
    with pytest.raises(KernelError, match="temporary ZIP reopen mismatch"):
        publish_package(kernel, package, data, "published/reopen.zip")
    monkeypatch.setattr(Path, "read_bytes", original_read)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr("audio_story.workflows.package_publication.os.replace", fail_replace)
    with pytest.raises(KernelError, match="filesystem operation failed"):
        publish_package(kernel, package, data, "published/reopen.zip")
    assert (
        kernel.db.connection.execute(
            "SELECT status FROM image_packages WHERE id=?", (package,)
        ).fetchone()[0]
        == "PASS"
    )
    kernel.close()


def test_persisted_orphan_inventory_is_authority_checked_and_idempotent(tmp_path: Path) -> None:
    kernel, package, data = _publication_candidate(tmp_path)
    orphan = tmp_path / "published" / "unknown.zip"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(data)
    first = inventory_package_path(kernel, "published/unknown.zip", "CANONICAL")
    second = inventory_package_path(kernel, "published/unknown.zip", "CANONICAL")
    assert first == second
    assert (
        kernel.db.connection.execute(
            "SELECT classification FROM package_orphan_inventory WHERE id=?", (first,)
        ).fetchone()[0]
        == "ORPHANED"
    )

    owned = tmp_path / "published" / "owned.zip"
    owned.write_bytes(data)
    kernel.register_image_package_target(package, "published/owned.zip")
    owned_id = inventory_package_path(
        kernel, "published/owned.zip", "CANONICAL", expected_package_id=package
    )
    assert (
        kernel.db.connection.execute(
            "SELECT classification FROM package_orphan_inventory WHERE id=?", (owned_id,)
        ).fetchone()[0]
        == "OWNED_RECOVERABLE"
    )
    mismatch = tmp_path / "published" / "wrong.zip"
    mismatch.write_bytes(data)
    mismatch_id = inventory_package_path(
        kernel, "published/wrong.zip", "CANONICAL", expected_package_id=package
    )
    assert (
        kernel.db.connection.execute(
            "SELECT classification FROM package_orphan_inventory WHERE id=?", (mismatch_id,)
        ).fetchone()[0]
        == "MISMATCH"
    )
    assert (
        kernel.db.connection.execute("SELECT COUNT(*) FROM package_orphan_inventory").fetchone()[0]
        == 3
    )
    assert owned.read_bytes() == data and mismatch.read_bytes() == data
    kernel.close()

    reopened = WorkflowKernel(tmp_path)
    assert (
        inventory_package_path(
            reopened, "published/owned.zip", "CANONICAL", expected_package_id=package
        )
        == owned_id
    )
    assert (
        reopened.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='PACKAGE_FILE_INVENTORIED'"
        ).fetchone()[0]
        == 2
    )
    reopened.close()


def test_publication_sqlite_faults_rollback_lifecycle_and_event(tmp_path: Path) -> None:
    kernel, package, data = _publication_candidate(tmp_path)
    for fault_stage in ("AFTER_LIFECYCLE", "AFTER_SUPERSESSION", "AFTER_EVENT"):
        with pytest.raises(KernelError, match=fault_stage):
            kernel.finalize_image_package_publication(
                package,
                "published/fault.zip",
                len(data),
                fault_stage=fault_stage,
            )
        assert (
            kernel.db.connection.execute(
                "SELECT status,published_relative_path FROM image_packages WHERE id=?", (package,)
            ).fetchone()[0]
            == "PASS"
        )
        assert (
            kernel.db.connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_PUBLISHED'"
            ).fetchone()[0]
            == 0
        )

    kernel.db.connection.execute(
        "CREATE TEMP TRIGGER fail_publish_event BEFORE INSERT ON events "
        "WHEN NEW.event_type='IMAGE_PACKAGE_PUBLISHED' BEGIN SELECT RAISE(ABORT,'event fault'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="event fault"):
        kernel.finalize_image_package_publication(package, "published/fault.zip", len(data))
    assert (
        kernel.db.connection.execute(
            "SELECT status FROM image_packages WHERE id=?", (package,)
        ).fetchone()[0]
        == "PASS"
    )
    assert (
        kernel.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_PUBLISHED'"
        ).fetchone()[0]
        == 0
    )
    kernel.close()


def test_begin_immediate_lock_rolls_back_publication(tmp_path: Path) -> None:
    owner, package, data = _publication_candidate(tmp_path)
    contender = WorkflowKernel(tmp_path, busy_timeout_ms=10)
    owner.db.connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            contender.finalize_image_package_publication(package, "published/locked.zip", len(data))
    finally:
        owner.db.connection.rollback()
    assert (
        contender.db.connection.execute(
            "SELECT status FROM image_packages WHERE id=?", (package,)
        ).fetchone()[0]
        == "PASS"
    )
    assert (
        contender.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_PUBLISHED'"
        ).fetchone()[0]
        == 0
    )
    owner.close()
    contender.close()


def test_two_fresh_kernels_reconcile_one_publication_event(tmp_path: Path) -> None:
    kernel, package, data = _publication_candidate(tmp_path)
    with pytest.raises(KernelError, match="AFTER_RENAME"):
        publish_package(
            kernel,
            package,
            data,
            "published/race.zip",
            fault=PublicationFault.AFTER_RENAME,
        )
    kernel.close()

    def recover() -> str:
        instance = WorkflowKernel(tmp_path)
        try:
            return recover_package_publication(instance, package)
        finally:
            instance.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: recover(), range(2)))
    assert results == ("PUBLISHED", "PUBLISHED")
    reopened = WorkflowKernel(tmp_path)
    assert (
        reopened.db.connection.execute(
            "SELECT status FROM image_packages WHERE id=?", (package,)
        ).fetchone()[0]
        == "PUBLISHED"
    )
    assert (
        reopened.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_PUBLISHED'"
        ).fetchone()[0]
        == 1
    )
    reopened.close()


def test_connection_interruption_after_rename_recovers_from_inventory(tmp_path: Path) -> None:
    kernel, package, data = _publication_candidate(tmp_path)
    with pytest.raises(KernelError, match="CONNECTION_INTERRUPTION"):
        publish_package(
            kernel,
            package,
            data,
            "published/interrupted.zip",
            fault=PublicationFault.CONNECTION_INTERRUPTION,
        )
    reopened = WorkflowKernel(tmp_path)
    inventory = inventory_package_path(
        reopened,
        "published/interrupted.zip",
        "CANONICAL",
        expected_package_id=package,
    )
    assert (
        reopened.db.connection.execute(
            "SELECT classification FROM package_orphan_inventory WHERE id=?", (inventory,)
        ).fetchone()[0]
        == "OWNED_RECOVERABLE"
    )
    assert recover_package_publication(reopened, package) == "PUBLISHED"
    reconciled = inventory_package_path(
        reopened,
        "published/interrupted.zip",
        "CANONICAL",
        expected_package_id=package,
    )
    assert reconciled != inventory
    assert (
        inventory_package_path(
            reopened,
            "published/interrupted.zip",
            "CANONICAL",
            expected_package_id=package,
        )
        == reconciled
    )
    assert recover_package_publication(reopened, package) == "PUBLISHED"
    assert (
        reopened.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_PUBLISHED'"
        ).fetchone()[0]
        == 1
    )
    reopened.close()


def test_publication_cancellation_before_write_and_after_rename_is_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kernel, package, data = _publication_candidate(tmp_path)
    cancellation = Event()
    cancellation.set()
    with pytest.raises(KernelError) as before:
        publish_package(
            kernel,
            package,
            data,
            "published/cancelled-before.zip",
            cancellation=cancellation,
        )
    assert before.value.code == "RK040_PACKAGE_PUBLICATION_CANCELLED"
    assert not (tmp_path / "published" / "cancelled-before.zip").exists()

    cancellation.clear()
    original_replace = __import__(
        "audio_story.workflows.package_publication", fromlist=["os"]
    ).os.replace

    def replace_then_cancel(source: Path, destination: Path) -> None:
        original_replace(source, destination)
        cancellation.set()

    monkeypatch.setattr("audio_story.workflows.package_publication.os.replace", replace_then_cancel)
    with pytest.raises(KernelError) as after:
        publish_package(
            kernel,
            package,
            data,
            "published/cancelled-after.zip",
            cancellation=cancellation,
        )
    assert after.value.code == "RK040_PACKAGE_PUBLICATION_CANCELLED"
    assert (
        kernel.db.connection.execute(
            "SELECT status FROM image_packages WHERE id=?", (package,)
        ).fetchone()[0]
        == "PASS"
    )
    kernel.close()

    recovered = WorkflowKernel(tmp_path)
    assert recover_package_publication(recovered, package) == "PUBLISHED"
    assert recover_package_publication(recovered, package) == "PUBLISHED"
    assert (
        recovered.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_PUBLISHED'"
        ).fetchone()[0]
        == 1
    )
    recovered.close()


def test_two_fresh_kernels_recover_one_supersession_pair(tmp_path: Path) -> None:
    first, old, old_bytes = _publication_candidate(tmp_path)
    publish_package(first, old, old_bytes, "published/old.zip")
    first.mark_image_packages_stale("b" * 64, "PKG025_STALE_AUTHORITY_SET")
    stage = first.db.connection.execute(
        "SELECT stage_run_id FROM asset_transactions t JOIN image_packages p "
        "ON p.package_transaction_id=t.id WHERE p.id=?",
        (old,),
    ).fetchone()[0]
    new_tx = first.get_or_create_transaction(stage, "LANDSCAPE", "successor.zip")
    new_call = first.begin_generation_call(new_tx, "f" * 64)
    new_artifact = first.register_candidate(
        new_call,
        old_bytes,
        "application/zip",
        "STAGE1",
        artifact_role="STAGE1_MANIFEST",
    )
    successor = first.create_image_package(
        new_tx,
        new_call,
        authority_set_digest="1" * 64,
        manifest_digest="2" * 64,
        dependency_digest="3" * 64,
        evidence_digest="4" * 64,
    )
    from audio_story.validation.canonical import sha256_bytes

    first.pass_image_package(successor, new_artifact, sha256_bytes(old_bytes))
    publish_package(first, successor, old_bytes, "published/new.zip")
    first.db.connection.execute(
        "UPDATE image_packages SET supersedes_id=? WHERE id=?", (old, successor)
    )
    first.close()

    def recover() -> str:
        instance = WorkflowKernel(tmp_path)
        try:
            return instance.recover_image_package_supersession(successor)
        finally:
            instance.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert tuple(pool.map(lambda _: recover(), range(2))) == (
            "SUPERSEDED",
            "SUPERSEDED",
        )
    reopened = WorkflowKernel(tmp_path)
    old_row = reopened.db.connection.execute(
        "SELECT status,superseded_by_id FROM image_packages WHERE id=?", (old,)
    ).fetchone()
    new_row = reopened.db.connection.execute(
        "SELECT status,supersedes_id FROM image_packages WHERE id=?", (successor,)
    ).fetchone()
    assert tuple(old_row) == ("SUPERSEDED", successor)
    assert tuple(new_row) == ("PUBLISHED", old)
    assert (
        reopened.db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_SUPERSESSION_RECOVERED'"
        ).fetchone()[0]
        == 1
    )
    assert (tmp_path / "published" / "old.zip").read_bytes() == old_bytes
    assert (tmp_path / "published" / "new.zip").read_bytes() == old_bytes
    reopened.close()


def test_double_commit_different_bytes_and_read_only_mutation_are_rejected(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction, _, artifact = _candidate(kernel, stage, b"one")
    _pass_gate(kernel, stage, artifact)
    kernel.commit_artifact(transaction, artifact)
    other_transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "other.png")
    call = kernel.begin_generation_call(other_transaction, "c" * 64)
    other = kernel.register_candidate(call, b"two", "image/png", "STAGE1")
    with pytest.raises(KernelError, match="different bytes"):
        kernel.commit_artifact(transaction, other)
    with pytest.raises(KernelError) as caught:
        kernel.quarantine_artifact(artifact, stage)
    assert caught.value.code == "RK009_READ_ONLY_MUTATION"
    kernel.close()


def test_rejected_candidate_and_stale_gate_do_not_increase_progress(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction, _, artifact = _candidate(kernel, stage)
    kernel.record_gate(
        stage,
        artifact,
        "PNG",
        DetectorClass.DETERMINISTIC,
        GateStatus.PASS,
        {"ok": True},
        PROMPT,
        CAPSULE,
        "1.0",
        "old",
    )
    assert kernel.mark_dependency_stale(artifact, "new") == 1
    assert kernel.db.connection.execute("SELECT is_current FROM gate_results").fetchone()[0] == 0
    with pytest.raises(KernelError) as caught:
        kernel.commit_artifact(transaction, artifact)
    assert caught.value.code == "RK016_GATE_NOT_CURRENT_PASS"
    kernel.quarantine_artifact(artifact, stage)
    assert kernel.progress(stage) == (0, 1)
    assert transaction
    kernel.close()


def test_owner_mismatch_and_invalid_call_finish_fail_before_publish(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "cover.png")
    call = kernel.begin_generation_call(transaction, "c" * 64)
    with pytest.raises(KernelError) as caught:
        kernel.register_candidate(call, b"bad", "image/png", "STAGE2")
    assert caught.value.code == "RK014_OWNER_STAGE_MISMATCH"
    with pytest.raises(KernelError) as caught:
        kernel.register_candidate(
            call, b"bad-role", "image/png", "STAGE1", artifact_role="PORTRAIT"
        )
    assert caught.value.code == "RK015_ROLE_OWNER_MISMATCH"
    with pytest.raises(KernelError) as caught:
        kernel.finish_generation_call(call, CallStatus.RUNNING)
    assert caught.value.code == "RK008_INVALID_CALL_FINISH"
    kernel.close()


def test_workspace_lease_detects_conflict_and_allows_stale_takeover(tmp_path: Path) -> None:
    first = WorkflowKernel(tmp_path)
    second = WorkflowKernel(tmp_path)
    first.acquire_lease("workspace", "owner-a", 30)
    with pytest.raises(KernelError) as caught:
        second.acquire_lease("workspace", "owner-b", 30)
    assert caught.value.code == "RK012_LEASE_CONFLICT"
    first.db.connection.execute(
        "UPDATE workspace_leases SET expires_at='2000-01-01T00:00:00Z' WHERE workspace_id='workspace'"
    )
    second.acquire_lease("workspace", "owner-b", 30)
    first.close()
    second.close()


def test_store_dedup_and_commit_digest_mismatch_are_guarded(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction, _, artifact = _candidate(kernel, stage, b"same")
    second_transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "second.png")
    second_call = kernel.begin_generation_call(second_transaction, "f" * 64)
    duplicate = kernel.register_candidate(second_call, b"same", "image/png", "STAGE1")
    assert duplicate == artifact
    _pass_gate(kernel, stage, artifact)
    row = kernel.db.connection.execute(
        "SELECT relative_path FROM artifacts WHERE id=?", (artifact,)
    ).fetchone()
    (kernel.workspace / row["relative_path"]).write_bytes(b"tampered")
    with pytest.raises(KernelError) as caught:
        kernel.commit_artifact(transaction, artifact)
    assert caught.value.code == "RK011_ARTIFACT_DIGEST_MISMATCH"
    kernel.close()


def test_unvalidated_candidate_cannot_commit(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    transaction, _, artifact = _candidate(kernel, stage)
    with pytest.raises(KernelError) as caught:
        kernel.commit_artifact(transaction, artifact)
    assert caught.value.code == "RK017_CANDIDATE_NOT_VALIDATED"
    kernel.close()


def test_two_instances_claim_same_logical_transaction(tmp_path: Path) -> None:
    first, _, stage = _kernel(tmp_path)
    second = WorkflowKernel(tmp_path)
    first_id = first.get_or_create_transaction(stage, "LANDSCAPE", "shared.png")
    second_id = second.get_or_create_transaction(stage, "LANDSCAPE", "shared.png")
    assert second_id == first_id
    first.close()
    second.close()


def test_call_and_commit_enforce_transaction_lineage(tmp_path: Path) -> None:
    kernel, _, stage = _kernel(tmp_path)
    first_transaction, _, first_artifact = _candidate(kernel, stage, b"first")
    second_transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "second.png")
    second_call = kernel.begin_generation_call(second_transaction, "d" * 64)
    second_artifact = kernel.register_candidate(
        second_call,
        b"second",
        "image/png",
        "STAGE1",
        artifact_role="CHARACTER_ASSET",
    )
    kernel.finish_generation_call(second_call, CallStatus.FINISHED, "e" * 64)
    _pass_gate(kernel, stage, first_artifact)
    _pass_gate(kernel, stage, second_artifact)

    with pytest.raises(KernelError) as caught:
        kernel.commit_artifact(first_transaction, second_artifact)
    assert caught.value.code == "RK019_ARTIFACT_TRANSACTION_MISMATCH"

    kernel.commit_artifact(first_transaction, first_artifact)
    with pytest.raises(KernelError) as caught:
        kernel.begin_generation_call(first_transaction, "f" * 64)
    assert caught.value.code == "RK018_TRANSACTION_NOT_CALLABLE"

    active_transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "active.png")
    kernel.begin_generation_call(active_transaction, "a" * 64)
    with pytest.raises(KernelError) as caught:
        kernel.begin_generation_call(active_transaction, "b" * 64)
    assert caught.value.code == "RK018_TRANSACTION_NOT_CALLABLE"
    kernel.close()
