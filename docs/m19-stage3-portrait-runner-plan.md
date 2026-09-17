# M19 — Stage 3 Portrait Runner

Stage 3 now consumes a validated Stage 2 package, builds the existing deterministic
portrait adaptation plan, executes the pilot-first queue, validates each 1080x1920 PNG
through the existing transaction kernel, and writes the existing compatible final
`story.zip` layout.

The Studio endpoint is `POST /api/v1/stage3`; it accepts an optional `source_package`
inside the active workspace and otherwise selects the latest PASS Stage 2 package. The
execution mode is `VLM_LOCAL` by default, with `MOCK` retained for deterministic tests.
