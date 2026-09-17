# Audio Story Offline Runtime

Offline orchestration runtime for the canonical Audio Story v3.16.13 contract.
Milestones M0-M6 provide prompt compilation, deterministic validation, transactional artifact storage, local LLM/image/OCR adapters, Stage 1 packaging and the validated M6 image-production path. Runtime defaults remain offline and local services bind to loopback.

M11 adds digest-bound workspace backup/restore and verifiable offline release bundles without changing the canonical `story.zip` format.

## Install for development

```powershell
py -3.11 -m pip install -e ".[dev]"
```

## Run the diagnostic

```powershell
audio-story doctor
```

The command emits one JSON document and performs only local inspection. Missing optional runtimes are reported as unavailable and do not make the command fail.

## Audio Story Studio

From the repository root, launch the local UI and SQLite-backed API with:

```powershell
.\open_app.bat
```

The launcher uses `artifacts/studio-workspace` by default and opens
`http://127.0.0.1:4173/`. Pass an existing runtime workspace to inspect it:

```powershell
.\open_app.bat D:\path\to\workspace
```

The equivalent CLI command is:

```powershell
audio-story studio --workspace <workspace> --host 127.0.0.1 --port 4173
```

Studio reads workflow, stage, transaction, generation-call, artifact, current gate and event state from `runtime.sqlite3`. Its HTTP API is intentionally
loopback-only. Stage 1 creation is queued through the application service and deterministic local adapter; other authority-changing actions remain disabled
until their stage-specific runners are connected.

Studio API 1.0 exposes:

```text
GET  /api/v1/health
GET  /api/v1/studio
GET  /api/v1/jobs
GET  /api/v1/jobs/{job_id}
POST /api/v1/workflows
POST /api/v1/stage2
POST /api/v1/jobs/{job_id}/cancel
POST /api/v1/jobs/{job_id}/retry
```

Stage 2 supports `MOCK` for deterministic offline verification and `COMFYUI` for the configured loopback production backend. Production image generation
fails closed at `WAITING_SEMANTIC_REVIEW` until exact-pixel semantic evidence is provided; test-only semantic fixtures are never used in ComfyUI mode.

## Backup and restore

```powershell
audio-story backup --workspace <workspace> --output <backup.asbackup>
audio-story restore --backup <backup.asbackup> --workspace <empty-destination>
```

Restore accepts FULL backups and publishes only after archive, database, migration and artifact-integrity checks pass.
# Vận hành nhanh

Xem [Sổ tay vận hành tiếng Việt](docs/operational-runbook-vi.md) và [Release Checklist](docs/release-checklist-vi.md).
