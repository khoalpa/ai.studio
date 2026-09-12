CREATE TABLE cross_file_gate_results (
  id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE CHECK(length(idempotency_key) = 64),
  workflow_id TEXT NOT NULL REFERENCES workflow_runs(id),
  stage_run_id TEXT NOT NULL REFERENCES stage_runs(id),
  transaction_id TEXT NOT NULL REFERENCES asset_transactions(id),
  generation_call_id TEXT NOT NULL REFERENCES generation_calls(id),
  artifact_id TEXT NOT NULL REFERENCES artifacts(id),
  package_identity TEXT,
  status TEXT NOT NULL CHECK(status IN ('PASS','REJECTED','STALE','QUARANTINED')),
  error_code TEXT,
  dependency_digest TEXT NOT NULL CHECK(length(dependency_digest) = 64),
  evidence_digest TEXT NOT NULL CHECK(length(evidence_digest) = 64),
  created_at TEXT NOT NULL
);
