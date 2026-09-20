"""Process-owned workspace lock for the local Studio runtime."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class StudioInstanceLockError(RuntimeError):
    pass


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@dataclass(slots=True)
class StudioInstanceLock:
    path: Path
    token: str

    @classmethod
    def acquire(cls, workspace: Path) -> StudioInstanceLock:
        root = workspace.resolve()
        root.mkdir(parents=True, exist_ok=True)
        path = root / ".audio-story-studio.lock"
        token = uuid.uuid4().hex
        payload = {
            "schema_version": "1.0",
            "pid": os.getpid(),
            "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "workspace": str(root),
            "token": token,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        for _ in range(2):
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                    owner_pid = int(current["pid"])
                except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise StudioInstanceLockError(f"UI014_WORKSPACE_LOCK_INVALID: {path}") from exc
                if _pid_is_alive(owner_pid):
                    raise StudioInstanceLockError(
                        f"UI015_WORKSPACE_ALREADY_OPEN: PID {owner_pid} owns {root}"
                    ) from None
                with suppress(FileNotFoundError):
                    path.unlink()
                continue
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return cls(path, token)
        raise StudioInstanceLockError(f"UI016_WORKSPACE_LOCK_RACE: {root}")

    def release(self) -> None:
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if current.get("token") == self.token:
            with suppress(FileNotFoundError):
                self.path.unlink()
