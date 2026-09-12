from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from audio_story.adapters.image import DeterministicMockImageAdapter, ImageRequest
from audio_story.domain.state import CallStatus, DetectorClass, GateStatus, WorkflowStatus
from audio_story.validation.canonical import sha256_bytes
from audio_story.validation.images import validate_image_qa
from audio_story.workflows import KernelError, WorkflowKernel
from audio_story.workflows.package_publication import (
    PublicationFault,
    publish_package,
    recover_package_publication,
)
from audio_story.workflows.recovery import recover
from audio_story.workflows.typography import render_cover, validate_cover

PROMPT = "4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27"


@dataclass(frozen=True, slots=True)
class Boundary:
    name: str
    phase: int
    stable_code: str


BOUNDARIES = (
    Boundary("before_image_request", 0, "RK_CLEAN"),
    Boundary("after_image_request", 1, "RK_CALL_INTERRUPTED"),
    Boundary("after_response_before_png_qa", 2, "RK_STORE_ORPHAN_FOUND"),
    Boundary("after_png_qa_before_candidate", 3, "RK_STORE_ORPHAN_FOUND"),
    Boundary("after_candidate_before_authority", 4, "RK_TRANSACTION_INTERRUPTED"),
    Boundary("after_authority_before_gate", 5, "RK_TRANSACTION_INTERRUPTED"),
    Boundary("after_gate_before_binding", 6, "RK_TRANSACTION_INTERRUPTED"),
    Boundary("after_binding_before_commit", 7, "RK_TRANSACTION_INTERRUPTED"),
    Boundary("before_typography", 8, "RK_CALL_INTERRUPTED"),
    Boundary("after_typography", 9, "RK_STORE_ORPHAN_FOUND"),
    Boundary("before_ocr_evidence", 10, "RK_CALL_INTERRUPTED"),
    Boundary("after_ocr_before_cross_file", 11, "RK_TRANSACTION_INTERRUPTED"),
    Boundary("after_cross_file_validation", 12, "RK_TRANSACTION_INTERRUPTED"),
    Boundary("after_authority_set_freeze", 13, "RK_TRANSACTION_INTERRUPTED"),
    Boundary("after_manifest_creation", 14, "RK_TRANSACTION_INTERRUPTED"),
    Boundary("after_zip_creation", 15, "RK_TRANSACTION_INTERRUPTED"),
    Boundary("after_package_pass_before_publish", 16, "RK900_INJECTED_FAILURE"),
)


def _request() -> ImageRequest:
    return ImageRequest(
        "cover.png", "a" * 64, "b" * 64, "mock", 7, 1, 32, 16, "PNG", 1, "tx", "call"
    )


def _zip_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("image_manifest.json", b"{}")
    return output.getvalue()


