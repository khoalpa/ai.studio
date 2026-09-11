# Local LLM Adapter

M4 exposes `LocalLLMAdapter` with `generate_structured`, `generate_text`, `assess_semantic`, `health` and `unload`. The deterministic mock is the default test backend. `LlamaCppAdapter` supports either loopback HTTP or an explicitly configured local subprocess; it has no cloud transport, credential field, download path or fallback.

`StructuredGenerationService` binds an M1 capsule digest into the request digest, opens one M3 generation call per attempt, writes the exact response as a candidate, and applies M2 strict JSON, field-order and versioned schema validation. Only an `IMPLEMENTED` deterministic schema result records a PASS gate and reaches M3 commit. Parse, schema, backend, timeout, cancellation and `NOT_VERIFIED` outcomes never publish or increase progress.

Requests and events retain digests and operational metadata, not prompt or response bodies. The generation-call row records request/response digest, model identity, adapter version, duration and termination reason. Retry reuses the logical transaction while M3 creates a new call ID, preserving `RK018` and `RK019` lineage.

## Stable errors

| Code | Meaning |
| --- | --- |
| `LLM001_NON_LOOPBACK_ENDPOINT` | Endpoint is not HTTP loopback |
| `LLM002_CONTEXT_BUDGET` | Capsule plus instruction exceeds the configured context |
| `LLM003_TIMEOUT` | Local backend exceeded its deadline |
| `LLM004_CANCELLED` | Caller cancelled the request |
| `LLM005_RETRY_EXHAUSTED` | All bounded attempts failed |
| `LLM006_BACKEND_FAILURE` | Local HTTP/process backend failed |
| `LLM007_NON_ZERO_EXIT` | Local process returned a non-zero code |
| `LLM008_TRUNCATED_OUTPUT` | Backend returned empty or length-truncated output |
| `LLM009_VALIDATION_FAILED` | M2 strict/schema validation rejected output |
| `LLM010_VALIDATION_NOT_VERIFIED` | Registered schema is not deterministically implemented |
| `LLM011_SEMANTIC_RESPONSE` | Semantic response envelope is malformed |
| `LLM012_BINDING_MISMATCH` | Stage, capsule or canonical lineage does not match M3 state |
| `LLM013_TOKEN_BUDGET` | Requested output budget is invalid or too large |
| `LLM014_EXECUTION_FAILURE` | Unexpected local execution/store failure was contained |

The adapter never reports deterministic PASS itself. Semantic assessment is a separate typed result and cannot substitute for the M2 gate.
