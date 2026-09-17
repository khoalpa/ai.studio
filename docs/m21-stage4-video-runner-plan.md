# M21 — Stage 4 Video Runner

Stage 4 now accepts a PASS Stage 3 package, derives canonical video prompts and SRT,
builds a validated Stage 4 release package, then renders a local MP4 through the
existing FFmpeg/FFprobe adapter. Dependency digests, timeline, dimensions, frame rate,
pixel format, and output bytes are verified before the job is marked PASS.

The Studio endpoint is `POST /api/v1/stage4`; it uses the latest PASS Stage 3 package
when `source_package` is omitted and auto-detects local `ffmpeg`/`ffprobe` binaries.

