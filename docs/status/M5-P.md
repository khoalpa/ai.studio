# Milestone M5-P Production Enablement Status

Status: PRODUCTION STORY BLUEPRINT CONTRACT VERIFIED; CHARACTER REFERENCES PENDING.

## Purpose

M5-P is the prerequisite required to replace the explicit M5 test-only Stage 1
package before M7 can close. It must preserve the CURRENT Stage 1 `story.zip`
layout and canonical v3.16.13 bytes. It does not authorize M8, cloud fallback,
credentials, automatic runtime downloads or schema drift. The explicitly
approved one-time dependency acquisition is recorded below.

## Preflight evidence

- `Stage1Service._execute` deliberately returns `WAITING_DEPENDENCY` with
  `S143_TEST_ASSET_PRODUCTION_PATH` whenever `Stage1Request.test_mode` is false.
- The existing Stage 1 builder creates `TEST_ONLY_M5_MOCK` character PNGs and
  records `mock semantic evidence bound to final digest`; relabeling those bytes
  would violate the production validator and provenance contract.
- Neither `llama-server` nor `llama-cli` is installed or available on `PATH`.
- No local GGUF text-generation model was found in the configured local model
  roots. The only discovered model is `Qwen2.5-VL-7B-Instruct`, provisioned as
  the independent Stage 2 image assessor rather than the Stage 1 writer.
- No model was downloaded and no remote or cloud endpoint was contacted.

## Required implementation slices

1. Provision an explicitly approved local text model and loopback llama.cpp
   backend, with immutable model identity and digest evidence.
2. Replace the deterministic M5 story builder on the production route with
   strict structured plan, draft, review, repair and serialization outputs from
   the M4 adapter. Every output must pass the existing CURRENT Stage 1 schemas
   and exact field order before it can be committed.
3. Generate or supply non-test character references through the local M6 image
   authority path. Bind exact bytes, decoded pixels, identity evidence and
   provenance to the final story characters.
4. Produce independent non-mock story-quality evidence, build the unchanged
   Stage 1 archive, reopen it byte-for-byte and prove recovery/idempotency.
5. Run M7-F again from that authoritative package. Existing test-rooted Stage 2
   artifacts remain evidence for runtime behavior only and must not be promoted.

## Stop condition

Do not begin production generation until an approved local text model path (or
an already-running loopback llama.cpp endpoint) is provided and its provenance
is recorded. Missing dependencies remain `WAITING_DEPENDENCY`; they never become
a semantic PASS by assertion.

## Approved dependency acquisition

The user explicitly approved a one-time download on 2026-09-14. This does not
add an automatic downloader to the runtime. Resumable `.part` files are stored
under `D:\Documents\Models\m5p-downloads` and must not be promoted or executed
until their exact hashes pass.

- llama.cpp stable `b10516`, Windows CUDA 13.3 x64 binary ZIP, 146,794,747
  bytes, expected SHA-256
  `462fc1b2eddb78b594a93867778a1a0cb15a39f0c0b16e9337f0b56ca7aa25f9`.
- CUDA 13.3 runtime ZIP for the same release, 390,970,417 bytes, expected
  SHA-256
  `1462a050eb4c684921ba51dcc4cc488a036674c3e73e9945ee705b854808d03e`.
- Official `Qwen/Qwen2.5-7B-Instruct-GGUF` Q4_K_M shard 1, 3,993,201,344
  bytes, expected SHA-256
  `dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db`.
- Official Q4_K_M shard 2, 689,872,288 bytes, expected SHA-256
  `539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a`.

All four transfers use explicit upstream URLs and resume in place. Network
throughput observed at start was too low to complete within this checkpoint.

## Local runtime attempt

- All four downloads completed with the exact expected byte sizes and SHA-256
  values. The two llama.cpp archives passed ZIP CRC and traversal checks before
  extraction to `D:\Documents\Models\llama.cpp-b10516-cuda13.3`.
- Both `llama-server.exe --version` and `llama-cli.exe --version` exit before
  argument processing with Windows status `0xC0E90002`. The downloaded archive
  itself matches the official release digest, and neither ZIP nor extracted
  files carries a `Zone.Identifier` stream.
- The release executables and native DLLs are unsigned. Windows rejects the
  native image; no security control, application-control policy or antivirus
  setting was disabled or bypassed.
- WSL2 is not installed, and no local CMake/MSVC toolchain is available for a
  source build. Installing those system components is outside this checkpoint.

The GGUF files remained verified and preserved while execution was blocked.
No alternate backend or security-policy bypass was introduced.

## Windows execution retry

After the user changed the local Smart App Control setting, the same
hash-verified `llama-server.exe` ran successfully without modifying any project
security behavior. It reports llama.cpp build `10516`, commit `b95502ba9`.

- Server binding: `127.0.0.1:8080` only; Web UI disabled.
- Model: official Qwen2.5-7B-Instruct Q4_K_M split GGUF; llama.cpp resolved both
  verified shards from shard 1.
- Runtime: 16,384-token context, one slot, 99 requested GPU layers.
- `/health`: `{"status":"ok"}`.
- `/props`: Q4_K Medium, one slot, context 16,384, build
  `b10516-b95502ba9`, UI false.
- Direct deterministic completion returned 16 tokens from the local model.
- The repository M4 integration smoke against
  `AUDIO_STORY_LLAMA_CPP_SMOKE_URL=http://127.0.0.1:8080` passed: 1 test passed
  in 0.18 seconds.

The dependency blocker is resolved. M5-P remains open because the production
Stage 1 plan/draft/review/repair/serialize route and non-test character
references are not yet implemented.

## M5-P-A adapter contract correction

The loopback adapter now composes the immutable prompt capsule and the
phase-specific instruction into the actual llama.cpp prompt. Structured and
semantic calls use llama.cpp's `json_schema` request field instead of the
previous unused `json_mode` flag. The adapter also treats both
`stop_reason: length` and llama.cpp's current `stop_type: limit` as
`LLM008_TRUNCATED_OUTPUT`, so incomplete output cannot be committed.

Evidence collected on 2026-09-14:

- Focused adapter tests: 15 passed, 1 opt-in integration smoke skipped; Ruff
  passed for both changed files. The focused pytest invocation alone reports
  the repository-wide coverage threshold as expected because it does not run
  the full suite.
- A live structured call through the verified Qwen2.5-7B endpoint returned and
  parsed exactly `{"status":"PASS","evidence":"adapter-live-smoke"}` while
  constrained by an object JSON schema.
- The server was stopped after the smoke call and port 8080 was verified free,
  preserving the one-GPU-heavy-job invariant.
- Full repository baseline after the correction: `ruff format --check .` passed
  for 134 files; `ruff check .` passed; strict `mypy src` passed for 64 source
  files; `pytest` passed 307 tests with 2 skips and 91.16% coverage.

The next M5-P slice is to define deterministic, phase-specific production
schemas and bind validated plan/draft/review/repair/serialize bytes and lineage
to workflow transactions. This adapter evidence is necessary plumbing, not a
claim that the production Stage 1 archive is complete.

## M5-P-B five-phase production checkpoints

The non-test Stage 1 route now executes `plan`, `draft`, `review`, `repair` and
`serialize` through `generate_structured`. Every later request includes the
exact validated upstream phase bytes in execution order, and the resulting
request digest therefore binds the chain. Recovery reloads committed upstream
bytes from the content-addressed store. Each response must use the exact root
order `schema_version`, `phase`, `status`, `payload`, match schema version 1.0,
match its transaction phase, report `PASS`, and satisfy a phase-specific exact
payload order with non-empty values. Parsing, NFC checks, duplicate-key checks,
field order and value checks all run before candidate registration and commit.
Invalid responses consume the bounded retry budget and fail closed.

