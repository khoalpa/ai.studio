# M6 ComfyUI Local Validation Plan

## Purpose and boundary

This document is the implementation and evidence plan for the ComfyUI slice of
M6-B. It does not authorize downloading models, workflows, custom nodes or
fonts, starting a backend, using a cloud endpoint, or beginning M7. The
runtime remains offline and the endpoint must bind to `127.0.0.1`.

The existing `ComfyUIImageAdapter` is a transport contract with mocked tests.
Those tests demonstrate deterministic rejection behavior, but do not promote
the production environment to `PASS`.

## Required local inputs

Before implementation or smoke execution, record these exact local inputs in an
environment evidence file outside the canonical prompt:

Use `docs/m6-comfyui-evidence.json` as the environment evidence record. A blank
or synthetic value keeps the evidence `NOT_VERIFIED`.

- ComfyUI version, executable/install path and launch arguments.
- Explicit loopback host and configured port.
- Workflow JSON path and SHA-256, including the output node contract.
- Checkpoint/model path, SHA-256 and license/provenance.
- Every custom-node package/version/path and SHA-256, if used.
- Python/runtime identity and relevant CUDA/driver identity.

Missing or unlocked inputs keep the item `BLOCKED` or `NOT_VERIFIED`; a mock
response cannot substitute for them.

## Implementation slices

1. Add a no-download offline launch profile that rejects non-loopback bindings,
   network/model-install flags and missing registered inputs.
2. Add a digest-bound workflow fixture and typed request builder. The builder
   must bind transaction ID, generation-call ID, seed, canvas, workflow digest
   and output cardinality.
3. Extend the local smoke harness for `/system_stats` or health, `/prompt`,
   `/history/{prompt_id}` and `/view`, with bounded polling and cancellation.
4. Reopen the returned PNG and run the existing deterministic PNG QA before
   accepting the image transaction. Record the exact output digest and bytes.
5. Add fault tests for redirect, timeout, cancellation, malformed/truncated/
   empty/fan-out output, non-zero/crashed backend and semaphore/unload paths.

No production claim is made until the smoke harness runs against the explicitly
provisioned local backend and all evidence is digest-bound.

The reviewed launch profile is `scripts/run_comfyui_offline.ps1`. It pins
loopback port 8188, the registered model-path configuration, disables custom
nodes/API nodes/Manager UI and enables deterministic mode. The script does not
download or install anything.

## Definition of Done for the ComfyUI slice

- All required local inputs are present, versioned and digest recorded.
- The backend binds only to loopback and performs no network access or
  automatic download.
- Health/capability/model probes pass with the registered inputs.
- One request produces exactly one expected image and a reproducible output
  digest for the locked fixture.
- PNG QA, transaction binding, recovery and cancellation checks pass.
- The smoke evidence and deterministic test results are recorded in
  `docs/status/M6-B-COMFYUI.md`.

Current status: `PASS`. The reviewed production evidence, exact dependency
digests, live generation/cancellation results and deterministic fault matrix
are recorded in `docs/status/M6-B-COMFYUI.md`.
