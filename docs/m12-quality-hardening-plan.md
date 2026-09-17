# M12 Quality Hardening Plan

## Scope

M12 closes test blind spots identified by the final M11 audit. It adds direct
coverage for Stage 2 checkpoint publication, offline story-quality evidence and
the pinned FFmpeg process boundary. It does not change schemas, canonical prompt
bytes, package layouts, production policies or external dependencies.

## Definition of Done

- No production module remains at zero coverage.
- Stage 2 checkpoint publication is exercised end-to-end after aggregate gates.
- Story-quality evidence accepts only digest-bound threshold PASS results.
- FFmpeg tests cover dependency integrity, success, cancellation, timeout,
  malformed probe output, output limits, non-zero exit and execution failure.
- Ruff format/lint, strict mypy, pytest, `git diff --check` and canonical digest
  gates pass.