After all five commits, production stops before story materialization with
`S144_CHARACTER_REFERENCE_PRODUCTION_REQUIRED`; it does not invoke the M5 mock
story/character builder or publish a package.

Live evidence collected with the verified local Qwen2.5-7B backend:

- Evidence workspace: `artifacts/m5p-stage1-production-chained`.
- Workflow: `e975716928584982b6ad3c631ef1585b`; stage:
  `3a95f4dff4794800a2328fbbf2be6b1e`.
- Five text transactions committed and five deterministic checkpoint gates
  passed. Gate evidence digests, in phase order: `af9e094586ecbf7f0f1ecb322152f6fc47a891a671141af3d59d5663e4803473`,
  `73fa8f0552218ea20b88d7df7a613fd265409bd1407d9c59e8fa156593b03535`,
  `433597b1da57a072e3ed7e68e08d3c8594ca266ba8f6af5fb91e9023936e5263`,
  `cdd5e46fedf2b65555c7afeaa54841dc223b8220aac24f0a6c780fac03b76eab`,
  and `b46fe8492a57a7bc54d72a230aa21ff17340b133b0620479dd1759121238131c`.
- The live result was `WAITING_DEPENDENCY` with reason
  `S144_CHARACTER_REFERENCE_PRODUCTION_REQUIRED`; no `story.zip` was produced.
- The local server was stopped and port 8080 verified free after execution.
- M5-P-B integration coverage passed 28 tests. The final full baseline passed
  308 tests with 2 skips and 91.19% coverage after one unrelated orphan-temp
  timing test was rerun successfully and the complete suite was repeated.

M5-P-B is complete. The next slice is production story materialization plus
non-test character-reference generation and binding through the single-GPU
image authority; M5-P remains open until those bytes and independent quality
evidence pass the existing unchanged Stage 1 validators.

## M5-P-C1 materialization-ready serialize contract

Inspection of the first chained live run showed that the structural M5-P-B
contract still admitted generic placeholder content. The active serialize
contract now requires `payload.story` to contain exactly `title`, `characters`,
`outline`, `script`; it validates nested field order, non-empty character
descriptions, positive ages, unique `char_` IDs, unique script item IDs,
complete sentence punctuation, valid zones and presence of all eight canonical
zones in order. The serialize prompt carries the same deterministic contract.

Committed production phases are revalidated against the active contract during
recovery. Resuming the prior live evidence workspace correctly rejected its
legacy placeholder serialize artifact with
`S161_COMMITTED_PHASE_SCHEMA_DRIFT`; the underlying deterministic finding was
`DJ010_MISSING_FIELD` for `title`, `characters`, `outline`, and `script`.
Generation-time regression coverage also proves a placeholder consumes both
attempts, leaves `serialize.json` `FAILED_RETRYABLE`, and creates no committed
serialize binding.

This completes M5-P-C1 only. Character PNG generation, reference metadata
injection, full duration/item-count validation, independent semantic quality
evidence and package publication remain pending and cannot be inferred from a
blueprint-schema PASS.

Verification after M5-P-C1: 29 focused Stage 1 tests passed; the full suite
passed 309 tests with 2 skips and 90.72% coverage. Ruff format/lint and strict
mypy passed.

## M5-P-C2 character image authority

The Stage 1 production route now accepts an explicit local character-image
configuration. ComfyUI receives digest-bound positive/negative prompts through
`commitment_context`; prompt text is injected only into an in-memory copy of
the hash-verified workflow. Character generation requires one 1536x2048 PNG,
role `CHARACTER_ASSET`, owner `STAGE1`, production metadata with exact
`character_id`, and a current deterministic image gate. Request hashing now
includes the full commitment context. The authority row is recorded as
`AUTHORITATIVE`, current `PASS`, and immutable before the artifact binding is
committed. Mock backend/model identities are rejected with
`IMG017_TEST_BACKEND_PRODUCTION_PATH`, and committed references are reopened
idempotently from the content-addressed store.

The direct ComfyUI process did not load Comfy Desktop's shared-model mapping.
Two local hardlinks (no model copy or download) expose the already verified
SDXL checkpoint under the shared and installation `models/checkpoints`
directories. Both links hash to the approved
`31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b`.

Live deterministic evidence in `artifacts/m5p-character-live4`:

- Transaction `0743e52d94f94bb6af5b00c18151b4f3`, call
  `0b956bf5c1a04999966a12e73266cd72`.
- Exact PNG SHA-256
  `3c24d9fdd51385cb45b4718a7a5e5f650d90c89284b5b385fd1ac979dca7afbc`;
  1536x2048 RGB; embedded production provenance and prompt/workflow/model
  digests all reopened successfully.
- Independent local Qwen2.5-VL assessment returned `FAIL`, evidence digest
  `640eb728bfe59aaa02c10f7d92666415784ae6c55d36665823e98961180bd872`,
  because the image visibly contains duplicate people for one character ID.
- The image authority record is therefore `QUARANTINED` with code
  `SEMANTIC_DUPLICATE_CHARACTER`; downstream packaging must not use it.
- ComfyUI was stopped after generation and the VLM ran only after the image
  worker released the GPU.

M5-P-C2 infrastructure is implemented, but its live artifact is not accepted.
The next slice must put the independent single-person/identity semantic gate
before immutable commit and retry generation on semantic failure. A
deterministic image-QA PASS alone is insufficient for a character reference.

Verification after M5-P-C2: 49 focused image/Stage 1 tests passed; the full
suite passed 312 tests with 2 skips and 90.65% coverage. Ruff format/lint and
strict mypy passed for 65 source files.

## M5-P-C3 precommit semantic character gate

Character generation now requires a semantic assessor. It runs on exact final
PNG bytes after deterministic QA but before candidate registration. Evidence
must bind the exact image SHA-256 and return only `PASS` or `FAIL`. A failure is
persisted as `IMG018_SEMANTIC_GATE_FAIL`, creates no candidate or binding, and
retries with the next seed; malformed/unbound evidence fails as
`IMG019_SEMANTIC_GATE_INVALID`. A successful artifact receives both current
`IMAGE_QA_GATE` and `CHARACTER_SEMANTIC_GATE` records before authority binding.
Production character configuration without an assessor is rejected as
`IMG020_SEMANTIC_GATE_REQUIRED`.

Live sequential GPU evidence in `artifacts/m5p-character-semantic-live`:

- Workflow `7dda098c3d2c40ee89dabc3daa539ce9`, stage
  `2ba6d74da6294a5d91977b5910f1293b`, transaction
  `4472cb9f32f24aefb70fe42f78cc711e`.
- Seed 1701 failed before commit with `IMG018_SEMANTIC_GATE_FAIL`; local
  Qwen2.5-VL evidence digest
  `f6807c9cff441e22e49e6326775f9022d88e6372eb26119efe4abc95b2d8a5a8`.
- Seed 1702 passed the independent VLM assessment, evidence digest
  `6bf427b09f0c23455bb9defea154b30920f0aad87e444c86688575025b088f98`.
- Only attempt 2 was committed: artifact
  `6971ebd4a1bb48a6aac30b58918447d8`, PNG SHA-256
  `50d03079cd8844f89fb85a1282df0d6c943d7f0bb8c7cfb2146014573ca349bc`.
- ComfyUI explicitly unloaded its model before each VLM subprocess, the VLM
  exited before any retry, and port 8189 was released afterward. Thus only one
  GPU-heavy job ran at a time.

The reusable live entry point is
`scripts/run_m5p_character_semantic_smoke.py`. M5-P-C3 is complete for one
character transaction. The next slice must bind accepted character bytes into
the serialize blueprint, compute reference/pixel/identity fields, and pass the
unchanged full `story.json` validator before package work begins.

