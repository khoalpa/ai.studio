"""Sequentially health-check the provisioned local backends without downloads."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path


def wait_json(url: str, timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error = "unreachable"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                value = json.loads(response.read().decode("utf-8"))
            if isinstance(value, dict):
                return value
            last_error = "non-object response"
        except Exception as exc:  # noqa: BLE001 - smoke must report backend failures
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(last_error)


def run_process(command: list[str], health_url: str, timeout: float) -> dict[str, object]:
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        health = wait_json(health_url, timeout)
        return {"status": "PASS", "health": health, "pid": process.pid}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llama-server", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--comfy-main", type=Path, required=True)
    parser.add_argument("--comfy-python", type=Path, required=True)
    parser.add_argument("--llama-port", type=int, default=8080)
    parser.add_argument("--comfy-port", type=int, default=8189)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    result: dict[str, object] = {"execution_policy": "sequential_gpu_only"}
    try:
        result["llama"] = run_process(
            [
                str(args.llama_server),
                "-m",
                str(args.model),
                "--host",
                "127.0.0.1",
                "--port",
                str(args.llama_port),
                "-ngl",
                "99",
            ],
            f"http://127.0.0.1:{args.llama_port}/health",
            args.timeout,
        )
        result["comfy"] = run_process(
            [
                str(args.comfy_python),
                str(args.comfy_main),
                "--listen",
                "127.0.0.1",
                "--port",
                str(args.comfy_port),
            ],
            f"http://127.0.0.1:{args.comfy_port}/system_stats",
            args.timeout,
        )
    except (OSError, RuntimeError) as exc:
        result["status"] = "WAITING_DEPENDENCY"
        result["error"] = str(exc)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 2
    result["status"] = "PASS"
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
