# M6-B Checkpoint 3 ComfyUI Plan

Status: implementation candidate. No backend was started, no model or workflow was
downloaded, and no cloud service was used.

The implementation/evidence plan is in `docs/m6-comfyui-plan.md`. Production
ComfyUI remains `BLOCKED` until the local launch profile, loopback binding,
workflow, model/custom-node provenance and digest-bound fixture are supplied.
M7 remains out of scope.

The required evidence record is `docs/m6-comfyui-evidence.json`.
The local ComfyUI Desktop installation, executable and SDXL checkpoint are now
recorded there. The checkpoint is 6,938,078,334 bytes with SHA-256
`31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b`.
License and approved workflow fixture are still missing, so the record remains
`NOT_VERIFIED`. A local API workflow has now been created at
`comfy_workflows/sdxl_txt2img_api.json`; it is valid JSON, 1,418 bytes, and has
SHA-256 `3cbc96f829464b7a40a03b31f4f9a673efb6a5c04dce42a66e572dc351bd28fe`.
It still requires validation against the installed ComfyUI node set and a
confirmed checkpoint license before production smoke.

Static compatibility check: PASS. All seven node types resolve in the local
ComfyUI source (`CheckpointLoaderSimple`, `CLIPTextEncode`,
`EmptyLatentImage`, `KSampler`, `VAEDecode` and `SaveImage`), the referenced
checkpoint basename exists, and the workflow contains no URL or download
directive. Runtime smoke remains blocked by missing license confirmation and
an approved output fixture.

Implemented the fail-closed `ComfyUIProvenance` contract and focused negative
tests. It verifies loopback HTTP, non-empty version/license, workflow/model
existence and exact SHA-256 before producing offline launch arguments. Using
the bundled Python 3.12.14 toolchain: Ruff format/lint PASS, mypy strict PASS,
full pytest PASS (`280 passed, 2 skipped`, 93.32% branch coverage), and
`git diff --check` PASS.

Baseline carried forward from M6-B:

- Ruff format/lint: PASS.
- mypy strict: PASS.
- Full pytest: PASS, with only the documented optional skips.
- Canonical prompt SHA-256/read-only: PASS.
- Tesseract production smoke: `NOT_VERIFIED` pending approved fixture.
- Typography/font production evidence: `NOT_VERIFIED`.

Next authorized action is to implement the offline launch/profile validation
and evidence schema only after the local dependency inputs are explicitly
available. The canonical prompt remains untouched.

Checkpoint provenance scan found no sidecar license or model card. The project
owner has now supplied a user attestation confirming the checkpoint's
license/provenance; this is recorded as an internal evidence assertion and is
not an independent legal determination.

Static local inspection also identified ComfyUI version `0.20.1` and two
installed custom-node directories (`ComfyUI_IPAdapter_plus` and `glm_prompt`).
The current workflow does not reference either custom node.

Offline launch profile added at `scripts/run_comfyui_offline.ps1`; static
review confirms it pins `127.0.0.1:8188`, uses the recorded model-path config,
disables custom/API/Manager features and enables deterministic mode. It has
been executed, but startup failed before binding. The latest log reports
PyTorch `2.5.1+cu121` incompatibility with the installed `comfy-kitchen` custom
operator schema (`kernel_size: list[int]`), so `127.0.0.1:8188` remained
unreachable. No workflow was submitted by this run. Runtime inventory confirms
Python `3.10.6`, `comfy-kitchen 0.2.33` and `comfy-aimdo 0.2.14`; no local
torch/kitchen/triton wheel cache was found for an offline repair.

Model-path check: PASS for local discovery configuration. ComfyUI Desktop's
`extra_models_config.yaml` maps its default model base path to
`D:\Documents\ComfyUI`, which contains the recorded checkpoint. Two existing
UI workflows were found under the ComfyUI user profile, but they are not yet
approved API fixtures for this project.

Production smoke passed on the second managed runtime: ComfyUI `0.35.1`,
Python `3.13.12`, PyTorch `2.12.1+cu130`, CUDA available and `comfy-kitchen
0.2.33`. It bound only to `127.0.0.1:8188`; `/system_stats` returned HTTP 200.
The digest-bound workflow completed with prompt ID
`634b0c19-ddc4-42c5-b330-481f9100a361` and exactly one `/view` output. The
reopened PNG is 1,525,311 bytes, 1024x1024, has the required PNG signature and
SHA-256 `d410df414c32b49f0a59e6e4cc1eb77a800063d1c5780f861bb2234bf4248518`.

`ComfyUIImageAdapter` now supports the production API sequence when configured
with a digest-bound workflow path: `/prompt`, bounded `/history/{prompt_id}`
polling and `/view`. It rewrites only seed, canvas, batch size and output prefix,
rejects workflow drift, malformed prompt IDs, timeout, cancellation and output
fan-out. A live adapter call passed with one 1024x1024 PNG. Ruff and mypy pass;
the full suite passes with 282 tests and 2 optional skips at 91.68% branch
coverage. The newly added production branch is currently at 55% unit coverage
and needs a focused mocked fault matrix before checkpoint closure.

The focused mocked API matrix now covers successful prompt/history/view,
workflow digest drift, malformed prompt ID, empty output and image fan-out.
Focused tests pass (20/20); full suite passes with 288 tests and 2 optional
skips at 92.82% branch coverage. `comfyui.py` branch coverage increased from
55% to 86%; Ruff and mypy remain PASS.

Cancellation now records active prompt IDs and sends a bounded best-effort
`/interrupt`; local cancellation remains authoritative if the interrupt call
fails. Malformed history has stable code `IMG015_HISTORY_INVALID`. The focused
API suite passes 8/8 and the full suite passes 290 tests with 2 optional skips;
total branch coverage is 92.98% and `comfyui.py` is 87%. Ruff, mypy and
`git diff --check` pass.

Final live verification is PASS. A production adapter request completed in
8,827 ms with exactly one 1024x1024 PNG (1,566,359 bytes, SHA-256
`2f032f93b0f18f3bc07e1c01737de2baf41ccc01bec1c25eab843760d866db8b`).
A second request was cancelled after its real prompt ID was captured;
`/interrupt` completed, the worker stopped, and the adapter returned
`IMG004_CANCELLED` without accepting an image. The ComfyUI slice is ready for
review; this does not promote the still-unverified OCR/typography production
items or authorize M7.
