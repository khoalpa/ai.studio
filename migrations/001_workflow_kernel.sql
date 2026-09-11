PRAGMA foreign_keys = ON;

CREATE TABLE workflow_runs (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  profile TEXT NOT NULL,
  requested_stage TEXT NOT NULL,
  route TEXT NOT NULL,
  status TEXT NOT NULL,
  canonical_prompt_sha256 TEXT NOT NULL CHECK(length(canonical_prompt_sha256) = 64),
  config_digest TEXT NOT NULL
);

CREATE TABLE stage_runs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflow_runs(id),
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  capsule_digest TEXT NOT NULL CHECK(length(capsule_digest) = 64),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(workflow_id, stage)
);

CREATE TABLE asset_transactions (
  id TEXT PRIMARY KEY,
  stage_run_id TEXT NOT NULL REFERENCES stage_runs(id),
  orientation TEXT NOT NULL,
  basename TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(stage_run_id, orientation, basename)
);

CREATE TABLE generation_calls (
  id TEXT PRIMARY KEY,
  transaction_id TEXT NOT NULL REFERENCES asset_transactions(id),
  attempt_index INTEGER NOT NULL,
  request_digest TEXT NOT NULL,
  response_digest TEXT,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  failure_code TEXT,
  candidate_artifact_id TEXT,
  UNIQUE(transaction_id, attempt_index)
);

CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL UNIQUE,
  relative_path TEXT NOT NULL UNIQUE,
  byte_size INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  artifact_role TEXT NOT NULL,
  owner_stage TEXT NOT NULL,
  status TEXT NOT NULL,
  mutation_status TEXT NOT NULL,
  dependency_digest TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE artifact_bindings (
  id TEXT PRIMARY KEY,
  transaction_id TEXT NOT NULL REFERENCES asset_transactions(id),
  artifact_id TEXT NOT NULL REFERENCES artifacts(id),
  role TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(transaction_id, role),
  UNIQUE(transaction_id, artifact_id)
);

CREATE TABLE gate_results (
  id TEXT PRIMARY KEY,
  stage_run_id TEXT NOT NULL REFERENCES stage_runs(id),
  artifact_id TEXT NOT NULL REFERENCES artifacts(id),
  gate_id TEXT NOT NULL,
  detector_class TEXT NOT NULL,
  status TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  evidence_digest TEXT NOT NULL,
  canonical_prompt_sha256 TEXT NOT NULL,
  capsule_digest TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  dependency_digest TEXT,
  is_current INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE events (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflow_runs(id),
  stage_run_id TEXT REFERENCES stage_runs(id),
  sequence_no INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_digest TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(workflow_id, sequence_no)
);

CREATE TABLE workspace_leases (
  workspace_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