Verification after M5-P-C3: 12 focused semantic/image transaction tests passed;
the full suite passed 313 tests with 2 skips and 90.50% coverage. Ruff
format/lint and strict mypy passed for 65 source files.

## M5-P-C4 story materialization and reference binding

The production route now materializes `story.json` only from a validated
serialize blueprint and one accepted image result per character. It reopens
each exact content-addressed image and requires its image authority row to be
`AUTHORITATIVE`, current `PASS`, and immutable. The materializer computes a
decoded RGBA pixel digest independently of the PNG file digest, derives an
identity lock from character ID, description and pixel digest, and injects the
unchanged CURRENT reference field order. It then runs
`validate_character_assets(..., test_mode=False)` and `validate_story_bytes`
before checkpointing `story.json`.

Semantic story quality is deliberately not asserted during materialization.
The commitment records `semantic_quality_status: NOT_VERIFIED`, and a
successful production route stops with
`S147_PRODUCTION_QUALITY_EVIDENCE_REQUIRED`; report and ZIP publication remain
blocked.

A live materialization smoke reused the C3 accepted exact image bytes and
passed the CURRENT story/character validators:

- `story.json` SHA-256:
  `0643305e9b853524dd8e5a0567c46608dd893abb08ea2ccf35c8db0a1b97d000`;
  43,210 bytes, 5,520 recomputed words and 60 script items.
- Character PNG file SHA-256:
  `50d03079cd8844f89fb85a1282df0d6c943d7f0bb8c7cfb2146014573ca349bc`.
- Decoded RGBA pixel SHA-256:
  `ae2825ffcbd59b6ee195006f18772e8544c944e2ed77ed0aee8f53eb107c1301`.
- Quality status remained `NOT_VERIFIED`. The synthetic script used by this
  smoke proves deterministic materialization only and is not production story
  content or semantic PASS evidence.

The next slice must strengthen plan/draft/review/repair content contracts,
generate a real duration-compliant story, and attach independent digest-bound
quality evidence before building `story_validation.json`.

Verification after M5-P-C4: 33 focused Stage 1/materialization tests passed;
the full suite passed 314 tests with 2 skips and 90.50% coverage. Ruff
format/lint and strict mypy passed for 66 source files.

## M5-P-D1 independent quality evidence contract

The production quality-finalization path now requires exact evidence bindings
for the final script digest and ordered character asset-set digest. In
addition to the bounded final/progression/engagement scores, the assessor must
return exactly eight quality dimension scores and five engagement dimension
scores, each an integer in `0..2`. The commitment stores those arrays and the
report derives `quality_raw_score` and `engagement_raw_score` by summing the
evidence arrays; production reports therefore do not use hard-coded raw-score
arrays. Any missing, mis-sized, or out-of-range dimension list fails closed
before `story.json` is checkpointed.

Verification after M5-P-D1: focused Stage 1/materialization tests passed;
`ruff format --check` and `ruff check` passed for changed files; strict mypy
passed on 66 source files; full suite passed 315 tests with 2 skips and
90.23% coverage. This slice is still contract/infrastructure work: the live
story smoke remains synthetic, no production `story.zip` was published, and
M5-P-D remains open pending a real duration-compliant local story and an
independent assessor run that returns digest-bound PASS evidence.

## M5-P-D2 production preflight

The verified local GGUF shards and the ComfyUI install/checkpoint are present:
the two Qwen2.5-7B-Instruct shards remain under
`D:\Documents\Models\m5p-downloads`, and the approved SDXL checkpoint remains
available through the existing ComfyUI hardlinks. Both loopback services were
checked before this checkpoint and were stopped (`127.0.0.1:8080` and
`127.0.0.1:8189` are free). No production story generation was started because
the repository has no single approved end-to-end runner that wires the five
phase Stage 1 service, ComfyUI character authority, and independent story
assessor together; starting only one backend would not produce valid package
evidence. This is a safe preflight stop, not a semantic PASS.

The next implementation slice is a bounded local production runner with
explicit sequential GPU ownership: launch/health-check llama.cpp, run the
five-phase Stage 1 route, release/unload it, launch ComfyUI for character
references, release/unload it, then run the independent story assessor and
checkpoint only on digest-bound PASS. The runner must stop with a stable
WAITING_DEPENDENCY/WAITING_INPUT result if either backend is unavailable.

## M5-P-D3 deterministic environment preflight

Added `scripts/m5p_production_preflight.py`. It performs no download and no
process launch; it checks the hash-verified llama-server executable, both
verified GGUF shards, the ComfyUI install/checkpoint and loopback port
availability, then emits machine-readable JSON. The current machine returned
`READY`: both ports are free, all required files exist, and the observed
digests are the approved llama shards and SDXL checkpoint. Ruff format/lint
passed for the new script. This is environment readiness only; it is not a
story-generation or semantic-quality PASS.

## M5-P-D4 sequential backend smoke

Added `scripts/m5p_backend_smoke.py`, which launches the verified llama.cpp
server first, checks `/health`, terminates it, then launches ComfyUI and checks
`/system_stats`. It uses loopback bindings and one GPU-heavy process at a time;
it never downloads or falls back to cloud. The current run returned llama
`PASS` with `{"status":"ok"}` and then `WAITING_DEPENDENCY` because the
ComfyUI process did not expose `/system_stats` before the bounded timeout. Both
processes were terminated and ports 8080/8189 were free afterward. Ruff
format/lint passed for the runner. Production story generation remains blocked
until the ComfyUI launch profile is corrected and its health evidence passes.

The launch profile was corrected to use ComfyUI's bundled
`ComfyUI\\.venv\\Scripts\\python.exe`; the workspace Python lacks ComfyUI's
SQLAlchemy dependency and is not a valid launcher. A rerun then passed both
backends sequentially: llama `/health` returned `{"status":"ok"}` and ComfyUI
`/system_stats` reported ComfyUI 0.35.1, PyTorch 2.12.1+cu130 and the RTX
A4500 device. Both processes were terminated after the checks and the loopback
ports were released. This closes backend environment smoke only; it does not
create a story or semantic evidence.

## M5-P-D5 live five-phase Stage 1 attempt

Added `scripts/run_m5p_stage1_llama.py` and ran it against the verified local
Qwen2.5-7B-Instruct server using the bundled model shard. The live route
successfully committed `plan.json`, `draft.json`, `review.json` and
`repair.json` with completed generation calls. The strict `serialize.json`
contract rejected both bounded attempts with `S110_GENERATION_FAILURE`, so no
serialize artifact, character generation, story materialization or package was
created. The workflow remains incomplete and this is evidence that the current
local model needs a more explicit content contract/repair prompt before the
production route can proceed. No cloud fallback or test artifact was promoted.

The serialize instruction was then strengthened with a minimum 40-item
requirement and retried using the smaller `YOUTH_SAFE` 12-minute profile. The
local model still exhausted both serialize attempts and left `serialize.json`
`FAILED_RETRYABLE`; no character or story artifact was checkpointed. Prompt-only
tightening is therefore insufficient for the current model/context budget. The
next implementation must use a bounded per-zone content construction loop with
deterministic aggregation, while retaining the LLM as writer and the strict
final serializer gate.

The first per-zone prompt attempt was executed live with the local model. It
still left `serialize.json` `FAILED_RETRYABLE` after two bounded calls, so the
prompt-level block is reproducible even at the smaller profile. This rules out
simply increasing the item-count wording as a sufficient fix. The next change
must split generation into actual per-zone transactions (one compact LLM call
per zone, validated before aggregation) and keep serialization as a
deterministic final assembly step.

## M5-P-D7 decision point

The repeated live failures establish a model-capability/context-budget
blocker, not a backend availability issue. Do not spend additional GPU runs on
the monolithic serialize call. The next implementation must introduce a
versioned zone-generation transaction contract with per-zone payloads,
zone-local validation, bounded retry and deterministic aggregation into the
existing CURRENT blueprint. Until that adapter and its fixtures exist, M5-P
remains open and no production package may be claimed.

