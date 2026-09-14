"""Calibrate bounded JSON string lengths against the full Stage 1 segment envelope."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

from audio_story.adapters.llm.mock import DeterministicMockAdapter
from audio_story.domain.stage1 import resolve_profile
from audio_story.workflows import Stage1Service, WorkflowKernel
from audio_story.workflows.stage1 import _production_zone_instruction, _segment_json_schema
from audio_story.workflows.stage1_capsule_projection import project_stage1_capsule

BOUNDS = ((80, 150), (90, 170), (100, 190), (110, 210))
SEEDS = (1702, 1703, 1704)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--projected-context", action="store_true")
    parser.add_argument("--item-index", type=int, default=1)
    parser.add_argument("--segment-index", type=int, default=1)
    parser.add_argument("--seed-base", type=int, default=1702)
    parser.add_argument("--word-bounds", default="20:30")
    parser.add_argument(
        "--bounds",
        action="append",
        default=[],
        help="Character interval MIN:MAX; repeat for a matrix",
    )
    parser.add_argument(
        "--canonical", type=Path, default=Path("canonical/ChatGPT_prompt_v3.16.13.txt")
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    capsule_bytes = b""
    upstream: tuple[bytes, ...] = ()
    committed_texts: set[str] = set()
    if args.workspace is not None:
        capsule_bytes, upstream = load_production_context(
            args.workspace, args.canonical, projected=args.projected_context
        )
        committed_texts = load_committed_segment_texts(args.workspace, "GREETING")
    seeds = tuple(range(args.seed_base, args.seed_base + 3))
    word_bounds = tuple(int(value) for value in args.word_bounds.split(":"))
    if len(word_bounds) != 2 or word_bounds[0] >= word_bounds[1]:
        raise ValueError("--word-bounds must be MIN:MAX with MIN < MAX")
    bounds = (
        tuple(
            tuple(int(value) for value in specification.split(":")) for specification in args.bounds
        )
        or BOUNDS
    )
    if any(len(interval) != 2 or interval[0] >= interval[1] for interval in bounds):
        raise ValueError("each --bounds value must be MIN:MAX with MIN < MAX")
    results: list[dict[str, object]] = []
    for minimum, maximum in bounds:
        for seed in seeds:
            result = run_case(
                args.endpoint,
                minimum,
                maximum,
                seed,
                capsule_bytes=capsule_bytes,
                upstream=upstream,
                temperature=args.temperature,
                top_p=args.top_p,
                item_index=args.item_index,
                segment_index=args.segment_index,
                committed_texts=committed_texts,
                word_budget=word_bounds,
            )
            results.append(result)
            case = args.output / f"chars-{minimum}-{maximum}-seed-{seed}"
            case.mkdir(exist_ok=True)
            (case / "response.raw.json").write_bytes(result.pop("raw_response"))
            (case / "evidence.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    candidates = [
        [minimum, maximum]
        for minimum, maximum in bounds
        if (
            all(
                row["status"] == "PASS"
                for row in results
                if row["minimum_characters"] == minimum and row["maximum_characters"] == maximum
            )
            and len(
                {
                    row["content_sha256"]
                    for row in results
                    if row["minimum_characters"] == minimum and row["maximum_characters"] == maximum
                }
            )
            == len(seeds)
        )
    ]
    summary = {
        "cases": results,
        "passing_bounds": candidates,
        "decoding": {"temperature": args.temperature, "top_p": args.top_p},
        "context_mode": "projected" if args.projected_context else "authoritative",
    }
    summary["status"] = "PASS" if candidates else "FAIL"
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": summary["status"], "passing_bounds": candidates}))
    return 0 if candidates else 1


def load_production_context(
    workspace: Path, canonical: Path, *, projected: bool = False
) -> tuple[bytes, tuple[bytes, ...]]:
    kernel = WorkflowKernel(workspace)
    try:
        capsule = Stage1Service(kernel, DeterministicMockAdapter(), canonical)._capsule(
            resolve_profile("YOUTH_SAFE", "vi")
        )
        connection: sqlite3.Connection = kernel.db.connection
        outputs: list[bytes] = []
        for basename in ("plan.json", "draft.json", "review.json", "repair.json"):
            row = connection.execute(
                "SELECT a.sha256 FROM asset_transactions t "
                "JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
                "JOIN artifacts a ON a.id=b.artifact_id WHERE t.basename=?",
                (basename,),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"missing committed {basename}")
            outputs.append(kernel.store.get_artifact_by_digest(str(row["sha256"])))
        context = project_stage1_capsule(capsule) if projected else capsule.canonical_bytes
        return context, tuple(outputs)
    finally:
        kernel.close()


def load_committed_segment_texts(workspace: Path, zone: str) -> set[str]:
    kernel = WorkflowKernel(workspace)
    try:
        rows = kernel.db.connection.execute(
            "SELECT a.sha256 FROM asset_transactions t "
            "JOIN artifact_bindings b ON b.transaction_id=t.id AND b.role='COMMITTED' "
            "JOIN artifacts a ON a.id=b.artifact_id WHERE t.basename LIKE ?",
            (f"segment-{zone.lower()}-%.json",),
        ).fetchall()
        result = set()
        for row in rows:
            value = json.loads(kernel.store.get_artifact_by_digest(str(row["sha256"])))
            result.add(" ".join(str(value["items"][0]["text"]).casefold().split()))
        return result
    finally:
        kernel.close()


def run_case(
    endpoint: str,
    minimum: int,
    maximum: int,
    seed: int,
    *,
    capsule_bytes: bytes = b"",
    upstream: tuple[bytes, ...] = (),
    temperature: float = 0.8,
    top_p: float = 0.95,
    item_index: int = 1,
    segment_index: int = 1,
    committed_texts: set[str] | None = None,
    word_budget: tuple[int, int] = (20, 30),
) -> dict[str, object]:
    instruction = (
        _production_zone_instruction(
            "GREETING", 1, word_budget, upstream, item_index=item_index, segment_index=segment_index
        )
        if upstream
        else (
            "Write only segment 1 of item 1 in the GREETING zone of a Vietnamese youth-safe "
            "audio story. Return the exact JSON envelope. The text must contain 20 to 30 "
            "Unicode words, continue the premise that a child finds a mysterious lamp after "
            "rain, and end with punctuation. Count words before returning."
        )
    )
    schema = (
        _segment_json_schema(word_budget, "GREETING", item_index, segment_index)
        if upstream
        else {
            "type": "object",
            "properties": {
                "schema_version": {"const": "1.0"},
                "zone": {"const": "GREETING"},
                "status": {"const": "PASS"},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "speaker_id": {"const": "narrator"},
                            "voice": {"const": "narrator"},
                            "speed": {"const": "1.0"},
                            "environment": {"type": "string", "minLength": 1},
                            "text": {"type": "string", "minLength": minimum, "maxLength": maximum},
                        },
                        "required": [
                            "item_id",
                            "speaker_id",
                            "voice",
                            "speed",
                            "environment",
                            "text",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["schema_version", "zone", "status", "items"],
            "additionalProperties": False,
        }
    )
    schema["properties"]["items"]["items"]["properties"]["text"] = {
        "type": "string",
        "minLength": minimum,
        "maxLength": maximum,
    }
    prefix = capsule_bytes.decode("utf-8") + "\n\n" if capsule_bytes else ""
    payload = {
        "prompt": prefix + f"<|im_start|>user\n{instruction}\n<|im_end|>\n<|im_start|>assistant\n",
        "n_predict": 256,
        "seed": seed,
        "json_schema": schema,
        "temperature": temperature,
        "top_p": top_p,
    }
    request_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    request = urllib.request.Request(
        endpoint + "/completion",
        data=request_bytes,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
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
    text = ""
    try:
        parsed = json.loads(content)
        text = str(parsed["items"][0]["text"])
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    repeated = len(words) >= 8 and len(set(word.casefold() for word in words)) < len(words) / 3
    duplicates_committed = " ".join(text.casefold().split()) in (committed_texts or set())
    passed = (
        http_status == 200
        and word_budget[0] <= len(words) <= word_budget[1]
        and not repeated
        and not duplicates_committed
        and value.get("stop_type") not in {"limit", "length"}
        and not value.get("truncated")
    )
    return {
        "minimum_characters": minimum,
        "maximum_characters": maximum,
        "seed": seed,
        "temperature": temperature,
        "top_p": top_p,
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "http_status": http_status,
        "word_count": len(words),
        "word_bounds": list(word_budget),
        "repeated": repeated,
        "duplicates_committed": duplicates_committed,
        "tokens_predicted": value.get("tokens_predicted"),
        "stop_type": value.get("stop_type"),
        "truncated": value.get("truncated"),
        "duration_ms": duration_ms,
        "status": "PASS" if passed else "FAIL",
        "raw_response": raw,
    }


if __name__ == "__main__":
    raise SystemExit(main())
