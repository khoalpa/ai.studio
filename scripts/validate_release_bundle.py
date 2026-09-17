"""Accept a release ZIP by extracting it safely and running the clean-machine smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bundle", type=Path, default=root / "dist" / "audio-story-studio.zip", nargs="?"
    )
    args = parser.parse_args()
    bundle = args.bundle.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="audio-story-release-acceptance-") as temp:
        target = Path(temp)
        with zipfile.ZipFile(bundle) as archive:
            names = archive.namelist()
            if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                raise RuntimeError("unsafe archive member")
            archive.extractall(target)
        manifest = json.loads((target / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        for record in manifest["files"]:
            path = target / record["path"]
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]
            ):
                raise RuntimeError(f"manifest mismatch: {record['path']}")
        env = {"PYTHONPATH": str(target / "src")}
        import os

        result = subprocess.run(
            [sys.executable, str(target / "scripts" / "validate_clean_machine.py")],
            cwd=target,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(result.stdout, end="")
            print(result.stderr, end="")
            return result.returncode
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "bundle": str(bundle),
                    "manifest_files": len(manifest["files"]),
                    "clean_machine": "PASS",
                }
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