## M5-P-D8 zone contract scaffold

Added `stage1_zone_generation.py` with a versioned per-zone payload contract,
strict field-order validation, exact five-item zone cardinality, sentence and
metadata checks, canonical zone-order enforcement, and deterministic
aggregation to the existing 40-item serialize blueprint. Unit coverage is
3/3 PASS; Ruff format/lint and strict mypy pass. The module is intentionally
not wired into the production route yet: the next slice must connect each
validated zone payload to bounded local LLM transactions and persist their
lineage before aggregation.

## M5-P-D9 transactional zone generation

The production Stage 1 route no longer sends the monolithic `serialize` prompt
that repeatedly exhausted the local model. After the existing plan, draft,
review and repair checkpoints, it now opens one `zone-<zone>.json` transaction
for each canonical zone. Each transaction has two bounded attempts, strict
version/header/field-order/cardinality validation, its own generation-call
lineage and a deterministic PASS gate. A failed zone cannot publish and cannot
create `serialize.json`.

Profile minimum item counts are distributed deterministically across the eight
canonical zones. Only after all eight zone payloads commit are their item IDs
renumbered in canonical order and the existing CURRENT story blueprint assembled
and revalidated. `serialize.json` is written by the deterministic Stage 1 writer,
not accepted from an LLM response. Recovery reopens committed zone bytes,
revalidates their active contract and skips their LLM calls; a regression test
interrupts after OPENING and confirms that every zone retains exactly one call
after fresh-process resume. Another regression proves that an invalid first
attempt and valid second attempt share one logical GREETING transaction.

Verification after M5-P-D9: 34 focused Stage 1/zone tests passed. Ruff format
and lint pass for the full repository; strict mypy passes on 67 source files in
the clean Python 3.11-target environment; the full suite passes 320 tests with
2 expected local-service skips and 90.15% total coverage. `git diff --check`
passes and the canonical prompt SHA-256 remains
`4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27`.

M5-P remains open. The next slice is one bounded live YOUTH_SAFE run through
the eight zone transactions. It must stop before character generation if the
zone/aggregate contract fails; successful text generation may then proceed to
the already implemented sequential ComfyUI character-authority and independent
story-quality gates.

## M5-P-D10 live transactional zone smoke

The deterministic preflight returned `READY` with the previously approved
llama.cpp executable, both Qwen2.5-7B-Instruct GGUF shards and SDXL checkpoint;
ports 8080 and 8189 were free. The first isolated run failed closed at GREETING
because the model encoded `speed` as a JSON number. Both attempts were rejected,
no zone artifact was committed and no `serialize.json` was created. The zone
instruction was corrected to require every item field to be a JSON string and
the exact value `"1.0"`; focused regression coverage remained 34/34 PASS.

The second isolated run in `artifacts/m5p-d9-zone-live-20260914-r2` completed
all 13 text transactions: four production phases, eight canonical zones and the
deterministically assembled `serialize.json`. Every zone has a persisted PASS
gate. The final blueprint contains exactly 40 items, five per zone, renumbered
from `item_001` through `item_040`; its artifact SHA-256 is
`ccdb2886355b4ce55409e89296d28d0a6c55c4400daf57702d77a72a8c7eead1`.
The runner returned `WAITING_DEPENDENCY` with
`S144_CHARACTER_REFERENCE_PRODUCTION_REQUIRED`, as required at the text/image
boundary, and terminated llama.cpp; port 8080 was free afterward. No model or
runtime bytes were downloaded and no cloud endpoint was used.

This closes the live text-generation portion of M5-P-D. M5-P remains open until
the accepted blueprint passes sequential ComfyUI character authority,
duration-compliant story materialization and the independent semantic quality
gate before production package publication.

## M5-P-D11 resumed character authority and duration stop

Added `scripts/run_m5p_resume_character.py`. Unlike the earlier isolated image
smoke, it requires an existing workflow/stage, reopens that stage's committed
`serialize.json`, and resumes through `Stage1Service` without launching or
calling llama.cpp. It uses the blueprint's exact character metadata, the pinned
M6 ComfyUI workflow/model digests and the existing independent offline VLM gate.

The runner resumed workflow `d362e15e6e19428286e5f112041b1837`, stage
`895203a688f54af7b09d9b20fa5ec2bb`. ComfyUI 0.35.1 generated one 1536x2048
character reference; the offline Qwen2.5-VL assessment returned PASS with
evidence digest
`9318da449eb61c95640fd4ee8f740ee471e5112db2182933bee02dfa21ce536f`.
`char_001.png` is authoritative and committed with SHA-256
`8daac954f2e9f9842dfb57490e05680765203c8558ae461ec5dadb4b8e84eb7a`.
ComfyUI unloaded its model before VLM execution and port 8189 was free after
the runner, preserving the one-GPU-heavy-job invariant.

Materialization then stopped deterministically at `S126_DURATION_WPM`. The
accepted 40-item blueprint contains only 502 words while the confirmed
YOUTH_SAFE target is 2,400 words (12 minutes at 200 WPM). No `story.json` or
production package was published. Character authority remains reusable on
resume, so the next implementation must version and enforce a per-zone word
budget before zone commit and regenerate the text transactions in a new
workflow; padding during materialization or bypassing the duration validator is
forbidden.

## M5-P-D21 authoritative capsule inference projection

Added a deterministic `M5P-STAGE1-INFERENCE-1.0` projection for local inference.
It preserves the authoritative M1 capsule digest, canonical prompt hash,
stage/profile/route binding and the exact bytes/digests of the duration,
validation, profile-safety and execute-now units. The full M1 capsule remains
the authority and is unchanged; the projection cannot masquerade as it. Segment
request lineage and gate evidence bind the projection SHA-256. The inference
context falls from 48,359 to 22,746 bytes (52.96% reduction), with unit tests for
selection, size and false-binding rejection.

The fresh local workflow `artifacts/m5p-d21-projected-live-20260914` still
exhausted both attempts for its first GREETING segment below 20 words. No
segment or downstream artifact was committed and llama.cpp was terminated.
Further removal of canonical units would require a separately reviewed semantic
projection contract and is not justified by this result.

Both safe in-repository approaches are now exhausted: exact-context character
calibration has no multi-seed passing range, and a digest-bound 53% capsule
projection does not stabilize the approved model. The next milestone action
requires explicit approval of another already-provisioned local text model or
decoding configuration, followed by the unchanged D20 exact-context matrix.
Automatic download, cloud fallback and validator relaxation remain forbidden.

## M5-P-D12 deterministic word budgets

Zone validation now accepts versioned minimum/maximum Unicode word budgets and
checks both every item and the aggregate zone text before candidate
registration. The production service derives the total legal range directly
from the resolved profile (`min_minutes/max_minutes * target_wpm`) and
distributes both boundaries deterministically across the eight canonical zones.
For YOUTH_SAFE this is 300–450 words per zone and 60–90 words per each of five
items, guaranteeing that any complete eight-zone set is inside the unchanged
2,400–3,600-word story duration interval. Gate evidence persists the exact
budget applied to each zone. Focused word-budget, retry and recovery coverage
passes 35 tests.

Two fresh offline YOUTH_SAFE workflows were attempted. The first used the zone
aggregate budget; both GREETING attempts were below 300 words and failed before
commit. The second additionally instructed and enforced 60–90 words for every
item; both GREETING attempts still failed the per-item minimum. Neither workflow
committed a zone or `serialize.json`, and neither started ComfyUI or published
story/package bytes. llama.cpp was terminated after each run and the loopback
port was released.

