CREATE TABLE studio_stage2_runs (
  job_id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL UNIQUE REFERENCES workflow_runs(id),
  stage_run_id TEXT NOT NULL UNIQUE REFERENCES stage_runs(id),
  source_package_path TEXT NOT NULL,
  source_package_sha256 TEXT NOT NULL CHECK(length(source_package_sha256) = 64),
  execution_mode TEXT NOT NULL CHECK(execution_mode IN ('MOCK','COMFYUI')),
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE studio_semantic_assessments (
  stage_run_id TEXT NOT NULL REFERENCES stage_runs(id),
  basename TEXT NOT NULL,
  image_sha256 TEXT NOT NULL CHECK(length(image_sha256) = 64),
  status TEXT NOT NULL CHECK(status IN ('PASS','FAIL')),
  method TEXT NOT NULL CHECK(method IN ('HUMAN_REVIEW','QWEN2_5_VL_LOCAL')),
  observable_findings_json TEXT NOT NULL,
  evidence_digest_sha256 TEXT NOT NULL CHECK(length(evidence_digest_sha256) = 64),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(stage_run_id, basename)
);

