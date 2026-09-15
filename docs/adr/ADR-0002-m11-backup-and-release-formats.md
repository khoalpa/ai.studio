# ADR-0002: M11 Backup and Offline Release Formats

Status: Accepted for M11.

## Context

SQLite runs in WAL mode and cannot be backed up safely by copying only the main
database file. The artifact store and published package paths are separate from
SQLite. Air-gapped installation also requires a verifiable dependency set that
does not contact package indexes.

## Decision

- Workspace backups use schema `1.0` and are separate from canonical
  `story.zip` packages.
- SQLite is captured with its online Backup API. WAL and SHM files are never
  archive members.
- `FULL` contains the database, every file referenced by `artifacts` or a
  published image-package path, and regular published files below the
  runtime-owned `outputs/` tree. Pending files and symlinks are excluded or
  rejected. `STATE_ONLY` is archival state and cannot be restored standalone.
- Every member is bound by path, size and SHA-256. The canonical prompt digest,
  migration checksums and a digest of the sorted member ledger are mandatory.
- Restore accepts only `FULL`, stages on the destination volume, validates the
  complete database/file closure, and publishes only to an absent or empty
  destination.
- Release bundles contain wheels, a hash-locked requirement file, CycloneDX
  SBOM, standard-library verifier and PowerShell installer. Installation uses
  `pip --no-index --require-hashes`.
- External executables and models are inventory entries, not automatically
  downloaded payloads. Their distribution remains subject to license review.

## Compatibility

Unknown backup or release schema versions fail closed. Migration authority in a
backup must exactly equal the runtime migration files. A future format requires
a new ADR and explicit compatibility adapter. This decision does not modify the
v3.16.13 `story.zip` layout.
