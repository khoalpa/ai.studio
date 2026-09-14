"""Fail-closed preflight for the M5-P local production runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llama-server", type=Path, required=True)
    parser.add_argument("--gguf-shard", action="append", type=Path, required=True)
    parser.add_argument("--comfy-install", type=Path, required=True)
    parser.add_argument("--comfy-model", type=Path, required=True)
    parser.add_argument("--llama-port", type=int, default=8080)
    parser.add_argument("--comfy-port", type=int, default=8189)
    args = parser.parse_args()

    checks = {
        "llama_server_exists": args.llama_server.is_file(),
        "gguf_shards_exist": all(path.is_file() for path in args.gguf_shard),
        "comfy_install_exists": args.comfy_install.is_file(),
        "comfy_model_exists": args.comfy_model.is_file(),
        "llama_loopback_port_free": port_free(args.llama_port),
        "comfy_loopback_port_free": port_free(args.comfy_port),
    }
    evidence = {
        "status": "READY" if all(checks.values()) else "WAITING_DEPENDENCY",
        "checks": checks,
        "paths": {
            "llama_server": str(args.llama_server),
            "gguf_shards": [str(path) for path in args.gguf_shard],
            "comfy_install": str(args.comfy_install),
            "comfy_model": str(args.comfy_model),
        },
        "sha256": {
            "llama_server": sha256(args.llama_server) if args.llama_server.is_file() else None,
            "gguf_shards": [sha256(path) if path.is_file() else None for path in args.gguf_shard],
            "comfy_model": sha256(args.comfy_model) if args.comfy_model.is_file() else None,
        },
        "execution_policy": "preflight_only; no download; no process launch; loopback only",
    }
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0 if evidence["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
