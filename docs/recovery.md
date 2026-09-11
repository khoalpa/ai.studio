# Recovery and Resume

Recovery opens the existing SQLite database and artifact store from a new application instance, appends `RESUME_STARTED`, classifies inconsistencies, applies deterministic state changes in one database transaction, and appends `RESUME_COMPLETED` with decision codes.

| Recovery code | Classification and action |
| --- | --- |
| `RK_CLEAN` | No recovery action required |
| `RK_TEMP_ORPHAN_QUARANTINED` | Temporary file retained for delayed cleanup |
| `RK_STORE_ORPHAN_FOUND` | Published store bytes lack DB metadata; preserve unbound |
| `RK_DB_FILE_MISSING` | DB-bound file missing; block transaction and stale gates |
| `RK_DIGEST_MISMATCH` | DB-bound file digest differs; block transaction and stale gates |
| `RK_CALL_INTERRUPTED` | Running call becomes timed out, never PASS |
| `RK_TRANSACTION_INTERRUPTED` | In-progress transaction becomes retryable with same ID |
| `RK_STALE_GATE` | Dependency or artifact evidence is no longer current |

A crash before temporary write leaves no state. A crash after temporary write leaves a delayed-cleanup orphan. A crash after atomic rename or an injected DB failure leaves an unbound content-addressed object. SQLite rollback leaves no partial metadata. Recovery never creates a replacement logical transaction and never increases progress.

The event log is append-only through the public API. Sequence allocation occurs inside `BEGIN IMMEDIATE`, with a unique `(workflow_id, sequence_no)` constraint. Canonical JSON payload bytes and payload SHA-256 are stored together.

Workspace leases use owner identity and UTC expiry. `BEGIN IMMEDIATE`, busy timeout and the lease row coordinate normal operation; unique database constraints remain the final cross-process guard. A stale lease may be taken over deterministically.
