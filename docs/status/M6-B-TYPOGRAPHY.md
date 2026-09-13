# M6-B Production Typography Checkpoint

Status: implementation candidate, review-ready and uncommitted.

The production renderer uses Pillow `11.3.0` with the OS-installed DejaVu Sans
font. The font is 757,076 bytes with SHA-256
`7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954`;
license/provenance is recorded as a project-owner attestation because no local
sidecar license was present.

The renderer validates font path/digest/identity/provenance, enforces safe
margins, writes deterministic PNG bytes and verifies byte-for-byte
repeatability. Rendering `Chuyện kể đêm nay` over the digest-bound ComfyUI base
produced a 1024x1024 PNG with SHA-256
`04ee5c0de3971e2b63c3dd09ac4a5bcd1177ac602b585d9bfae2d58dd8278438`.

The production transaction now binds the expected base-image SHA-256 before
rendering, embeds deterministic `audio_story` provenance metadata, renders
twice to enforce repeatability, persists and reopens the exact bytes, then runs
the PNG structure/dimension/luma QA bundle. A stale base is rejected before an
output file is created. The gate returns immutable evidence for the base,
font, UTF-8 text, final artifact, dimensions and renderer version.

The gate was exercised against the real ComfyUI base SHA-256
`d410df414c32b49f0a59e6e4cc1eb77a800063d1c5780f861bb2234bf4248518`.
The verified 1024x1024 artifact has SHA-256
`c860c596b638161672a8be2aaebe6dc506277c1124f908cf32a95323d3579275`;
its text SHA-256 is
`d2e4c33fb09a305930c97c98e5cc0d8e1f9a076ded2d4dfd92f875a7bcedb771`
and renderer identity is `M6B-PILLOW-1.0`.

Pinned Vietnamese Tesseract rerun exactly returned `Chuyện kể đêm nay` with
confidence `0.9636167525`. The `vie.traineddata` SHA-256 is
`b6b49293d95d0b6dbd8780174627e82c75be957b6f4ed9862155540d6b00bb45`;
request digest is
`f5ee07dde17e4075752babf8db554163bed1c64b15edfa2fd983ff923082b4c9`
and result digest is
`d2e4c33fb09a305930c97c98e5cc0d8e1f9a076ded2d4dfd92f875a7bcedb771`.
`TesseractConfig` now supports a separately pinned TSV config path and digest.
The production rerun used `tessdata_best` directly plus the installed TSV
config SHA-256
`59d079bb75d8b3d7c839a3564580cb559e362c93a9d70f234e421c0c3e767e04`;
no composite directory was required. Exact Vietnamese OCR remained PASS at
confidence `0.9636167525`; the new request digest is
`01790b950cc090a6b227e0b71e65faba3683e309d5ecbaebb887a8f428337519`.

Verification: Ruff format/lint PASS, mypy strict PASS, focused production tests
5/5 PASS, full suite 297 passed and 2 optional skips, total branch coverage
92.63%, canonical prompt SHA-256 PASS, and `git diff --check` PASS.
