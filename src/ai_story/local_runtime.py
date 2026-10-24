from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from .errors import RuntimeUnavailableError


class LlamaServerSupervisor:
    """Starts one workspace-local llama.cpp server on demand and reuses it."""

    _lock = threading.Lock()

    def __init__(self, runtime_root: Path, endpoint: str = "http://127.0.0.1:8080") -> None:
        self.runtime_root = runtime_root.resolve()
        self.endpoint = endpoint.rstrip("/")
        self.state_path = self.runtime_root / ".models" / "llama-server.json"
        self.log_path = self.runtime_root / ".models" / "llama-server.log"

    def ensure(
        self, model: dict[str, Any], timeout_seconds: float = 90, *, force_restart: bool = False
    ) -> dict[str, Any]:
        if force_restart:
            with self._lock:
                self._stop_managed_server(timeout_seconds=min(15.0, timeout_seconds))
        if self._healthy() and self._state_matches(model):
            return {"status": "READY", "started": False, "endpoint": self.endpoint}
        model_path = Path(str(model.get("path") or "")).expanduser().resolve()
        if not model_path.is_file():
            raise RuntimeUnavailableError(
                "Model viết truyện chưa có file GGUF hợp lệ; hãy kiểm tra Model local."
            )
        with self._lock:
            if self._healthy() and self._state_matches(model):
                return {"status": "READY", "started": False, "endpoint": self.endpoint}
            if self._healthy():
                self._stop_managed_server(timeout_seconds=min(15.0, timeout_seconds))
            executable = shutil.which("llama-server") or shutil.which("llama-server.exe")
            if not executable:
                raise RuntimeUnavailableError(
                    "Không tìm thấy llama-server. Hãy cài llama.cpp hoặc thêm llama-server.exe vào PATH."
                )
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            log = self.log_path.open("ab")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                [executable, "-m", str(model_path), "--host", "127.0.0.1", "--port", "8080", "-c", "16384", "--n-gpu-layers", "32", "--parallel", "1"],
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                creationflags=flags,
            )
            self.state_path.write_text(json.dumps({
                "pid": process.pid, "model_id": model.get("id"), "model_path": str(model_path),
                "endpoint": self.endpoint, "log_path": str(self.log_path),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.close()
                    raise RuntimeUnavailableError(
                        f"llama.cpp dừng khi khởi động (exit {process.returncode}); xem log: {self.log_path}"
                    )
                if self._healthy():
                    log.close()
                    return {"status": "READY", "started": True, "pid": process.pid, "endpoint": self.endpoint}
                time.sleep(0.5)
            log.close()
            process.terminate()
            raise RuntimeUnavailableError(
                f"llama.cpp chưa sẵn sàng sau {timeout_seconds:g}s; xem log: {self.log_path}"
            )

    def _state_matches(self, model: dict[str, Any]) -> bool:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        requested_path = str(Path(str(model.get("path") or "")).expanduser().resolve())
        state_path = str(Path(str(state.get("model_path") or "")).expanduser().resolve())
        return bool(requested_path) and (
            state.get("model_id") == model.get("id") and state_path == requested_path
        )

    def _stop_managed_server(self, timeout_seconds: float) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            pid = int(state["pid"])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeUnavailableError(
                "Cổng llama.cpp đang được dùng bởi process không do workspace quản lý; "
                "không thể chuyển model an toàn."
            ) from exc
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise RuntimeUnavailableError(
                f"Không thể dừng llama.cpp process {pid} để chuyển model: {exc}"
            ) from exc
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not self._healthy():
                self.state_path.unlink(missing_ok=True)
                return
            time.sleep(0.25)
        raise RuntimeUnavailableError(
            f"llama.cpp process {pid} chưa dừng; không thể chuyển model an toàn."
        )

    def _healthy(self) -> bool:
        try:
            with urllib.request.urlopen(self.endpoint + "/health", timeout=1.5) as response:
                return response.status == 200
        except Exception:
            return False
