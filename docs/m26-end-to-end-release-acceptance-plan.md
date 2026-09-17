# M26 — End-to-End Release Acceptance

`scripts/validate_release_bundle.py` safely extracts the release ZIP into a temporary
directory, verifies every manifest digest, and executes the bundled clean-machine
smoke with the extracted source on `PYTHONPATH`. The temporary extraction is removed
automatically.

