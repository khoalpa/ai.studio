# SQLite Migrations

Migration `001_workflow_kernel.sql` creates:

- `workflow_runs`
- `stage_runs`
- `asset_transactions`
- `generation_calls`
- `artifacts`
- `artifact_bindings`
- `gate_results`
- `events`
- `workspace_leases`

The migration runner creates `schema_migrations(version, checksum, applied_at)` before applying numbered scripts. Each script is UTF-8, applied once and recorded with SHA-256. Reopening an already migrated database is idempotent; changing bytes of an applied migration raises `RK002_MIGRATION_CHECKSUM_MISMATCH`.

Migration `002_llm_call_metadata.sql` adds `model_identity`, `adapter_version`, `duration_ms` and `termination_reason` to `generation_calls`. These fields preserve M4 execution provenance without persisting prompt or response bodies.

Connections enable `foreign_keys`, WAL and a configurable busy timeout. Application transactions use `BEGIN IMMEDIATE` by default. Business transitions remain in Python rather than triggers. Backup/restore packaging is deferred to M11; until then, a consistent manual backup must include the database plus WAL/SHM state or be taken after closing the kernel.
