# M9 Stage 4 Canonical Video Prompt Package Plan

M9 accepts one authoritative Stage 3 `story.zip`, derives a deterministic
sentence-bound timeline and provider-neutral `video_prompts.json` schema 1.2,
then publishes a Stage 4 `story.zip` for `VIDEO_PRODUCTION_RELEASE`.

M9 owns only `video_prompts.json`, the new workflow manifest and archive
container. It never calls an image, audio or video generator and retains every
Stage 3 non-manifest member byte-for-byte. Static references are restricted to
the exact character reference set.

Implementation slices are M9-0 canonical decision, M9-A source intake, M9-B
configuration/timeline, M9-C scene/reference/voice/continuity planning, M9-D
schema and gates, and M9-E deterministic packaging and postwrite verification.

Production FULL_STORY execution must pause when the deterministic projection
exceeds 120 clips and resume only after the user selects the canonical coverage
option.
