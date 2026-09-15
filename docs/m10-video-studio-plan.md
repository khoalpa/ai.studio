# M10 Offline Video Studio Plan

M10 consumes one authoritative Stage 4 `VIDEO_PRODUCTION_RELEASE` package and
produces local Video Studio delivery artifacts with a pinned FFmpeg/FFprobe
adapter. It does not modify or replace the Stage 4 archive and never calls an
image, audio or video generator.

The owned outputs are an MP4, `video_quality_report.json` equivalent and a
result manifest. They are delivery artifacts outside `story.zip`; they do not
replace `VIDEO_PROMPT_GATES` or become authoritative package members.

## Slices

- M10-A: strict Stage 4 archive/member/digest intake, exact SRT parsing and
  Stage 4 timing-derived SRT support.
- M10-B: deterministic `AUTO`, `SCENE`, `ZONE` and `FIXED` slideshow planning.
  `AUTO` selects SCENE only with an authoritative valid scene plan, otherwise
  FIXED. Explicit invalid SCENE fails closed.
- M10-C: pinned local FFmpeg/FFprobe subprocess adapter, no shell, bounded
  output, timeout/cancellation cleanup and the system-wide heavy-job lease.
- M10-D: FFprobe postwrite gates for stream count, dimensions, pixel format,
  CFR, duration and audio presence.
- M10-E: same-volume atomic publication of MP4/report/manifest, exact digest
  binding and source archive mutation check.

## Definition of Done

- Stage 4 package, manifest order, member hashes and package digest reopen.
- SRT has one UTF-8, monotonic, positive cue per exact `story.script[]` item and
  ends within 250 ms of the canonical Stage 4 total.
- Timeline has positive contiguous segments, exact oriented package images and
  complete SRT coverage; invalid/gapped SCENE inputs cannot silently degrade.
- FFmpeg and FFprobe executable bytes are pinned for every invocation; command
  arguments never pass through a shell and all inputs are local files.
- Published MP4 has exactly one video stream, optional audio exactly as
  requested, 1920x1080 or 1080x1920, 30 fps CFR, `yuv420p`, and duration within
  250 ms.
- Result manifest binds Stage 4 archive/package, story, video prompts, SRT,
  optional audio, renderer, quality report and MP4 digests.
- Stage 4 archive SHA-256 is unchanged after rendering.
- Ruff, strict mypy and pytest with repository coverage at least 85% pass.

Backup/restore packaging, SBOM, wheelhouse and an air-gapped installer remain
deferred to M11.
