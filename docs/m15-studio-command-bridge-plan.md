# M15 Studio Command Bridge Plan

M15 adds the first authority-preserving write path to Audio Story Studio. The
bounded slice is Stage 1 creation through the existing deterministic runtime.

## Scope

- Validate Stage 1 profile, language, duration, seed, and title before queueing.
- Run one background command at a time with a fresh `WorkflowKernel` connection.
- Execute `Stage1Service` with `DeterministicMockAdapter` and the canonical prompt.
- Expose in-memory job status while all authoritative workflow state remains in
  SQLite and the artifact store.
- Provide create, list, inspect, and queued-job cancellation endpoints.
- Add an accessible UI form and live queue/package feedback.

Resume, retry, and cancellation of an already-running stage remain out of scope
until their workflow-specific cancellation boundaries are available.

## Definition of Done

- A valid UI/API request completes Stage 1 and publishes a verified `story.zip`.
- The resulting workflow survives Studio restart because authority is persisted.
- Invalid requests fail before workflow creation.
- HTTP remains responsive while the background job runs.
- One runner worker serializes local generation commands.
- Repository quality gates pass and the canonical prompt hash is unchanged.
