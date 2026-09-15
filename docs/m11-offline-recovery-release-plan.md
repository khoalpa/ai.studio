# M11 Offline Recovery and Release Plan

M11 provides deterministic workspace backup/restore and a verifiable offline
Python release bundle. Runtime behavior remains offline; no cloud fallback,
credentials or automatic dependency/model download is introduced.

## Slices

- M11-A: freeze backup/release schema 1.0 in ADR-0002.
- M11-B: online SQLite snapshot, referenced-file closure, canonical manifest,
  deterministic ZIP and atomic publication.
- M11-C: secure extraction, migration/database/artifact reconciliation and
  staged restore into an absent or empty destination.
- M11-D: pre-provisioned wheelhouse packaging, hash lock, CycloneDX SBOM,
  external-runtime inventory, standard-library verifier and offline installer.
- M11-E: fault tests, production backup/restore evidence and complete quality
  gates.

## Commands

```powershell
audio-story backup --workspace <workspace> --output <file.asbackup>
audio-story restore --backup <file.asbackup> --workspace <empty-destination>
python scripts/build_m11_release.py --wheelhouse <wheels> --output <bundle>
```

The release builder never resolves dependencies. Wheels must be provisioned and
reviewed before it runs. The generated installer verifies the bundle, then uses
only its local wheelhouse with `--no-index` and `--require-hashes`.

## Definition of Done

- A live WAL workspace produces a consistent backup without copying WAL/SHM.
- Two backups of unchanged logical state are byte-identical.
- FULL restore reproduces the SQLite state and every referenced artifact hash.
- Corruption, unsafe archives, incompatible migrations, incomplete closure and
  occupied destinations fail before publication.
- The release manifest binds every payload; the lock pins every wheel hash and
  the SBOM records all Python components.
- An empty environment installs from the bundle with network access disabled.
- Canonical bytes and Stage 4 package layout are unchanged.
- Ruff format/lint, strict mypy and pytest with branch coverage at least 85% pass.
