# M13 Audio Story Studio UI Plan

M13 adds a presentation-only, offline-capable web surface under `ui/`. It does
not alter the canonical prompt, schemas, package layout, runtime state machine,
or backend authority rules.

## Scope

- A responsive Vietnamese production workspace for the four canonical stages.
- Direct visual mapping for workflow, stage, transaction, artifact, and gate states.
- Validation/recovery details that preserve retry and immutable-artifact semantics.
- Local-service health, queue, package provenance, and activity-log surfaces.
- Static deployment with no cloud runtime dependency or automatic downloads.

## Definition of Done

- The primary workflow, validation center, inspector, search, navigation, and
  responsive mobile layout work without a backend.
- Visible progress is based on committed/current PASS examples only.
- UI source passes static entrypoint, local-reference, and JavaScript syntax checks.
- The repository canonical prompt hash is unchanged.
