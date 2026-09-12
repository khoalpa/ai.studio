CREATE TABLE package_orphan_inventory (
  id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE CHECK(length(idempotency_key) = 64),
  relative_path TEXT NOT NULL,
  file_kind TEXT NOT NULL CHECK(file_kind IN ('TEMP','CANONICAL')),
  observed_digest TEXT NOT NULL CHECK(length(observed_digest) = 64),
  observed_size INTEGER NOT NULL,
  expected_package_id TEXT REFERENCES image_packages(id),
  expected_transaction_id TEXT REFERENCES asset_transactions(id),
  expected_generation_call_id TEXT REFERENCES generation_calls(id),
  classification TEXT NOT NULL CHECK(classification IN ('OWNED_RECOVERABLE','ORPHANED','MISMATCH','QUARANTINED','RECONCILED')),
  reason_code TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
