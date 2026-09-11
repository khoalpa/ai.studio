# Deterministic Validator

## Purpose

`validate_story_runtime.py` validates reproducible byte and structure properties. It does not assess narrative quality, identity, anatomy, visual coherence, OCR, typography, safety semantics, or any other model-dependent property.

## CLI

```powershell
audio-story-validate story.json `
  --stage STAGE1 `
  --profile YOUTH_SAFE `
  --route CREATE `
  --phase INPUT `
  --canonical-prompt-sha256 4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27 `
  --capsule-digest <64-hex-digest> `
  --output deterministic_validation_result.json
```

The command prints one JSON result. Exit code 0 means deterministic execution completed with `PASS` or explicit `NOT_VERIFIED`; exit code 1 means `FAIL`. `NOT_VERIFIED` is always represented in the result, never encoded only in the process exit code.

## Python API

```python
from pathlib import Path

from audio_story.validation import ValidationRequest, validate

result = validate(
    ValidationRequest(
        stage="STAGE1",
        profile="YOUTH_SAFE",
        route="CREATE",
        phase="INPUT",
        artifact_path=Path("story.json"),
        canonical_prompt_sha256="<sha256>",
        capsule_digest="<sha256>",
        output_path=Path("deterministic_validation_result.json"),
    )
)
```

Resource limits can be overridden by passing a local `ValidationLimits` instance. Defaults bound JSON bytes/depth, PNG pixels, ZIP member count, member/total bytes, compression ratio, and streaming copy chunk size.

## Stable error codes

| Prefix | Area | Representative codes |
| --- | --- | --- |
| `DJ` | Strict JSON and order | `DJ002_UTF8_BOM`, `DJ004_DUPLICATE_KEY`, `DJ005_NFC_DUPLICATE_KEY`, `DJ008_TRAILING_DATA`, `DJ012_FIELD_ORDER` |
| `DS` | Schema registry | `DS001_UNKNOWN_SCHEMA`, `DS002_UNSUPPORTED_PHASE`, `DS004_SCHEMA_VERSION` |
| `DF` | File set | `DF001_DUPLICATE_NORMALIZED_PATH`, `DF003_MISSING_FILE`, `DF004_FORBIDDEN_FILE`, `DF005_FILE_COUNT` |
| `DP` | PNG | `DP001_PNG_SIGNATURE`, `DP003_PNG_CRC`, `DP007_PNG_METADATA`, `DP009_PNG_DIMENSIONS`, `DP010_PNG_METADATA_MISSING` |
| `DZ` | ZIP security | `DZ003_DUPLICATE_PATH`, `DZ004_NON_REGULAR_MEMBER`, `DZ009_CRC_ERROR`, `DZ011_UNSAFE_PATH` |
| `DV` | Validator runtime/result | `DV001_IO_ERROR`, `DV002_RESULT_REOPEN_MISMATCH` |

Every failure includes `artifact_path`, detector class `DETERMINISTIC`, and JSON or byte/line/column locators where the parser can determine them.

## Rule status

| Rule family | Status |
| --- | --- |
| Strict UTF-8 JSON, duplicates, NFC, finite numbers, trailing data, size/depth | IMPLEMENTED |
| Independent exact object field order | IMPLEMENTED |
| Canonical internal JSON and SHA-256 | IMPLEMENTED |
| Generic exact file-set/path/count contracts | IMPLEMENTED |
| Basic PNG signature/chunks/CRC/decode/dimensions/color type/hash/JSON `tEXt` metadata | IMPLEMENTED |
| ZIP path/type/encryption/CRC/size/count/ratio inspection and guarded extraction | IMPLEMENTED |
| `deterministic_validation_result.json` schema, digest projection and reopen | IMPLEMENTED |
| Full semantic schemas for story/visual/video/package artifacts | NOT_VERIFIED |
| Manifest owner-stage and mutation-status semantics | NOT_IMPLEMENTED pending M3 ownership model |
| Hard-link recognition when ZIP metadata is indistinguishable from a regular file | NOT_VERIFIED platform limitation |
| OCR, identity, anatomy, coherence, typography and semantic/model assessment | NOT_APPLICABLE to M2 |

The eight vertical-slice artifact schemas are registered with canonical versions and supported phases, but remain `NOT_VERIFIED` beyond deterministic `schema_version` checks until their exact executable field contracts are introduced. The result schema is fully implemented.

## Adding a schema or rule

1. Add or update a typed `SchemaSpec` in `schemas.py`; do not infer missing fields from examples.
2. Add an explicit field-order tuple wherever the canonical contract mandates order.
3. Implement the rule in the narrow module (`strict_json`, `files`, `images`, or `archives`) and allocate a stable error code.
4. Add one valid fixture and at least three invalid fixtures covering distinct invariants.
5. Add the ordered check to the validator result and bind its evidence digest.
6. Run all repository quality gates and update the milestone status.

## Archive extraction threat model

Untrusted ZIPs may attempt traversal, absolute/drive/UNC paths, normalized-name collisions, links, special files, encryption, CRC corruption, oversized expansion, or extreme compression ratios. Inspection occurs before extraction. Extraction uses a new temporary root, writes members individually without `extractall()`, verifies the resolved target remains below the root, streams bounded chunks, and checks each output with `lstat`. The temporary root is removed after an extraction failure. Platform APIs cannot always distinguish a hard link encoded as an ordinary regular entry; that case remains `NOT_VERIFIED` rather than PASS.
