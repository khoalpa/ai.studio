# M7 Stage 2 ZONE Implementation Plan

## Purpose and boundary

M7 implements the Stage 2 ZONE workflow on top of the completed M6 image
runtime. It accepts one authoritative CURRENT Stage 1 `story.zip`, creates
exactly ten landscape assets, serializes `visual_plan.json` and
`visual_bible.json`, and publishes a verified Stage 2 workflow checkpoint.

M7 does not create portrait assets, `package_quality_report.json` or
`video_prompts.json`; those belong to later milestones. It does not modify the
canonical prompt, resolve `PCF001`, add cloud fallback or download models.

## Entry preflight

- HEAD contains the M6 closure commit and the working tree is clean.
- Canonical prompt SHA-256 is
  `4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27`
  and the file remains read-only.
- M1 can compile the Stage 2 capsule for all three profiles.
- M3 and M6 provide transaction lineage, one-GPU-job enforcement, candidate
  quarantine, exact-byte gates, package publication and fresh-process recovery.
- The production ComfyUI, OCR and typography path has passed one combined
  transaction; the default test suite remains offline and GPU-free.
- `visual_plan.json` and `visual_bible.json` are registered but their CURRENT
  schemas are still `NOT_VERIFIED`; M7 must implement them before generation.

## Fixed ZONE contract

The ordered basename set is:

1. `introduction.png`
2. `opening.png`
3. `cover.png`
4. `development.png`
5. `climax.png`
6. `falling.png`
7. `ending.png`
8. `greeting.png`
9. `farewell.png`
10. `outro.png`

Packaging follows the canonical ZONE allowlist, while execution uses the
canonical identity-pilot and calibration order. Every generated asset has one
logical transaction, one basename, one final-purpose landscape canvas and one
committed authoritative output. Retries create generation calls within the
same transaction and never create a second commit for the basename.

## Implementation slices

### M7 A Stage 2 input and schemas

- Validate and safely extract one authoritative Stage 1 `story.zip`.
- Bind its package, manifest, story, validation report, character references
  and optional series anchor as immutable parent inputs.
- Implement strict CURRENT schemas, field order and deterministic serializers
  for `visual_plan.json` schema 1.0 and `visual_bible.json` schema 2.0.
- Reject loose files, source conflicts, wrong package stage, parent digest
  mismatch and any attempt to mutate Stage 1 members.

### M7 B ZONE planning and queue

- Resolve mode to ZONE and freeze the exact ten-basename set once.
- Build basename-scoped visual plans and Visual Bible identity, wardrobe,
  location, prop, symbol and dependency locks from validated Stage 1 bytes.
- Persist the execution queue in the required pilot, calibration, cover and
  wave order without exposing package-wide context to the image backend.
- Add deterministic payload firewall checks for orientation LANDSCAPE,
  `FINAL_REQUIRED_ASSET`, output count one and current basename only.

### M7 C Landscape execution and gates

- Reuse the M6 transaction for all ten assets with at most one GPU-heavy job.
- Generate `introduction.png` as identity pilot, `opening.png` as calibration,
  prove the cover path, then execute remaining waves.
- Apply native/source-quality, identity, continuity, luma, text, cover, outro,
  provenance and postwrite exact-byte gates as applicable.
- Quarantine fan-out, contact sheets, portrait output, stale references,
  pseudo-text and every FAIL or NOT_VERIFIED candidate without increasing
  progress.
- Permit targeted repair only for the failed basename and preserve locks from
  previously authoritative assets.

### M7 D Stage 2 checkpoint

- Require ten distinct committed transactions and ten authoritative landscape
  PNGs; no portrait member may exist.
- Serialize the Stage 2 workflow manifest with parent-package digest and exact
  generation/reuse lineage.
- Build `story.zip` with inherited Stage 1 bytes, the two Stage 2 JSON files,
  ten landscapes and the optional inherited anchor only.
- Reopen, safely extract and validate every member, manifest relation, parent
  digest, metadata commitment and ordered file set before publication.
- Cover fresh-process recovery across planning, queue, per-asset commit and
  package publication boundaries.

## Definition of Done

- All three profiles pass deterministic Stage 2 ZONE fixtures.
- Exactly ten landscape basenames exist and exactly ten distinct asset
  transactions are committed; there are no portrait assets.
- `visual_plan.json` and `visual_bible.json` pass implemented CURRENT schemas
  and bind the exact story, characters, locks, landscape digests and mode.
- Every new PNG has current provenance/realization/postwrite evidence, and any
  hard FAIL or NOT_VERIFIED state blocks checkpoint publication.
- Identity pilot, calibration, cover, landscape coherence, outro and targeted
  repair paths have positive and fail-closed tests.
- Stage 2 `story.zip` binds the exact Stage 1 parent digest, has the canonical
  member set, safely extracts, reopens byte-for-byte and builds repeatably from
  identical authoritative inputs.
- Restart/fault tests prove idempotent recovery with no duplicate transaction,
  binding, progress increment, package event or publication.
- Ruff format/lint, mypy strict, full pytest, coverage threshold, canonical
  hash/read-only and `git diff --check` pass.
- One explicit local production acceptance run generates and commits the full
  ten-landscape ZONE set without downloads or non-loopback traffic.

## Stop conditions

Stop before an image call if the Stage 1 package, character references,
optional serial anchor, mode, basename scope, invocation cardinality or local
runtime provenance is absent or inconsistent. Stop before checkpoint creation
unless all ten assets are authoritative with current exact-byte evidence.
`PCF001_STAGE4_AUDIO_MODE_DEFAULT_COLLISION` remains visible but is not active
in the Stage 2 capsule or M7 acceptance decision.
