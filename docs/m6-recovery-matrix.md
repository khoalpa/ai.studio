# M6 Fresh-Process Recovery Matrix

Each row is an independent parameterized test case in
`tests/integration/test_m6_recovery_boundaries.py`. The harness injects by
stopping at exactly one seam, closes the original kernel, opens a fresh SQLite
connection/store/kernel, recovers, closes it, and repeats recovery with another
fresh instance. Counts for transactions, calls, artifacts and bindings must not
increase during either recovery pass; exact persisted artifact bytes are
reopened and checked against digest and size.

| # | Boundary | Expected pre-recovery state | Recovery action | Stable evidence |
|---:|---|---|---|---|
| 1 | Before image request | `PENDING`, no call | No promotion | `RK_CLEAN` |
| 2 | After image request | call `RUNNING` | Timeout call; retryable transaction | `RK_CALL_INTERRUPTED` |
| 3 | Response before PNG QA | response is unbound store object | Preserve orphan; timeout call | `RK_STORE_ORPHAN_FOUND` |
| 4 | PNG QA before candidate | verified bytes remain unbound | Preserve orphan; timeout call | `RK_STORE_ORPHAN_FOUND` |
| 5 | Candidate before authority | mutable candidate, no authority | Block commit; make retryable | `RK_TRANSACTION_INTERRUPTED` |
| 6 | Authority before gate | authority is `NOT_VERIFIED` | Block binding/progress | `RK_TRANSACTION_INTERRUPTED` |
| 7 | Gate before binding | current PASS, no committed binding | No implicit bind; make retryable | `RK_TRANSACTION_INTERRUPTED` |
| 8 | Authority bind before transaction commit | immutable authority, no M3 binding | No implicit commit/progress | `RK_TRANSACTION_INTERRUPTED` |
| 9 | Before typography | call/candidate in progress | Timeout and retry | `RK_CALL_INTERRUPTED` |
| 10 | After typography | cover bytes unbound | Preserve orphan and retry | `RK_STORE_ORPHAN_FOUND` |
| 11 | Before OCR evidence | call/candidate in progress | Timeout and retry | `RK_CALL_INTERRUPTED` |
| 12 | OCR before cross-file validation | persisted PASS evidence only | No implicit publication | `RK_TRANSACTION_INTERRUPTED` |
| 13 | After cross-file validation | persisted PASS result, no package | No implicit package/binding | `RK_TRANSACTION_INTERRUPTED` |
| 14 | After authority-set freeze | package `CANDIDATE` | Retain candidate, no publication | `RK_TRANSACTION_INTERRUPTED` |
| 15 | After manifest creation | package `CANDIDATE`, manifest bytes stored | Preserve exact bytes | `RK_TRANSACTION_INTERRUPTED` |
| 16 | After ZIP creation | package `PASS`, no canonical ZIP | Retain PASS, no publication | `RK_TRANSACTION_INTERRUPTED` |
| 17 | Package PASS after canonical rename | exact canonical ZIP, SQLite `PASS` | Verify and finish publication once | `RK900_INJECTED_FAILURE` |

The matrix deliberately treats non-persisted response/QA/typography bytes as
orphans. It does not reconstruct or promote them from process memory. Package
publication recovery is the only row allowed to complete automatically, and
only because path, digest, size and lifecycle authority are already persisted.
