# M24 — Clean-Machine Release Validation

`scripts/validate_clean_machine.py` validates the release from an empty temporary
workspace. It checks canonical/UI/FFmpeg prerequisites, bootstraps migrations, runs a
deterministic Stage 1 job, verifies the resulting package, and removes the temporary
workspace unless `--keep-workspace` is explicitly requested.