This is a repeatable granularity/capability stop condition. Further prompt-only
retries at zone granularity are not authorized by this evidence. The next slice
must introduce one bounded transaction per script item, validate its individual
word budget before commit, then deterministically aggregate five committed items
into each zone and all zones into the CURRENT serialize blueprint. Existing
short-zone or character artifacts must not be rebound across the new workflow
lineage.

## M5-P-D13 per-item transactions

The production writer now opens one transaction per script item rather than one
per zone. YOUTH_SAFE therefore has 40 independently recoverable text
transactions. Each call returns the existing strict zone envelope with exactly
one item, is checked against its deterministically allocated 60–90-word budget,
and records item index plus word boundaries in gate evidence. Five committed
items are renumbered and aggregated into each canonical zone; no intermediate
zone artifact is trusted or published. Tests cover all item basenames, retry in
one logical item transaction, and fresh-process resume across the first ten
committed items. The focused suite passes 35 tests.

A fresh offline run in `artifacts/m5p-d13-item-live-20260914` exhausted both
attempts for `item-greeting-001.json`: the local model still returned fewer than
60 words for a response containing only one requested item. No item artifact,
zone aggregate, serialize blueprint, image or package was committed. llama.cpp
was terminated and port 8080 released. This rules out 60–90-word single-item
calls for the currently approved model.

The next bounded slice should introduce short segment transactions (for example
three deterministic 20–30-word segments per item), validate each segment before
commit, and join them with deterministic punctuation into the existing item
field. The final item and zone word budgets remain authoritative; automatic
padding, repeated text, validator relaxation and unbounded retries remain
forbidden.

## M5-P-D14 short segment transactions

Each production item is now assembled from three independently persisted
segment transactions. For YOUTH_SAFE, each segment receives a deterministic
20–30-word budget; the three texts are joined without generated padding, then
the resulting item is revalidated at 60–90 words. Item metadata is normalized
deterministically, and the existing item, zone and full-duration gates remain
unchanged. The YOUTH_SAFE route has 120 recoverable segment transactions.
Focused retry, aggregation and fresh-process recovery coverage remains 35/35
PASS.

The fresh offline run `artifacts/m5p-d14-segment-live-20260914` failed closed at
the first GREETING segment: both bounded attempts contained fewer than 20 words.
No segment or downstream artifact was committed, ComfyUI was not started, and
llama.cpp was terminated. The approved local model has now repeated the same
short-response behavior at zone, item and 20-word segment granularity.

Do not add a fourth workflow granularity or relax deterministic word gates. The
next slice must diagnose the local llama.cpp response path with one isolated,
raw-output-preserving request: record the exact instruction digest, sampling and
token-limit parameters, termination reason, token count and unmodified response
bytes. Only evidence that the backend can produce a bounded 20–30-word JSON text
field should authorize another production workflow run; otherwise M5-P requires
a separately approved local text model or decoding configuration.

## M5-P-D15 raw llama.cpp response diagnostic

Added `scripts/m5p_llama_response_diagnostic.py`, a loopback-only diagnostic
that performs no workflow mutation and preserves the exact HTTP response,
decoded content and digest-bound evidence. It records the instruction/request
digests, JSON schema, seed, `n_predict`, sampling source, elapsed time,
`tokens_evaluated`, `tokens_predicted`, stop metadata, truncation flag, byte
count and independently counted output words.

The production-payload-equivalent capture (no explicit temperature override)
is stored under
`artifacts/m5p-d15-llama-diagnostic-production-payload-20260914`. With
`n_predict=256`, seed 1702 and a strict one-string JSON schema, llama.cpp
returned only 13 words / 23 predicted tokens and stopped with `stop_type=eos`;
`truncated=false`. Request SHA-256 is
`4f579241480bc7b892c84d9b26822507034e83b793f443be192927666395dfa4` and
content SHA-256 is
`3e2d3ee85bc5bd9474506d3eb934fe3441b09012428a75aa8be069851b66ff48`.
An explicit temperature-zero control independently returned 14 words / 25
tokens with the same EOS behavior. The server was terminated and port 8080 was
released.

The short output is therefore not caused by the adapter token ceiling, timeout
or truncation handling. The backend/model voluntarily emits EOS before the
minimum content budget. The next experiment must be an isolated decoding
configuration comparison (for example a reviewed EOS-control strategy) with
raw capture; production code must not adopt it until the response remains valid
JSON, terminates boundedly and reaches 20–30 words without repeated padding.

## M5-P-D16 bounded decoding comparison

The diagnostic now supports explicit EOS-control and JSON string-length bounds,
and records HTTP failures as raw evidence rather than losing the backend body.
`ignore_eos=true` with `n_predict=128` is rejected: llama.cpp returned HTTP 500
after its constrained JSON grammar stack completed, with no valid content. This
option is unsafe and must not enter the production adapter. Evidence is stored
under `artifacts/m5p-d16-ignore-eos-20260914`.

A second comparison retained normal EOS behavior and added only schema-level
`text.minLength=120` / `text.maxLength=240`. It returned valid JSON containing
28 words, predicted 40 tokens, stopped naturally with `stop_type=eos`, reported
`truncated=false`, and did not reach `n_predict=256`. Request SHA-256 is
`0561d1dfbab928f0be082af57d45820c4d04d9a93f1845cdc6245cbec0957281`;
content SHA-256 is
`13e0cba2576f94d7cd9cad87a75273d49bcd952903df8d770cd471d867d24d4c`.
Raw evidence is stored under `artifacts/m5p-d16-schema-minlength-20260914`.

D16 therefore passes one safe bounded strategy: structural JSON Schema length
constraints, not EOS suppression. Production still cannot use it because the
current `GenerationRequest` carries only a field-order hint and
`LlamaCppAdapter` sends the ineffective generic schema `{"type":"object"}`.
The next slice must add an explicit validated JSON-schema field to the adapter
contract, hash it into request lineage, test transport/rejection behavior, and
use per-segment min/max length constraints before another live workflow run.

## M5-P-D17 explicit adapter JSON Schema

`GenerationRequest` now carries an optional explicit JSON Schema.
`LlamaCppAdapter` validates that its root is an object, rejects non-serializable,
oversized and `$ref`-bearing schemas with stable
`LLM015_JSON_SCHEMA`, and otherwise sends the exact schema rather than the old
generic `{"type":"object"}`. Unit coverage verifies exact transport and
fail-closed rejection. Segment generation uses a complete closed schema for the
zone envelope and item fields, including `text.minLength=120` and
`text.maxLength=240`. Its canonical schema digest is included in both request
lineage and deterministic gate evidence. The focused adapter/Stage 1 suite
passes 51 tests; Ruff and strict mypy pass.

The fresh offline workflow `artifacts/m5p-d17-schema-live-20260914` proved that
the schema prevents the earlier short EOS response, but both attempts for the
first GREETING segment exceeded the deterministic 30-word maximum. No segment
or downstream artifact was committed and llama.cpp was terminated. Character
length is therefore not a sufficiently calibrated proxy for Vietnamese Unicode
word count: the 120–240-character range that yielded 28 words in the minimal
D16 prompt can exceed 30 words with the full production envelope/context.

The next slice must run a bounded calibration matrix using the exact production
schema and representative production instruction, varying only local
`minLength`/`maxLength`, and preserving every raw response. A range may enter
the workflow only if multiple fixed seeds all produce valid JSON within 20–30
words without truncation or repetition. Do not weaken the authoritative word
gate or spend another 120-transaction run before calibration passes.

## M5-P-D18 production-envelope schema calibration

Added `scripts/m5p_segment_schema_calibration.py`. It runs a fixed 4x3 matrix
over character bounds and seeds using the complete closed production segment
envelope, a representative GREETING instruction, normal EOS behavior and
`n_predict=256`. Every raw response and per-case digest/token/word result is
preserved under `artifacts/m5p-d18-segment-calibration-20260914`; the summary
rejects invalid JSON, word counts outside 20–30, limit/truncation stops and
low-diversity repetition.

