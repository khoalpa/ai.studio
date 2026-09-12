CREATE TABLE image_artifact_authority (
  artifact_sha256 TEXT PRIMARY KEY CHECK(length(artifact_sha256) = 64),
  owner_stage TEXT NOT NULL,
  transaction_id TEXT NOT NULL REFERENCES asset_transactions(id),
  generation_call_id TEXT NOT NULL REFERENCES generation_calls(id),
  delivery_status TEXT NOT NULL,
  provenance_digest TEXT NOT NULL CHECK(length(provenance_digest) = 64),
  evidence_digest TEXT NOT NULL CHECK(length(evidence_digest) = 64),
  gate_status TEXT NOT NULL,
  immutable INTEGER NOT NULL DEFAULT 0,
  quarantine_code TEXT,
  updated_at TEXT NOT NULL
);
