# M17 — Local Semantic Review Bridge

## Outcome

Stage 2 production assets can be reviewed through the local Studio UI and can only be
packaged after all ten exact committed PNGs receive current PASS assessments.

## Contract

- `GET /api/v1/jobs/{job_id}/semantic-review` returns the ten committed basenames and
  their server-owned SHA-256 digests.
- `POST /api/v1/jobs/{job_id}/semantic-review` accepts exactly ten unique PASS/FAIL
  decisions with non-empty observable findings.
- The runtime constructs evidence digests from the committed image SHA-256, basename,
  method, findings, and status. A browser-supplied digest is never trusted.
- Aggregate Stage 2 gates are re-evaluated against bytes reopened from the artifact
  store. Packaging remains blocked unless all ten semantic gates pass.
- Queued and running Studio jobs support cooperative cancellation. Image adapters
  receive the same cancellation token and local backends are asked to cancel the
  active generation call.

## Offline boundary

The bridge has no network or cloud fallback. `HUMAN_REVIEW` is the production-safe
fallback while a local VLM is unavailable. A future local VLM adapter must submit the
same assessment contract and must consume exact PNG bytes.

