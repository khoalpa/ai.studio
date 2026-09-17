"""Build a deterministic, offline Audio Story Studio release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import OrderedDict
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "dist" / "audio-story-studio.zip")
    args = parser.parse_args()
    prefixes = ("src/audio_story/", "migrations/", "ui/dist/", "scripts/", "docs/")
    explicit = (
        "open_app.bat",
        "open_release.bat",
        "README.md",
        "pyproject.toml",
        "canonical/prompt.sha256",
        "canonical/ChatGPT_prompt_v3.16.13.txt",
    )
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and (
            (path.relative_to(root).as_posix().startswith(prefixes))
            or path.relative_to(root).as_posix() in explicit
        )
        and not any(part == ".git" or part.startswith(".git") for part in path.parts)
        and not path.relative_to(root).as_posix().startswith("docs/status/")
    )
    records = [
        OrderedDict(
            path=path.relative_to(root).as_posix(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            size_bytes=path.stat().st_size,
        )
        for path in files
    ]
    manifest = OrderedDict(
        schema_version="1.0", bundle_kind="AUDIO_STORY_STUDIO", offline=True, files=records
    )
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for record, path in zip(records, files, strict=True):
            info = zipfile.ZipInfo(record["path"], (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo("RELEASE_MANIFEST.json", (1980, 1, 1, 0, 0, 0))
        info.external_attr = 0o100644 << 16
        archive.writestr(info, manifest_bytes)
    print(
        json.dumps(
            {
                "status": "PASS",
                "path": str(args.output),
                "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                "file_count": len(files),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
