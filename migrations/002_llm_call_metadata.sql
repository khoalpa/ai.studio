ALTER TABLE generation_calls ADD COLUMN model_identity TEXT;
ALTER TABLE generation_calls ADD COLUMN adapter_version TEXT;
ALTER TABLE generation_calls ADD COLUMN duration_ms INTEGER;
ALTER TABLE generation_calls ADD COLUMN termination_reason TEXT;