The 80–150-character range failed two seeds with 18 and 19 words. Ranges
90–170, 100–190 and 110–210 passed all three seeds. The selected candidate is
100–190: observed counts were 22, 21 and 29 words, all ended naturally with EOS
and none was truncated or repetitive. Although 110–210 also passed, one case
consumed 243 of the 256 allowed predicted tokens, so it has inferior bounded
headroom. The server was terminated and port 8080 released after calibration.

D18 closes calibration only. The next slice may change the production segment
schema from 120–240 to the evidence-backed 100–190 range, bind the selected
bounds into versioned gate evidence/tests, and run a resumable live workflow.
It must retain the independent 20–30 Unicode-word gate because character bounds
are only a decoding aid, not deterministic acceptance evidence.

## M5-P-D19 calibrated production schema

The segment schema now uses the D18-selected 100–190-character interval and is
versioned as `M5P-SEGMENT-SCHEMA-1.0`. Gate evidence records that version, the
exact character bounds and the canonical schema digest alongside the unchanged
20–30-word deterministic budget. Focused adapter, schema, lineage, retry and
recovery coverage passes 51 tests; Ruff and strict mypy pass.

The fresh offline workflow `artifacts/m5p-d19-calibrated-live-20260914` still
exhausted both attempts for the first GREETING segment below the 20-word
minimum. No segment or downstream artifact was committed and llama.cpp was
terminated. D18's representative prompt was therefore not sufficiently
equivalent to production: the live request also contains the full canonical
capsule and four committed upstream phase outputs, which can change generation
behavior even under the same schema and seed.

Do not tune character bounds again from the D18 matrix. The next diagnostic
must reconstruct the exact first-segment production prompt from the failed D19
workspace, preserve its raw response, and run a small bound matrix while holding
the capsule, upstream bytes, schema structure and seed constant. If no interval
passes multiple seeds under that exact context, the approved model/configuration
is a production dependency blocker rather than a workflow-granularity defect.

## M5-P-D20 exact-context calibration

The calibration runner now accepts a failed production workspace, reopens the
exact committed plan/draft/review/repair bytes, recompiles the YOUTH_SAFE
capsule, and calls the same production instruction/schema helpers. Only
character bounds and fixed seed vary. Twelve raw responses and the summary are
stored under `artifacts/m5p-d20-exact-context-calibration-20260914`.

No bound passed all three seeds. Results were: 80–150 => 23/14/18 words;
90–170 => 26/30/18; 100–190 => 26/32/18; 110–210 => 26/33/18. Seed 1704
remained below budget for every range, while seed 1703 crossed from valid to
over-budget as bounds increased. All requests used the same exact production
context, whose llama.cpp timing evidence reports approximately 12,782 prompt
tokens, and normal bounded EOS behavior.

D20 therefore confirms the current approved model/configuration is not stable
against the deterministic 20–30-word contract across fixed seeds. No further
character-bound tuning or full workflow retry is justified. M5-P is blocked on
a separately reviewed local text-model/decoding decision, or on an approved
prompt-capsule compaction design that preserves the M1 digest/binding contract.
Cloud fallback, automatic model download and validator relaxation remain
forbidden.
## M5-P semantic retry regression

Added an integration regression proving that a semantic gate `FAIL` on attempt 1
followed by `PASS` on attempt 2 commits the second image as `AUTHORITATIVE` and
advances stage progress. The focused test passes; no validator or offline policy
was changed.

The character smoke runner now waits for the ComfyUI `/system_stats` health
endpoint before submitting work, preventing startup races from being reported as
transport failures.

## M5-P-D22 authoritative character pipeline evidence

The offline character transaction was rerun against ComfyUI 0.35.1 on
`127.0.0.1:8188` and the provisioned Qwen2.5-VL-7B-Instruct Transformers model.
The first generation call finished without retry, the semantic assessor returned
`PASS`, and the transaction committed artifact
`c584aa7dba3c46788015bcf688c04461` as `AUTHORITATIVE`. The image SHA-256 is
`3f532f85d249f1ad9cee7e809495d92e25a917efd834c63c98d96db2a40a3d84`; the
semantic evidence digest is
`98f0478fe2b63e51fc1f37ba0fdfecbb95a3cd67f61eed484a987025bbc30cdc`.
The evidence workspace is
`artifacts/m5p-vl-character-smoke-20260914-cli-final`.

This closes the character image/VLM execution path only. M5-P remains blocked by
the D20 text-generation result: the current Qwen2.5-7B GGUF decoding behavior is
not stable against the deterministic 20–30-word segment contract. Do not start a
later milestone until that text dependency is resolved and the complete M5-P
Definition of Done passes.

## M5-P-D23 greedy exact-context calibration

The calibration runner now records explicit `temperature` and `top_p` values in
every case and in its summary. Against the same D20 exact production context,
Qwen2.5-7B GGUF with greedy decoding (`temperature=0`, `top_p=1`) produced 25
words for all three fixed seeds at both 100–190 and 110–210 character bounds.
Both bounds therefore PASS the unchanged 20–30 Unicode-word gate; 80–150 and
90–170 remain below budget. Raw responses and evidence are stored under
`artifacts/m5p-d23-greedy-exact-context-20260914`.

The existing production interval 100–190 remains selected because it is the
narrower passing bound. D23 resolves the D20 decoding dependency for the exact
first-segment context only. The next slice must bind greedy decoding into the
production request and run the resumable live Stage 1 workflow; it must not
change the canonical prompt, word validator, archive schema, or offline policy.

## M5-P-D24 greedy production binding

`GenerationRequest` now carries optional `temperature` and `top_p` values, the
llama.cpp adapter forwards them, and Stage 1 segment requests bind greedy
decoding (`temperature=0`, `top_p=1`) into both the request digest and gate
evidence. Focused adapter and Stage 1 tests pass (47 tests); Ruff and strict mypy
pass.

The fresh live workspace `artifacts/m5p-d24-greedy-live-20260914` still exhausted
both attempts on the first GREETING segment below the 20-word minimum. No segment
or downstream artifact was committed and llama.cpp was terminated. Review found
that D23 calibrated the reconstructed full capsule context, while production now
uses the D21 projected capsule context. D23 therefore did not reproduce the
current production prompt byte-for-byte. The next diagnostic must calibrate
greedy decoding against the projected context produced by
`project_stage1_capsule`; no further live workflow run is justified before that
equivalence is tested.

## M5-P-D25 greedy projected-context calibration

The calibration runner now has an explicit `--projected-context` mode that uses
the same `project_stage1_capsule` function as production and records the context
mode in its summary. With `temperature=0` and `top_p=1`, only the 110–210
character range passed all fixed seeds, producing 25/25/25 words. Production's
former 100–190 range produced 18/18/18 words and failed the unchanged 20-word
minimum. Evidence is stored under
`artifacts/m5p-d25-greedy-projected-context-20260914`.

The production bounds are therefore updated to 110–210 and the schema evidence
version is advanced to `M5P-SEGMENT-SCHEMA-1.1`. This is a decoding constraint
change only; the 20–30-word validator, canonical prompt, projection binding and
archive schema are unchanged. The next slice may run the live Stage 1 workflow
with this exact projected context and decoding configuration.

## M5-P-D26 live schema 1.1 run

The live workflow `artifacts/m5p-d26-greedy-schema11-live-20260914` passed the
GREETING word gate and committed eight unique segment checkpoints through
`segment-greeting-003-02.json`. Segment 003-03 then produced byte-identical
responses to earlier committed segments on both attempts. Content-addressed
deduplication correctly reused the existing read-only artifact records, and the
kernel rejected cross-transaction recommit with `RK009_READ_ONLY_MUTATION`.

