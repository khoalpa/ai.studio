# M25 — Release Bundle & Installer

`scripts/build_release_bundle.py` creates a deterministic offline ZIP containing the
Studio source, UI, migrations, scripts, canonical hash, and documentation. Each member
is recorded in `RELEASE_MANIFEST.json`; model weights and GPU binaries are intentionally
excluded. `open_release.bat` delegates to the existing validated local launcher.

