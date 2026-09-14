# M8 Stage 3 Portrait Package Implementation Plan

## Purpose and boundary

M8 implements the Stage 3 portrait and final-package workflow from the
authoritative M7 Stage 2 checkpoint. It creates one 1080x1920 portrait for
each basename in the frozen active image set, preserves every Stage 1/2 member
that Stage 3 does not own, produces `package_quality_report.json` schema 2.0,
and publishes the verified Stage 3 `story.zip`.

M8 does not create `video_prompts.json` or execute video generation. It does
not modify canonical v3.16.13, download models, add cloud fallback, or resolve
the Stage 4-only `PCF001` finding.

## Authoritative input

- Input: `artifacts/m7-production-d26/story.zip`.
- Expected SHA-256:
  `47db5f8ae31364caafea37019d38f0aa8f7823936c3fc1bbac998f55e1ff4cd2`.
- The Stage 2 manifest, story, validation report, character references,
  `visual_plan.json`, `visual_bible.json`, ten landscapes and optional anchor
  are immutable parent inputs.
- Stage 3 must reject loose sidecars, alternate parent candidates, parent
  digest mismatch, malformed archives and any inherited-byte mutation.

## Fixed ZONE contract

- Portrait basenames match the exact ten-name Stage 2 ZONE order.
- Every output is one final-purpose 1080x1920 PNG, orientation `PORTRAIT`, with
  one logical transaction and one authoritative commit.
- `introduction.png` is the portrait pilot. Remaining assets execute only after
  its identity, crop, anatomy, luma and cross-orientation checks pass.
- Landscape assets are references and immutable package members; they are
  never regenerated, resized or rewritten during CREATE.

## Implementation slices

### M8-A intake and contracts

- Implement strict Stage 2 package intake and immutable parent bindings.
- Implement CURRENT `package_quality_report.json` schema 2.0, exact field
  order, deterministic serialization and measurement ledger bindings.
- Freeze the Stage 3 file set and owner/mutation map before any image call.

### M8-B portrait planning and firewall

- Derive basename-scoped portrait objectives from the validated visual plan,
  Visual Bible, landscape bytes and character references.
- Select and persist the portrait pilot using canonical risk weights.
- Enforce `STAGE3`, `PORTRAIT`, `FINAL_REQUIRED_ASSET`, output count one,
  1080x1920 dimensions, current basename only and no package-wide generator
  context.

### M8-C execution and repair

- Reuse the image transaction kernel and global one-GPU-job authority.
- Execute the pilot, then the remaining nine portraits in deterministic order.
- Apply native/source quality, identity, anatomy, crop, luma, safety, text,
  provenance, realization and exact-byte postwrite gates.
- Apply cross-orientation parity against the matching authoritative landscape.
- Quarantine every FAIL/NOT_VERIFIED, multi-output, contact sheet, stale
  reference or malformed candidate. Repair only the failed basename within
  the canonical attempt budget.

### M8-D package quality and publication

- Evaluate all twelve canonical package-quality dimensions from deterministic
  measurements and independent semantic evidence.
- Publish verdict PASS only when all required component evidence is current,
  digest-bound and no hard FAIL/NOT_VERIFIED remains.
- Build the Stage 3 archive in canonical FILE-SET-01 order: manifest, ten
  landscapes, ten portraits, story, validation report, character references,
  visual plan, visual bible, package quality report and optional anchor.
- Reopen and safely extract the archive; verify order, CRC, dimensions,
  ownership, parent digest, exact bytes and repeatable output.

## Definition of Done

- All three profiles pass deterministic Stage 3 ZONE fixtures.
- Exactly ten distinct portrait transactions commit the canonical basename set;
  landscapes and all other inherited members remain byte-identical to M7.
- Every portrait is 1080x1920 PNG with current provenance, realization,
  semantic and postwrite evidence.
- Portrait pilot, cross-orientation parity, cover, outro, safety and targeted
  repair paths have positive and fail-closed tests.
- `package_quality_report.json` schema 2.0 binds all twelve dimensions,
  component evidence, score/rating and publish verdict without self-assertion.
- Stage 3 `story.zip` binds the exact M7 digest, follows FILE-SET-01, safely
  extracts, reopens byte-for-byte and builds repeatably.
- Restart/fault tests prove no duplicate transaction, progress increment,
  package event or publication.
- Ruff format/lint, strict mypy, full pytest, coverage threshold, canonical
  hash/read-only and `git diff --check` pass.
- One explicit offline local production run commits all ten portraits and a
  PASS final package without downloads or non-loopback traffic.

## Stop conditions

Stop before an image call if parent package authority, frozen basename set,
Visual Bible bytes, matching landscape/reference bytes, invocation cardinality
or runtime provenance is absent or inconsistent. Stop before publication if
any portrait, parity check, quality dimension, provenance record or inherited
byte is FAIL or NOT_VERIFIED.
