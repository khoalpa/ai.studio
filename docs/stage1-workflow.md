# Stage 1 workflow (M5)

`Stage1Service` is the small M5 application API. It resolves exactly one profile, compiles an
M1 `STAGE1/CREATE` capsule, persists the workflow/stage in the M3 kernel and requires explicit
duration confirmation before opening an M4 generation call.

The bounded call chain is `plan -> draft -> review -> repair -> serialize`. Each phase owns one
logical asset transaction; retry retains that transaction and creates a new generation-call ID.
Only request/response digests and adapter metadata enter persistence. The canonical prompt and
response bodies are not logged.

The explicit deterministic test route then freezes a story, creates test-only character PNGs,
validates `story.json` and `story_validation.json`, builds the manifest and deterministic ZIP,
safe-extracts it, reopens every member, records `STAGE1_PACKAGE_GATE`, and commits the archive via
the M3 artifact store. Production mode stops at `WAITING_DEPENDENCY` until M6 supplies real
character references.

Run the deterministic integration path:

```powershell
audio-story stage1-mock --workspace .runtime-test --profile YOUTH_SAFE --duration 12 --seed 7
```

The command is explicitly a mock/test path. Its character images must not be presented as
production-quality assets.

## Recovery boundaries

M3 recovery remains authoritative. Each generation phase now commits a digest-bound checkpoint;
`resume_recovery` opens the database and artifact store through a fresh kernel instance, reconciles
interrupted calls/transactions and skips already committed phase work. A fault seam is available
only to tests and covers every phase plus story/report/manifest/ZIP publication and binding.
Repeated recovery is idempotent and records `RESUME_STARTED`/`RESUME_COMPLETED` in the append-only
event log. A failed or exhausted call never creates a committed artifact or false progress.
