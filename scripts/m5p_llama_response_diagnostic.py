"""Capture one raw local llama.cpp completion for M5-P decoding diagnosis."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1702)
    parser.add_argument("--n-predict", type=int, default=256)
    parser.add_argument("--ignore-eos", action="store_true")
    parser.add_argument("--minimum-characters", type=int)
    args = parser.parse_args()
    instruction = (
        "Return JSON only: an object with one field named text. The text value must be "
        "Vietnamese narrative prose containing between 20 and 30 Unicode words inclusive, "
        "ending with punctuation. Count the words before returning."
    )
    prompt = f"<|im_start|>user\n{instruction}\n<|im_end|>\n<|im_start|>assistant\n"
    payload = {
        "prompt": prompt,
        "n_predict": args.n_predict,
        "seed": args.seed,
        "json_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    }
    if args.minimum_characters is not None:
        payload["json_schema"]["properties"]["text"]["minLength"] = args.minimum_characters
        payload["json_schema"]["properties"]["text"]["maxLength"] = args.minimum_characters * 2
    if args.ignore_eos:
        payload["ignore_eos"] = True
    request_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    started = time.monotonic()
    request = urllib.request.Request(
        args.endpoint + "/completion",
        data=request_bytes,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    http_status = 200
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        http_status = exc.code
        raw = exc.read()
    duration_ms = int((time.monotonic() - started) * 1000)
    value = json.loads(raw)
    content = str(value.get("content", ""))
    try:
        generated = json.loads(content)
        text = generated.get("text", "") if isinstance(generated, dict) else ""
    except json.JSONDecodeError:
        text = ""
    word_count = len(str(text).split())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "response.raw.json").write_bytes(raw)
    (args.output / "content.raw.txt").write_text(content, encoding="utf-8")
    evidence = {
        "instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "parameters": {
            "n_predict": args.n_predict,
            "seed": args.seed,
            "temperature": "SERVER_DEFAULT",
            "ignore_eos": args.ignore_eos,
            "minimum_characters": args.minimum_characters,
            "json_schema": payload["json_schema"],
        },
        "duration_ms": duration_ms,
        "http_status": http_status,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "content_byte_count": len(content.encode()),
        "observed_word_count": word_count,
        "tokens_predicted": value.get("tokens_predicted"),
        "tokens_evaluated": value.get("tokens_evaluated"),
        "stop_reason": value.get("stop_reason"),
        "stop_type": value.get("stop_type"),
        "truncated": value.get("truncated"),
        "valid_json": http_status == 200 and bool(text),
        "bounded_stop": http_status == 200
        and value.get("stop_type") not in {"limit", "length"}
        and not bool(value.get("truncated")),
        "status": (
            "PASS"
            if 20 <= word_count <= 30
            and http_status == 200
            and bool(text)
            and value.get("stop_type") not in {"limit", "length"}
            and not bool(value.get("truncated"))
            else "FAIL"
        ),
    }
    evidence_bytes = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    (args.output / "evidence.json").write_bytes(evidence_bytes)
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
