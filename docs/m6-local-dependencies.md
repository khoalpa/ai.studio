# M6 Local Dependency and Evidence Checklist

This checklist records the local prerequisites required to close M6. It does
not install, download, or enable any backend. Missing production dependencies
remain `NOT_VERIFIED` and are never substituted by the deterministic mocks.

## Layer 1 — deterministic M6 closure

These items can be implemented and evidenced with local fixtures and fault
injection, without a production model or network service:

- [x] Fresh-process recovery seams cover all 17 boundaries.
- [x] Fault-injection matrix covers adapter, OCR, typography, policy,
      filesystem, package and SQLite failures.
- [x] Deterministic typography/cover fixture, zero-text gate and provenance
      chain are complete.
- [x] Package quarantine, fan-out/contact-sheet checks and cross-file digest,
      manifest and safe-extraction gates are complete.
- [x] Every rejected candidate is quarantined and cannot bind, publish or
      advance progress.

Evidence for this layer must use fresh instances, deterministic fixtures and
exact state/event/artifact assertions. It must not claim production backend
quality.

## Layer 2 — environment validation

These items require explicitly provisioned local dependencies. Until then they
remain `NOT_VERIFIED` and must be reported as such.

### ComfyUI loopback

- [ ] ComfyUI version and local install path recorded.
- [ ] Server binds only to `127.0.0.1` on an explicit configured port.
- [ ] Workflow JSON, model/checkpoint and custom-node versions are present
      locally; record SHA-256 digests.
- [ ] Health and capability/model probes pass.
- [ ] Workflow digest, request digest, seed, canvas and single-output
      cardinality are captured.
- [ ] Timeout, cancellation, redirect rejection, malformed/truncated/empty/
      fan-out output, crash/non-zero exit, semaphore and unload tests pass.
- [ ] Output is reopened and its exact PNG digest is recorded.

Evidence must be produced by an explicitly marked smoke test. No model,
workflow or custom node may be downloaded by the test.

## Local OCR

- [ ] Engine and model are installed locally with pinned versions and digests.
- [ ] Adapter records image digest, engine/model identity, adapter version,
      region, NFC-normalized text, confidence, bounding box/locator, evidence
      digest, timing and termination reason.
- [ ] Tests cover correct/incorrect text, Vietnamese diacritics,
      normalization, low confidence, out-of-bounds boxes, zero-text residuals,
      timeout, cancellation, crash and image-digest mismatch.
- [ ] OCR never mutates authoritative pixels or bypasses PNG QA gates.

## Typography and cover renderer

- [ ] Deterministic renderer and pinned font identity are available locally.
- [ ] Zero-text base gate passes before rendering.
- [ ] Text, language, episode label, layout and safe-margin gates pass.
- [ ] Final PNG is reopened and dimensions, alpha, luma, OCR, metadata and
      digest gates are rerun.
- [ ] Provenance binds base digest, renderer/font identity, text input and
      final digest.
- [ ] Same input/seed/configuration produces identical bytes.

## Recovery and fault evidence

- [ ] Fresh-process evidence exists for all 17 M6 boundaries.
- [ ] Every case reconciles SQLite and filesystem, is idempotent on the second
      recovery, preserves RK018/RK019, and rejects stale candidates.
- [ ] Fault injection covers OOM, unload, cancellation, OCR, typography,
      policy, metadata/PNG/manifest/package writes, SQLite binding,
      publication, disk quota and unexpected adapter/store failures.

## Package quarantine and cross-file packaging

- [ ] Fan-out, contact-sheet, canvas/orientation, duplicate-basename,
      missing/extra output and path/owner/source checks are covered.
- [ ] Digest, byte-size, manifest, stale-evidence and relationship checks are
      enforced across story/character/image files.
- [ ] Reopen, safe extraction and archive-security corpus pass.
- [ ] Quarantined candidates cannot bind, publish, overwrite or advance
      progress.

## Release evidence

Record the exact command, result and status (`PASS`, `SKIP`, or
`NOT_VERIFIED`) for each item. The default suite must remain offline and GPU
free. M6 remains uncommitted until all required production evidence is
reviewed; M7 is out of scope and `PCF001` remains unresolved.
