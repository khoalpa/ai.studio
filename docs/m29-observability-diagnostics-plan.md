# M29 — Production Observability & Diagnostics

The Studio exposes `GET /api/v1/diagnostics` with SQLite integrity, WAL mode, job
counts, Python/platform identity, local dependency availability, model availability,
and disk capacity. The activity view presents a compact operator-facing summary.
All diagnostics are local read-only observations.