This is no longer a length-calibration failure. It is a deterministic repetition
failure caused by greedy decoding without a schema-bound segment identity. The
next slice must constrain `item_id` to the requested zone/item/segment identity
and reject duplicate segment text before commit. It must not weaken the artifact
immutability rule or permit the same authoritative bytes to satisfy different
logical segment transactions.

## M5-P-D27 segment identity and duplicate-text gate

The production JSON Schema now constrains both `zone` and `item_id` to the exact
requested zone/item/segment identity. Before registering a candidate, Stage 1
normalizes its text and rejects an exact duplicate of any committed segment in
the same zone. The immutable content-addressed artifact rule remains unchanged.
Test fixtures now emit unique segment text; all 31 Stage 1 integration tests,
Ruff and strict mypy pass.

The next slice should resume the D26 workspace so its eight valid GREETING
checkpoints are reused. If greedy decoding cannot produce a distinct 003-03
segment under the identity-constrained schema within two attempts, decoding
needs a narrowly bounded diversity strategy rather than further archive or
transaction changes.

## M5-P-D28 true recovery and duplicate rejection

The live runner now accepts paired `--workflow-id` and `--stage-id` arguments and
uses `resume_recovery` instead of creating a new workflow in an existing store.
Resuming workflow `a969f983d92046f28de234d0959cf782` correctly reused its eight
committed GREETING checkpoints and retried segment 003-03. Both greedy attempts
were rejected by the duplicate-text gate, confirming the D26 collision was model
repetition rather than a kernel lifecycle defect. llama.cpp was terminated.

The next calibration must test a narrowly bounded nonzero temperature against
the projected context and require both the 20–30-word contract and distinct
outputs across fixed seeds. Only a configuration passing both conditions may
replace the greedy production settings.

## M5-P-D31/D32 exact failing-segment diversity calibration

Calibration now targets an explicit item/segment, rejects text matching committed
predecessors, accepts custom character-bound matrices, and records those results.
For GREETING item 003 segment 03, temperatures 0.3 and 0.4 with 110–210 failed
the three-seed word gate despite resolving duplication. At temperature 0.3,
115–220 yielded 24/25/19 words and failed; 120–230 yielded 24/25/21 words with
three distinct digests and no predecessor duplicate, and is the sole PASS.
Evidence is stored under `artifacts/m5p-d32-temp03-tight-bounds-20260914`.

Production now binds `temperature=0.3`, `top_p=0.9`, bounds 120–230 and schema
evidence version `M5P-SEGMENT-SCHEMA-1.2`. The deterministic 20–30-word and
duplicate-text gates remain authoritative. The next slice should resume D26 and
must commit 003-03 before proceeding.

## M5-P-D33 exact word-budget correction

The live resume exposed that earlier focused calibration used a generic 20–30
word target, while GREETING segments in production receive the exact 29–44
budget derived from the item allocation. The runner now accepts and records an
explicit `--word-bounds` value. At temperature 0.3, 160–300 characters produced
38/46/29 words and 180–340 produced 31/46/33; neither passes all seeds, although
all outputs are distinct from committed predecessors. Evidence is stored under
`artifacts/m5p-d33-exact-word-budget-20260914`.

The next calibration should hold the exact 29–44 contract and reduce sampling
variance (temperature between 0.2 and 0.3) rather than changing transaction or
validator behavior.

## M5-P-D34 reduced-variance exact-budget calibration

With the exact GREETING 29–44 word contract, `temperature=0.25`, `top_p=0.9`
and 180–340 character bounds produced 31/41/32 words across seeds 1710–1712.
All response digests are distinct and none duplicates a committed predecessor.
The narrower 160–300 interval failed at 31/27/26. Evidence is stored under
`artifacts/m5p-d34-temp025-exact-budget-20260914`.

Production now binds temperature 0.25, top-p 0.9, bounds 180–340 and schema
evidence version `M5P-SEGMENT-SCHEMA-1.3`. The next slice should resume D26 and
verify 003-03 under this exact configuration before advancing further.

## M5-P-D35 live retry seed variation

The D34 live resume exceeded the 44-word ceiling. Segment retry previously reused
the same seed, so Stage 1 now advances deterministically to `seed + attempt` and
binds the actual attempt seed into request lineage and gate evidence. All 31 Stage
1 tests, Ruff and strict mypy pass. A subsequent D26 resume still exceeded the
word ceiling on both distinct-seed attempts.

The calibration-to-live mismatch is therefore not caused solely by repeated retry
seeds. Failed pre-validation responses are not currently preserved, preventing
exact comparison of live word counts/digests with calibration. The next slice
must persist bounded diagnostic evidence for rejected responses before any
further decoding change.

## M5-P-D36 rejected-response evidence

Stage 1 now registers each raw local response as a non-authoritative candidate
before semantic validation and records its digest on failed generation calls.
Rejected bytes therefore remain inspectable without bypassing any gate or commit.
All 31 focused Stage 1 tests, Ruff and strict mypy pass.

The D26 diagnostic resume preserved two latest responses for segment 003-03.
They contain 45 and 36 Unicode words respectively. The first exceeds the 29–44
budget; the second is within budget but was rejected as duplicate text. This
explains the retry exhaustion and proves the two failures require distinct repair
feedback rather than another blind global bound change.

## M5-P-D37 bounded retry feedback

Attempt 2 now receives deterministic corrective instruction requiring fresh prose
and the exact active word interval; its adjusted instruction and seed are included
in request lineage. All 31 Stage 1 tests, Ruff and strict mypy pass. The D26 live
resume still exhausted both attempts. Preserved recent responses contain 32 and
36 words, both within the 29–44 interval, indicating duplicate rejection remains
the likely active blocker even though the final exception chain reports an older
over-budget cause.

The next slice must replace the generic `S162_ZONE_GENERATION_FAILURE` with stable
failure codes for under-budget, over-budget and duplicate rejection, and record
the matched predecessor digest. This is required before another model run so the
terminal cause is unambiguous.

## M5-P-D38 stable segment rejection taxonomy

Stage 1 now maps live segment validation failures to stable codes:
`S164_SEGMENT_UNDER_BUDGET`, `S165_SEGMENT_OVER_BUDGET`, and
`S166_SEGMENT_DUPLICATE`. Duplicate termination evidence carries the matched
predecessor SHA-256, while every rejected call retains its own response digest.
The focused suite passes before the live diagnostic. The first diagnostic run
exposed that the budget mapping had initially been inserted on the recovery-read
path rather than the live validation path; the live path is now corrected as
well. A fresh resume is required to collect the first authoritative terminal-code
sample.

## M5-P-D39 live-contract correction

Stable failure codes show the current terminal transaction is
`segment-greeting-004-01.json`, so 003-03 has committed successfully. Both latest
004-01 responses are `S165_SEGMENT_OVER_BUDGET`. Recomputing the YOUTH_SAFE
allocation from code confirms every zone has 300–450 words across five items,
therefore each three-way segment receives 20–30 words. The 29–44 assumption in
D33/D34 came from an integration-test trace and was not the live profile.

The D34 production tuning is reverted. Production again uses the D32 configuration
that was calibrated against the correct 20–30 contract: temperature 0.3, top-p
0.9, bounds 120–230 and `M5P-SEGMENT-SCHEMA-1.2`. No committed artifact is
modified. The next resume should retry 004-01 with the corrected bounds.

## M5-P-D40 persistent retry seed progression

With the corrected live contract, recovery committed the remaining item 004
segments and `segment-greeting-005-01.json`, then stopped at 005-02. Its first
attempt was `S166_SEGMENT_DUPLICATE` and recorded predecessor digest
`825071d1caa5516e754b01afd69e4879ce76f8af62c24c950fbcdffc1a5d1456`;
the corrective second attempt was `S164_SEGMENT_UNDER_BUDGET`.

