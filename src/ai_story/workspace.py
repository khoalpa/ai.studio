from __future__ import annotations

import json
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import WorkflowError
from .models import Profile

RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{7,63}$")


@dataclass(frozen=True)
class RunWorkspace:
    run_id: str
    root: Path
    input_dir: Path
    work_dir: Path
    output_dir: Path
    logs_dir: Path

    @classmethod
    def create(cls, base: Path, profile: Profile, run_id: str | None = None) -> "RunWorkspace":
        value = run_id or f"run-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{secrets.token_hex(4)}"
        if not RUN_ID_PATTERN.fullmatch(value):
            raise WorkflowError("Invalid run ID")
        root = base.resolve() / value
        if root.exists():
            raise WorkflowError(f"Run already exists: {value}")
        paths = [root / name for name in ("input", "work", "output", "logs")]
        for path in paths:
            path.mkdir(parents=True, exist_ok=False)
        workspace = cls(value, root, *paths)
        metadata = {
            "run_id": value,
            "profile": profile.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "INITIALIZED",
        }
        (root / "run.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        workspace.log("RUN_CREATED", {"profile": profile.value})
        return workspace

    @classmethod
    def open(cls, base: Path, run_id: str) -> "RunWorkspace":
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise WorkflowError("Invalid run ID")
        root = base.resolve() / run_id
        paths = [root / name for name in ("input", "work", "output", "logs")]
        if not (root / "run.json").is_file() or not all(path.is_dir() for path in paths):
            raise WorkflowError(f"Run workspace is incomplete: {run_id}")
        return cls(run_id, root, *paths)

    def update_status(self, status: str, **details: Any) -> None:
        path = self.root / "run.json"
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"Cannot update run metadata: {exc}") from exc
        metadata.update(details)
        metadata["status"] = status
        if status != "FAILED":
            metadata.pop("error", None)
        metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)

    def log(self, event: str, payload: dict[str, Any] | None = None) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event": event,
            "payload": payload or {},
        }
        with (self.logs_dir / "events.ndjson").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}
