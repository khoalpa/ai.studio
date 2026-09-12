CREATE TABLE image_packages (
  id TEXT PRIMARY KEY,
  package_transaction_id TEXT NOT NULL REFERENCES asset_transactions(id),
  generation_call_id TEXT NOT NULL REFERENCES generation_calls(id),
  artifact_id TEXT REFERENCES artifacts(id),
  authority_set_digest TEXT NOT NULL CHECK(length(authority_set_digest) = 64),
  manifest_digest TEXT NOT NULL CHECK(length(manifest_digest) = 64),
  zip_digest TEXT CHECK(zip_digest IS NULL OR length(zip_digest) = 64),
  dependency_digest TEXT NOT NULL CHECK(length(dependency_digest) = 64),
  evidence_digest TEXT NOT NULL CHECK(length(evidence_digest) = 64),
  status TEXT NOT NULL CHECK(status IN ('CANDIDATE','PASS','PUBLISHED','STALE','QUARANTINED','SUPERSEDED')),
  supersedes_id TEXT REFERENCES image_packages(id),
  superseded_by_id TEXT REFERENCES image_packages(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(package_transaction_id),
  UNIQUE(generation_call_id)
);

CREATE INDEX image_packages_authority_idx ON image_packages(authority_set_digest, status);