Recovery previously restarted at the same two logical seeds. Segment seed now
includes the persisted generation-call count for its transaction, so a resumed
retry advances deterministically instead of replaying known rejected bytes. The
next slice should run focused tests and resume 005-02 using the next seed pair.

## M5-P-D29 bounded-diversity projected calibration

The calibration acceptance rule now requires all fixed seeds to pass the word
gate and to produce distinct response digests. With projected production context,
`temperature=0.2`, `top_p=0.9` and 110–210 character bounds produced 24/25/21
words with three distinct digests. It is the only passing bound. Evidence is
stored under `artifacts/m5p-d29-diverse-projected-context-20260914`.

Production Stage 1 now binds this exact decoding pair. The schema, deterministic
20–30-word gate, duplicate-text gate, capsule projection and artifact immutability
remain unchanged. The next slice should resume the original D26 workflow and
verify that segment 003-03 becomes distinct before allowing later checkpoints.

## M5-P-D30 live diversity retry diagnosis

Resuming D26 with the D29 decoding pair still rejected segment 003-03 as a
duplicate. The live trace exposed that `_call_zone_item` varied seed only by the
three segment positions and reused those same seeds for every item. Calibration
diversity across seeds therefore could not affect later items. The deterministic
seed mapping is corrected to include both item and segment position:
`base + (item_index - 1) * 3 + segment_index`. Existing committed checkpoints
remain immutable and recoverable; only uncommitted calls use the corrected seed.

The next slice should run focused Stage 1 tests and resume D26 again. A successful
003-03 commit is required before continuing the remaining GREETING items.

The focused verification passes (31 Stage 1 tests, Ruff and strict mypy), but the
subsequent live resume still produced duplicate text for 003-03 on both attempts
even with its corrected unique seed. Seed identity alone is therefore insufficient
at `temperature=0.2`. The next diagnostic must calibrate the exact failing
item/segment against its eight committed predecessors across a small temperature
matrix and retain the existing word and duplicate gates.
## M5-P-D41 resumable multi-zone progress

The corrected live-contract resume advanced past the full GREETING and OPENING
zones and stopped in INTRODUCTION at `segment-introduction-004-03`. Its two
attempts are classified as `S165_SEGMENT_OVER_BUDGET` and
`S164_SEGMENT_UNDER_BUDGET`. Prior committed checkpoints remain intact; no
duplicate or read-only mutation occurred. The next resume should continue this
INTRODUCTION transaction with persisted seed progression.
## M5-P-D42 resumable progress through INTRODUCTION

The live resume advanced through INTRODUCTION and stopped at
`segment-development-004-01`. Its two attempts are classified as
`S162_ZONE_GENERATION_FAILURE` (incomplete sentence) and
`S165_SEGMENT_OVER_BUDGET` (word ceiling). Earlier committed zones remain intact.
The next resume should continue DEVELOPMENT with the persisted seed progression;
the rejection taxonomy now distinguishes syntax from budget failures.
## M5-P-D43 resumable DEVELOPMENT progress

The next recovery completed DEVELOPMENT item 004 and stopped at
`segment-development-005-01`. Its attempts were classified as
`S165_SEGMENT_OVER_BUDGET` and `S164_SEGMENT_UNDER_BUDGET`. All prior checkpoints
remain authoritative. Continue with the same recovery command and persisted seed
progression; no configuration change is justified while the workflow continues
to advance.
## M5-P-D44 resumable late-zone progress

Recovery advanced through the remaining DEVELOPMENT items and all CLIMAX/FALLING
work until stopping at `segment-ending-004-01`. Both attempts are now classified
as `S164_SEGMENT_UNDER_BUDGET`. The run has therefore traversed most of the
120-segment plan with authoritative checkpoints preserved. Continue resume with
the same configuration; the next useful decision is only after ENDING completes
or repeatedly blocks on the same contract.
## M5-P-D45 final-zone progress

Recovery advanced through ENDING and stopped in FAREWELL at
`segment-farewell-004-02`. The two attempts were classified as
`S165_SEGMENT_OVER_BUDGET` and `S162_ZONE_GENERATION_FAILURE` (incomplete
sentence). All earlier checkpoints remain authoritative. One more resume should
finish the final zone if a valid bounded response is produced.
## M5-P-D46 Stage 1 text completion

The final FAREWELL resume completed all 125/125 production text transactions.
Stage 1 returned `WAITING_DEPENDENCY` with reason
`S144_CHARACTER_REFERENCE_PRODUCTION_REQUIRED`, which is the expected boundary
before character image production. No text transaction remains pending and the
serialize checkpoint is available in the D26 workspace. The next slice is to run
the already validated character-reference/VLM path against this authoritative
Stage 1 package, then perform final materialization and package gates.
## M5-P-D47 character authority on complete Stage 1

The complete 125/125 text package was resumed through character production. The
local ComfyUI + Qwen2.5-VL character transaction passed semantic assessment and
Stage 1 returned `WAITING_DEPENDENCY` with reason
`S147_PRODUCTION_QUALITY_EVIDENCE_REQUIRED`; progress is 126/126 including the
character transaction. Semantic evidence digest is
`e2a579c335186dad1bb6be21870e26b4570bf6a49aafad18a31acb523ae2d862`.
The next slice is the final production-quality assessor/materialization gate.

## M5-P-D48 deterministic verification and remaining gate

The authoritative D26 workspace remains complete at 126/126 transactions: all
125 text checkpoints and the character asset transaction passed. The local
character semantic evidence digest remains
`e2a579c335186dad1bb6be21870e26b4570bf6a49aafad18a31acb523ae2d862`.

Focused Stage 1/character/workflow tests pass (57 passed). The repository-wide
coverage threshold is not meaningful for this focused subset (58.40% and the
configured 85% gate therefore fails); no production failure was observed.
The canonical prompt hash still matches `canonical/prompt.sha256` (case-only
hex normalization).

M5-P cannot be marked complete: `Stage1Service` intentionally stops at
`S147_PRODUCTION_QUALITY_EVIDENCE_REQUIRED` when no independent
`story_quality_assessor` is supplied. The next step is to provide and approve a
local, reproducible assessor implementation/evidence contract, then resume the
same workflow and run the full repository quality gates before publication.

## M5-P-D49 production preflight READY

The fail-closed local preflight now passes when `--comfy-install` points to the
actual entry file `ComfyUI\main.py` (rather than the containing directory).
Both GGUF shards, the llama server, SDXL checkpoint, and loopback ports are
available. No process was launched and no download occurred. The remaining
blocker is therefore solely the independent story-quality assessor contract.

## M5-P-D50 static quality gates

Ruff formatting and lint pass across the repository, and strict mypy passes for
all 68 source files. The only remaining M5-P gate is semantic story-quality
evidence; the workflow remains fail-closed at S147 until that assessor is
supplied.

## M5-P-D51 assessor validation kernel

Added `story_quality_assessor.py`, a fail-closed validator for local assessor
evidence. It enforces the approved score thresholds, exact dimension counts,
PASS status, and script/asset digest bindings. Ruff and strict mypy pass for
the new module. Model invocation and workflow wiring remain the next slice.

## M5-P-D52 production semantic closure

The integrated local llama-server + ComfyUI character-resume run completed the
authoritative D26 workflow at 128/128 transactions. The story-quality assessor
passed the approved thresholds and digest bindings; Stage 1 now returns
`S148_PRODUCTION_PACKAGE_REQUIRED`. M5-P production generation and semantic
quality closure are complete. The remaining action is the normal package
publication step, followed by parent-digest handoff to M7.
