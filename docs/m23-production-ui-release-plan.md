# M23 — Production UI Hardening & Release Packaging

The Studio now exposes a controlled local `STATE_ONLY` backup action and keeps the
release-readiness gate visible in the Export view. Backups are generated under the
selected workspace with a UUID filename; no user-provided path is accepted. Restore
remains an explicit CLI operation to prevent accidental workspace overwrite.

