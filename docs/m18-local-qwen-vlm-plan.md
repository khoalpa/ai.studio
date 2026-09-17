# M18 — Local Qwen2.5-VL Semantic Assessor

## Outcome

The Studio can queue Qwen2.5-VL semantic review of all ten committed Stage 2 PNGs,
persist exact-byte evidence in SQLite, and recover review state after process restart.

## Runtime contract

- Reuse `scripts/run_m7_semantic_assessor.py` with the configured local model only.
- Force Hugging Face, Transformers, and datasets offline environment flags.
- Serialize each committed artifact to an isolated temporary directory and verify the
  returned `image_sha256` against bytes read from the artifact store.
- Accept only strict PASS/FAIL JSON with non-empty observable findings and a 64-byte
  hexadecimal evidence digest.
- Run VLM work through the existing single worker and cooperative cancellation token.
- Keep manual review as the fail-closed fallback; never synthesize a PASS.

## Persistence

Migration 009 adds Studio Stage 2 run metadata and current semantic assessments.
Assessment identity is `(stage_run_id, basename)` and includes the image digest,
method, findings, evidence digest, and timestamps. Interrupted jobs restore to
`WAITING_SEMANTIC_REVIEW`.

