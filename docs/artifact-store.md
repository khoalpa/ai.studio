# Artifact Store

The content-addressed store lives below the configured workspace at `artifact_store/sha256/<first-two-hex>/<remaining-hex>`. Paths are derived only from a validated lowercase SHA-256 digest.

Commit writes a uniquely named temporary file under `artifact_store/tmp` on the same workspace volume, flushes and `fsync`s it, verifies same-device placement, then publishes with `os.replace`. The published file is reopened and hashed before the caller may create database metadata. Same bytes deduplicate. Existing content at a digest path must match exactly.

Filesystem publication and SQLite binding cannot be one atomic transaction. The consistency protocol is therefore publish-bytes-first, then bind metadata in one SQLite transaction. A crash between them leaves a safe unbound store object; recovery preserves and reports it. A DB binding whose file is missing or mismatched becomes blocking. Published files are never deleted by the M3 API.

Temporary files are detected on recovery and retained for delayed cleanup. `cleanup_orphan_temps` deletes only explicit `*.tmp` files below the narrow store temp directory and only after the configured age. It never targets the workspace root, home directory or published store.

Windows and WSL2 both use `pathlib`. Atomic replacement requires the temporary file and target directory to report the same device/volume. Network filesystems and cross-volume junction behavior are not guaranteed by M3 and must fail closed.
