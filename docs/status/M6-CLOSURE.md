# M6 Closure Audit

Status: PASS.

## Scope decision

The implementation plan separates M6 into M6-A deterministic closure and M6-B
environment validation. M6-A was committed at `cedd1ef`; M6-B subsequently
validated the local OCR adapter, ComfyUI runtime and production typography path.
The combined production smoke is the final M6 acceptance item. M7 has not been
started.

`PCF001_STAGE4_AUDIO_MODE_DEFAULT_COLLISION` is not an M6 blocker. It reports a
real conflict between the Stage 4 canonical `NATIVE_DIALOGUE` default and the
Stage 4 projection registry's `AMBIENCE_ONLY` mapping for an absent value. The
canonical prompt is byte-for-byte frozen during M0-M8, and existing tests must
continue reporting this finding without selecting a value. Resolution therefore
belongs to the Stage 4/release decision path and requires an authorized canonical
revision; suppressing or silently choosing a default in M6 is forbidden.

## Definition of Done evidence

- Deterministic image transaction, single-response enforcement, current PASS
  gates, immutable binding and progress derivation: PASS.
- PNG signature, CRC, decode, dimensions, ratio, alpha policy, luma, metadata
  and exact digest validation: PASS.
- Authority, stale-evidence rejection, quarantine, deterministic package build,
  safe extraction and publication recovery: PASS.
- Seventeen fresh-process recovery boundaries and filesystem/SQLite fault
  matrix: PASS.
- One system-wide GPU-heavy job, retry/cancellation/OOM/unload behavior and
  loopback-only ComfyUI transport: PASS.
- Pinned workflow, checkpoint, font, Tesseract executable and Vietnamese model
  provenance/digests: PASS.
- Combined ComfyUI to zero-text OCR to typography to exact Vietnamese OCR to
  transaction commit smoke: PASS.
- Canonical prompt integrity and read-only policy: PASS.
- No cloud fallback, credentials, automatic downloads or custom-node dependency:
  PASS.

## Final production evidence

The combined transaction committed a 1024x1024 cover with SHA-256
`9413e28d7be6a2919601f1b30b73f116709bb0897e5ffa7985417b6c3dc88778`.
Base OCR confidence was `0.36375960153846154`, below the residual-text threshold
`0.8`. Final OCR returned exactly `Chuyện kể đêm nay` with confidence
`0.9636167525`. `IMAGE_QA_GATE`, `TYPOGRAPHY_GATE` and `OCR_GATE` were current
PASS records before the transaction committed and progress reached `1/1`.

The final offline regression suite reports 300 passed, 2 optional smoke skips
and 92.64% branch coverage. Ruff format/lint, mypy strict, canonical SHA-256 and
`git diff --check` pass. The explicit production smoke and dependency evidence
are recorded in `docs/status/M6-B-PRODUCTION-SMOKE.md` and the component M6-B
status files.

## Release checkpoint

M6 is eligible to close. `PCF001` remains visible and unchanged as an inherited
Stage 4/release finding. Beginning M7 requires a separate instruction and must
not mutate the canonical prompt to resolve `PCF001` without an authorized
canonical-version decision.
