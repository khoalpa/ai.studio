# M6 Image Recovery

Image authority metadata is persisted by versioned migration 003 in the same
SQLite database used by the M3 kernel. Ownership, generation-call provenance,
current gate, immutable binding and quarantine state therefore survive a new
kernel/store instance; no process-memory fallback is used.

Migration 004 persists cross-file gate outcomes with a deterministic
idempotency key. Replaying the same stale/reject result produces neither a
duplicate result nor a duplicate event. Current gates are invalidated rather
than deleted, preserving evidence history while preventing stale authority from
advancing progress after restart.

Migration 005 persists the package lifecycle independently of process memory.
Dependency invalidation moves current candidates, PASS records or published
packages to `STALE`, invalidates their current artifact gate, and retains the
old manifest/ZIP bytes. A replacement is a new package transaction and call;
only after its PASS-to-PUBLISHED transition is the old row linked as
`SUPERSEDED`.

Migration 007 binds the canonical publication path and byte size. Publication
uses a same-filesystem temporary file, flush/fsync/close, ZIP inspection and
safe extraction, atomic replace, and canonical digest reopen before the SQLite
transition/event transaction. Recovery may complete a `PASS` record after a
successful rename only from exact matching canonical bytes. A missing or
tampered `PUBLISHED` file is quarantined; repeated recovery does not duplicate
events.

Migration 008 records package-file observations as `OWNED_RECOVERABLE`,
`ORPHANED`, `MISMATCH`, `QUARANTINED`, or `RECONCILED`. Ownership is determined
from package lifecycle rows and exact path/digest/size, never from a filename.
Inventory is idempotent across fresh instances and intentionally leaves unknown
files untouched pending an explicit quarantine policy.

SQLite fault tests hold a competing `BEGIN IMMEDIATE` lock and inject failures
after lifecycle mutation, at supersession, and after event insertion. Because
lifecycle, supersession and event writes share one transaction, all injected
failures roll back to the previous package state with no partial event.

Concurrent publication recovery is terminal-state idempotent. If a second
kernel loses `PASS → PUBLISHED`, it rereads the row and accepts the exact
already-published state instead of reporting corruption. Connection
interruption immediately after rename is recovered by a new kernel only after
the persisted target, digest, size and ownership produce an
`OWNED_RECOVERABLE` inventory result.

Supersession recovery is an atomic SQLite operation performed only after the
successor is durably `PUBLISHED`. Two fresh kernels racing the same incomplete
link converge on one bidirectional predecessor/successor pair and one recovery
event. The losing kernel rereads and accepts the completed state, while the
predecessor is never partially linked and canonical package bytes are not
rewritten.

The 17-row recovery matrix is documented in `docs/m6-recovery-matrix.md`.
Each row is independently injected and uses two successive fresh kernels.
Recovery never reconstructs response, QA, OCR or typography evidence that was
not persisted before the injected stop. OOM and cancellation close generation
calls as failures, preserve retry lineage, release the GPU semaphore, and leave
binding/progress unchanged. A cancellation after atomic package rename is
handled as the same exact-byte recoverable gap as a process interruption.

Image work is one M3 transaction per basename. Retries retain the logical transaction and create a
new generation call. A candidate is stored and gated only after exact PNG reopen/QA; failures close
the call and leave no committed binding. The global semaphore is one GPU-heavy job, and adapter
`cancel`/`unload` are called by the owning application boundary. M3 recovery reconciles interrupted
calls, orphan files, digest mismatches and stale gates after a fresh process restart.
