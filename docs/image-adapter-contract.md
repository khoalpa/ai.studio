# M6 Image Adapter Contract

M6 exposes a versioned `LocalImageAdapter` with `generate_image`, `health`, `capabilities`,
`cancel` and `unload`. `ImageRequest` binds one basename, one canvas, one response, seed,
prompt/workflow digests, model identity, transaction and generation-call IDs. Requests with an
output count other than one or an invalid canvas are rejected before backend execution.

`DeterministicMockImageAdapter` is offline and test-only. `ComfyUIImageAdapter` accepts only an
explicit loopback endpoint and rejects redirects; it never downloads models/workflows or falls
back to a cloud service. The image transaction service validates exact PNG bytes before registering
a candidate in the M3 artifact store and committing it behind a deterministic PASS gate.

Stable image failures include `IMG001_SINGLE_RESPONSE_REQUIRED`, `IMG002_INVALID_CANVAS`,
`IMG004_CANCELLED`, `IMG006_REDIRECT_REJECTED`, `IMG007_BACKEND_FAILURE`,
`IMG008_TIMEOUT_OR_BACKEND`, `IMG009_EMPTY_OUTPUT`, `IMG010_OUTPUT_CARDINALITY` and
`IMG011_TRUNCATED_OUTPUT`. `IMG012_OOM` identifies resource-acquisition failure.
Retries retain the logical transaction ID and replace the request's generation
call ID with the newly persisted call ID. OOM and cancellation close the call,
do not bind or advance progress, and the GPU semaphore is released even when
backend unload fails. Package publication cancellation is
`RK040_PACKAGE_PUBLICATION_CANCELLED`; cancellation after atomic rename leaves
an exact-byte recoverable `PASS` package rather than promoting it implicitly.

The deterministic typography fixture rejects overflow (`TYPO001_TEXT_LAYOUT`),
missing fixture identity (`TYPO002_FIXTURE_MISSING`), renderer failure
(`TYPO003_RENDERER_FAILURE`), reopen mismatch (`TYPO004_REOPEN_MISMATCH`) and
stale base-image evidence (`TYPO005_STALE_BASE_IMAGE`).

M6 image-authority store failures use their own non-overlapping range:
`RK041_ARTIFACT_MISSING`, `RK042_ARTIFACT_DIGEST_MISMATCH`,
`RK043_OWNERSHIP_MISMATCH`, `RK044_PROVENANCE_MISSING`,
`RK045_GATE_NOT_PASS`, `RK046_NOT_AUTHORITATIVE`,
`RK047_METADATA_STORE_REQUIRED` and `RK048_METADATA_MISSING`. This avoids
reusing the numeric identities assigned to M3 kernel failures.
`RK049_CALL_TRANSACTION_MISMATCH` covers an M6 package/cross-file call whose
persisted transaction differs from the requested transaction; the existing M3
`RK019_ARTIFACT_TRANSACTION_MISMATCH` remains unchanged.
