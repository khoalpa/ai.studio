from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

VOLATILE_KEYS = {
    "archive_path",
    "created_at",
    "duration_ms",
    "finished_at",
    "ledger_digest_sha256",
    "package_digest_sha256",
    "report_digest_sha256",
    "run_id",
    "started_at",
    "timestamp",
    "updated_at",
    "wall_clock_duration_ms",
}
RUN_ID = re.compile(r"run-\d{14}-[0-9a-f]{8}")
ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonicalize(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS and key != "sha256" and not key.endswith("_sha256")
        }
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, str):
        return ISO_TIME.sub("<TIME>", RUN_ID.sub("<RUN_ID>", value)).replace("\\", "/")
    return value


def package_fingerprint(package: Path) -> dict[str, Any]:
    """Hash package semantics after removing known operational metadata."""
    entries: dict[str, str] = {}
    with zipfile.ZipFile(package) as archive:
        for name in sorted(archive.namelist()):
            if name.endswith("/"):
                continue
            payload = archive.read(name)
            if name.endswith(".json"):
                normalized = json.dumps(
                    _canonicalize(json.loads(payload)),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            elif name.endswith((".txt", ".md", ".vtt", ".srt")):
                text = payload.decode("utf-8")
                normalized = ISO_TIME.sub("<TIME>", RUN_ID.sub("<RUN_ID>", text)).encode("utf-8")
            else:
                normalized = payload
            entries[name] = hashlib.sha256(normalized).hexdigest()
    aggregate = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(aggregate).hexdigest(), "entries": entries}
