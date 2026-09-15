# ADR-0001: Stage 4 audio default resolution

Status: Accepted for M9 runtime compatibility.

## Context

Canonical v3.16.13 contains `NATIVE_DIALOGUE` in
`VIDEO_PROMPT_DEFAULT_CONFIG`, the runtime self-check and
`VIDEO-AUDIO-PROMPT-01`, while `STAGE4_AUDIO_PROJECTION_REGISTRY_JSON` maps an
absent value to `AMBIENCE_ONLY`. Its registry field counts also predate the
fixed schema 1.2 shapes by one field.

The canonical file remains the byte-for-byte trust root and is not edited.

## Decision

For M9, an absent `video_audio_mode` resolves to `NATIVE_DIALOGUE`. An explicit
canonical enum value always wins. Schema shape is derived from
`VIDEO-PROMPT-SCHEMA-01`: 8 root/23 clip fields for `NATIVE_DIALOGUE`, and 7
root/22 clip fields otherwise. The compiler finding remains visible when
auditing the original prompt; it is not suppressed or reclassified.

## Compatibility

Stage 4 input is an unchanged v3.16.13 Stage 3 package. M9 records the decision
as `created_by_prompt_version=3.16.13+M9-ADR-001`; no inherited member is
rewritten. Explicit `AMBIENCE_ONLY` and `SILENT` continue to serialize their
canonical no-voice projections.
