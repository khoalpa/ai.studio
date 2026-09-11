# Stage 1 artifact contracts

M5 implements the CURRENT Stage 1 roots required by canonical v3.16.13:

- `story.json` schema `2.3`, ordered root `schema_version, meta, characters, outline, script`.
- `story_validation.json` schema `2.3` with the exact 15-field ordered root.
- `workflow_manifest.json` schema `1.0` with the exact 13-field ordered root and ordered five-field
  file records.
- `story.zip` order: manifest, story, validation report, then character PNGs in story character
  order, followed by `series_anchor.json` only for `SERIAL_DETECTIVE`.
- `series_anchor.json` uses current schema `3.2.0`, the canonical six-field root order, and binds
  series/profile/episode and the exact story character set. Its strict parse and cross-file gate
  run again on extracted bytes.

Serialization is UTF-8/NFC without BOM. Strict JSON rejects duplicate keys, non-finite numbers
and trailing data. Story content, final script, character set, artifact and package digests are
recomputed from exact bytes or canonical projections. ZIP timestamps, permissions and member
order are fixed, so equal mock inputs produce equal member and container bytes.

## Stable M5 errors

| Code | Meaning |
| --- | --- |
| `S101_MISSING_PROFILE` | Active profile is absent |
| `S102_INVALID_PROFILE` | Profile is not canonical |
| `S103_CONFLICTING_PROFILE` | More than one profile was supplied |
| `S104_INVALID_LANGUAGE` | Language is not `vi` or `en` |
| `S105_DURATION_CONFIRMATION_REQUIRED` | User confirmation is missing |
| `S106_CAPSULE_BINDING` | Resume capsule no longer matches |
| `S107_DURATION_RANGE` | Confirmed duration is outside the profile range |
| `S110_GENERATION_FAILURE` | A local generation attempt failed |
| `S111_RETRY_EXHAUSTED` | Bounded phase attempts were exhausted |
| `S120_STORY_SCHEMA` | Story shape/type/version is invalid |
| `S121_PROFILE_MISMATCH` | Story/resume profile binding differs |
| `S123_INTERNAL_FIELD_LEAK` | Internal planning text leaked publicly |
| `S124_ZONE_ORDER` | Script zone set/order is invalid |
| `S125_SCRIPT_COUNT` | Script item minimum is not met |
| `S126_DURATION_WPM` | Word count and WPM duration do not reconcile |
| `S127_CHARACTER_BINDING` | Character ID/path/reference binding is invalid |
| `S128_INCOMPLETE_SENTENCE` | Script item is incomplete |
| `S129_PARSEBACK_DIGEST` | Final-script digest differs after parse-back |
| `S130_REPORT_ROOT` | Validation-report root/version is invalid |
| `S131_REPORT_BINDING` | Report story/content digest is stale or wrong |
| `S132_REPORT_EVIDENCE` | Required report evidence is absent |
| `S133_REPORT_NOT_VERIFIED` | A blocker gate is not PASS |
| `S134_DIALOGUE_VOICE` | Direct speech uses a non-canonical or narrator voice |
| `S135_DIALOGUE_AMBIGUITY` | Same-voice owner switch is ambiguous in serialized audio |
| `S140_MANIFEST_SCHEMA` | Manifest root/stage/parent contract is invalid |
| `S141_MANIFEST_FILE_SET` | Manifest allowlist/order/count is invalid |
| `S142_MANIFEST_DIGEST` | Declared member size/digest differs |
| `S143_TEST_ASSET_PRODUCTION_PATH` | Test-only reference requested in production |
| `S144_ANCHOR_SCHEMA` | Series anchor root/version is invalid |
| `S145_ANCHOR_BINDING` | Series/profile/episode binding differs from story |
| `S146_ANCHOR_CHARACTER` | Anchor character state differs from story |
| `S147_ANCHOR_APPLICABILITY` | Required anchor is absent, extra or out of order |
| `S148_ANCHOR_CONTINUITY` | Anchor revision/episode/case-arc state is invalid |
| `S150_PACKAGE_REOPEN` | Post-package extraction/reopen failed |
| `S160_RECOVERY_CONFLICT` | Resume state conflicts with persisted state |

All errors include a JSON/path/phase locator. Existing `DJ`, `DS`, `DF`, `DZ`, `LLM` and `RK`
codes retain their meanings.
