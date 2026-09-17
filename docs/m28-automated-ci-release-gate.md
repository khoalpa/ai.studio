# M28 — Automated CI Release Gate

`.github/workflows/release-gate.yml` runs the canonical hash check, Ruff, mypy, full
pytest with coverage, deterministic bundle build, and clean-machine acceptance on
Python 3.11 and 3.12. Ubuntu installs only the system FFmpeg dependency needed by
the clean-machine smoke. No model weights are downloaded and no GPU/VLM job runs in CI.