@pytest.mark.parametrize("boundary", BOUNDARIES, ids=lambda item: item.name)
def test_m6_fresh_process_boundary_is_fail_closed_and_idempotent(
    tmp_path: Path, boundary: Boundary
) -> None:
    """Exercise one independently injected M6 seam through two fresh recovery passes."""
    kernel = WorkflowKernel(tmp_path)
    workflow = kernel.create_workflow("YOUTH_SAFE", "STAGE1", "CREATE", PROMPT, "c" * 64)
    kernel.transition_workflow(workflow, WorkflowStatus.RUNNING)
    stage = kernel.start_stage(workflow, "STAGE1", "d" * 64)
    transaction = kernel.get_or_create_transaction(stage, "LANDSCAPE", "cover.png")
    call: str | None = None
    artifact: str | None = None
    package: str | None = None
    response = DeterministicMockImageAdapter().generate_image(
        _request(), __import__("threading").Event()
    )

    if boundary.phase >= 1:
        call = kernel.begin_generation_call(transaction, "e" * 64)
    if boundary.phase in {2, 3, 9}:
        payload = render_cover("TEST") if boundary.phase == 9 else response.content
        if boundary.phase == 3:
            validate_image_qa(payload, "cover.png", expected_dimensions=(32, 16))
        if boundary.phase == 9:
            validate_cover(payload)
        kernel.store.put(payload)
    if boundary.phase >= 4:
        assert call is not None
        artifact = kernel.register_candidate(
            call,
            response.content,
            "image/png",
            "STAGE1",
            artifact_role="STAGE1_MANIFEST",
            dependency_digest="f" * 64,
        )
    if boundary.phase >= 5:
        assert call is not None and artifact is not None
        digest = kernel.db.connection.execute(
            "SELECT sha256 FROM artifacts WHERE id=?", (artifact,)
        ).fetchone()[0]
        kernel.store.register_image_candidate(
            digest,
            owner_stage="STAGE1",
            transaction_id=transaction,
            generation_call_id=call,
            delivery_status="AUTHORITATIVE",
            provenance_digest="1" * 64,
            evidence_digest="2" * 64,
            gate_status="PASS" if boundary.phase >= 6 else "NOT_VERIFIED",
        )
    if boundary.phase >= 6:
        assert artifact is not None
        kernel.record_gate(
            stage,
            artifact,
            "IMAGE_QA_GATE",
            DetectorClass.DETERMINISTIC,
            GateStatus.PASS,
            {"boundary": boundary.name},
            PROMPT,
            "d" * 64,
            "M6-test",
            "f" * 64,
        )
    if boundary.phase >= 7:
        assert artifact is not None
        digest = kernel.db.connection.execute(
            "SELECT sha256 FROM artifacts WHERE id=?", (artifact,)
        ).fetchone()[0]
        kernel.store.bind_authoritative_artifact(digest)
    if boundary.phase >= 11:
        assert call is not None and artifact is not None
        kernel.record_cross_file_result(
            transaction,
            call,
            artifact,
            status="PASS",
            error_code=None,
            dependency_digest="3" * 64,
            evidence_digest="4" * 64,
        )
    if boundary.phase >= 13:
        assert call is not None
        package = kernel.create_image_package(
            transaction,
            call,
            authority_set_digest="5" * 64,
            manifest_digest="6" * 64,
            dependency_digest="7" * 64,
            evidence_digest="8" * 64,
        )
    package_bytes = _zip_bytes()
    if boundary.phase >= 14:
        kernel.store.put(b"{}")
    if boundary.phase >= 15:
        assert call is not None
        package_artifact = kernel.register_candidate(
            call,
            package_bytes,
            "application/zip",
            "STAGE1",
            artifact_role="STAGE1_MANIFEST",
        )
        assert package is not None
        kernel.pass_image_package(package, package_artifact, sha256_bytes(package_bytes))
    if boundary.phase == 16:
        assert package is not None
        with pytest.raises(KernelError, match="AFTER_RENAME") as injected:
            publish_package(
                kernel,
                package,
                package_bytes,
                "published/matrix.zip",
                fault=PublicationFault.AFTER_RENAME,
            )
        assert injected.value.code == boundary.stable_code

    before = {
        "transactions": kernel.db.connection.execute(
            "SELECT COUNT(*) FROM asset_transactions"
        ).fetchone()[0],
        "calls": kernel.db.connection.execute("SELECT COUNT(*) FROM generation_calls").fetchone()[
            0
        ],
        "artifacts": kernel.db.connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
        "bindings": kernel.db.connection.execute(
            "SELECT COUNT(*) FROM artifact_bindings"
        ).fetchone()[0],
        "events": kernel.db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
    }
    kernel.close()

    first = WorkflowKernel(tmp_path)
    if boundary.phase == 16:
        assert package is not None
        assert recover_package_publication(first, package) == "PUBLISHED"
    else:
        first_decisions = recover(first, workflow)
        assert boundary.stable_code in {decision.code.value for decision in first_decisions}
    first.close()

    second = WorkflowKernel(tmp_path)
    if boundary.phase == 16:
        assert package is not None
        assert recover_package_publication(second, package) == "PUBLISHED"
    else:
        second_decisions = recover(second, workflow)
        assert len(second_decisions) >= 1

    after = {
        "transactions": second.db.connection.execute(
            "SELECT COUNT(*) FROM asset_transactions"
        ).fetchone()[0],
        "calls": second.db.connection.execute("SELECT COUNT(*) FROM generation_calls").fetchone()[
            0
        ],
        "artifacts": second.db.connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
        "bindings": second.db.connection.execute(
            "SELECT COUNT(*) FROM artifact_bindings"
        ).fetchone()[0],
    }
    assert after == {key: value for key, value in before.items() if key != "events"}
    assert second.progress(stage)[0] == 0
    assert (
        second.db.connection.execute(
            "SELECT COUNT(*) FROM artifact_bindings GROUP BY transaction_id,role HAVING COUNT(*)>1"
        ).fetchall()
        == []
    )
    if artifact is not None:
        row = second.db.connection.execute(
            "SELECT sha256,byte_size,relative_path FROM artifacts WHERE id=?", (artifact,)
        ).fetchone()
        data = (tmp_path / row["relative_path"]).read_bytes()
        assert len(data) == row["byte_size"]
        assert sha256_bytes(data) == row["sha256"]
    if artifact is not None and boundary.phase >= 5:
        authority = second.db.connection.execute(
            "SELECT owner_stage,transaction_id,generation_call_id,gate_status,immutable,"
            "quarantine_code FROM image_artifact_authority WHERE artifact_sha256=?",
            (row["sha256"],),
        ).fetchone()
        assert authority["owner_stage"] == "STAGE1"
        assert authority["transaction_id"] == transaction
        assert authority["generation_call_id"] == call
        assert authority["gate_status"] == ("PASS" if boundary.phase >= 6 else "NOT_VERIFIED")
        assert authority["immutable"] == (1 if boundary.phase >= 7 else 0)
        assert authority["quarantine_code"] is None
    if call is not None and boundary.phase != 16:
        row = second.db.connection.execute(
            "SELECT transaction_id,status FROM generation_calls WHERE id=?", (call,)
        ).fetchone()
        assert row["transaction_id"] == transaction
        assert row["status"] in {CallStatus.TIMED_OUT, CallStatus.FINISHED}
    if package is not None:
        rows = second.db.connection.execute(
            "SELECT status,zip_digest,zip_size FROM image_packages WHERE id=?", (package,)
        ).fetchall()
        assert len(rows) == 1
        if boundary.phase == 16:
            assert rows[0]["status"] == "PUBLISHED"
            assert rows[0]["zip_digest"] == sha256_bytes(package_bytes)
            assert rows[0]["zip_size"] == len(package_bytes)
            assert (
                second.db.connection.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type='IMAGE_PACKAGE_PUBLISHED'"
                ).fetchone()[0]
                == 1
            )
    event_count = second.db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert event_count == before["events"] + (1 if boundary.phase == 16 else 4)
    second.close()
