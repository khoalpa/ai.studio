"""Packaged exact deterministic validator CLI and Python API.

The validator inspects bytes and structure only. It never performs semantic or
model assessment and never opens a network connection.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_story.validation.archives import inspect_zip
from audio_story.validation.canonical import digest_json, sha256_bytes
from audio_story.validation.errors import ValidationError, ValidationFinding
from audio_story.validation.images import validate_png
from audio_story.validation.limits import DEFAULT_LIMITS, ValidationLimits
from audio_story.validation.schemas import SCHEMAS, validate_schema
from audio_story.validation.strict_json import parse_json_bytes, validate_field_order

VALID_STATUSES = {"PASS", "FAIL", "NOT_VERIFIED", "NOT_APPLICABLE"}
RESULT_ORDER = (
    "schema_version",
    "validator_name",
    "validator_version",
    "validator_source",
    "canonical_prompt_sha256",
    "invocation",
    "input_bindings",
    "overall_status",
    "checks",
    "findings",
    "evidence_digests",
    "result_digest",
    "result_self_reopen_status",
)


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    stage: str
    profile: str
    route: str
    phase: str
    artifact_path: Path
    canonical_prompt_sha256: str
    capsule_digest: str
    output_path: Path | None = None
    limits: ValidationLimits = DEFAULT_LIMITS


def validate(request: ValidationRequest) -> dict[str, Any]:
    path = request.artifact_path
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    try:
        if path.is_dir():
            files = sorted(item for item in path.rglob("*") if item.is_file() or item.is_symlink())
            bindings = [
                {
                    "relative_path": item.relative_to(path).as_posix(),
                    "sha256": sha256_bytes(item.read_bytes()),
                }
                for item in files
                if item.is_file() and not item.is_symlink()
            ]
            checks.append(_check("FILE_SET_INVENTORY", "PASS", {"file_count": len(bindings)}))
        else:
            data = path.read_bytes()
            bindings = [
                {"relative_path": path.name, "sha256": sha256_bytes(data), "byte_size": len(data)}
            ]
            suffix = path.suffix.lower()
            if suffix == ".json":
                parsed = parse_json_bytes(
                    data,
                    str(path),
                    engine_generated=request.phase == "OUTPUT",
                    limits=request.limits,
                )
                checks.append(_check("STRICT_JSON", "PASS", {"sha256": sha256_bytes(data)}))
                if path.name in SCHEMAS:
                    status = validate_schema(parsed.value, path.name, request.phase, str(path))
                    checks.append(
                        _check(
                            "SCHEMA",
                            "PASS" if status == "IMPLEMENTED" else "NOT_VERIFIED",
                            {"implementation_status": status},
                        )
                    )
            elif suffix == ".png":
                info = validate_png(data, str(path), limits=request.limits)
                checks.append(
                    _check(
                        "PNG_BASIC",
                        "PASS",
                        {"width": info.width, "height": info.height, "sha256": info.sha256},
                    )
                )
            elif suffix == ".zip":
                members = inspect_zip(path, limits=request.limits)
                checks.append(_check("ZIP_SECURITY", "PASS", {"member_count": len(members)}))
            else:
                checks.append(_check("ARTIFACT_TYPE", "NOT_VERIFIED", {"suffix": suffix}))
    except (OSError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            findings.append(exc.finding.as_dict())
        else:
            findings.append(
                {
                    "code": "DV001_IO_ERROR",
                    "message": str(exc),
                    "artifact_path": str(path),
                    "detector_class": "DETERMINISTIC",
                }
            )
        checks.append(_check("VALIDATION_EXECUTION", "FAIL", {}))

    statuses = [item["status"] for item in checks]
    overall = (
        "FAIL" if "FAIL" in statuses else "NOT_VERIFIED" if "NOT_VERIFIED" in statuses else "PASS"
    )
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "validator_name": "validate_story_runtime.py",
        "validator_version": "0.1.0",
        "validator_source": "PACKAGED_EXACT_IMPLEMENTATION",
        "canonical_prompt_sha256": request.canonical_prompt_sha256,
        "invocation": {
            "stage": request.stage,
            "profile": request.profile,
            "route": request.route,
            "phase": request.phase,
            "capsule_digest": request.capsule_digest,
        },
        "input_bindings": bindings,
        "overall_status": overall,
        "checks": checks,
        "findings": findings,
        "evidence_digests": [digest_json(check) for check in checks],
        "result_digest": "",
        "result_self_reopen_status": "PASS"
        if request.output_path is not None
        else "NOT_APPLICABLE",
    }
    result["result_digest"] = digest_json(_result_projection(result))
    if request.output_path is not None:
        _write_and_reopen(result, request.output_path, request.limits)
    return result


def _check(identifier: str, status: str, evidence: dict[str, Any]) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(status)
    return {"check_id": identifier, "status": status, "evidence": evidence}


def _result_projection(result: dict[str, Any]) -> dict[str, Any]:
    excluded = {"generated_timestamp", "result_digest", "result_self_reopen_status"}
    return {key: value for key, value in result.items() if key not in excluded}


def _write_and_reopen(result: dict[str, Any], path: Path, limits: ValidationLimits) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )
    path.write_bytes(payload)
    reopened = parse_json_bytes(path.read_bytes(), str(path), engine_generated=True, limits=limits)
    validate_field_order(reopened.value, RESULT_ORDER, str(path))
    reopened_bytes = json.dumps(
        reopened.value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    if reopened_bytes != payload:
        raise ValidationError(
            ValidationFinding(
                "DV002_RESULT_REOPEN_MISMATCH", "reopened result bytes differ", str(path)
            )
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="validate_story_runtime")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--phase", required=True, choices=("INPUT", "OUTPUT"))
    parser.add_argument("--canonical-prompt-sha256", required=True)
    parser.add_argument("--capsule-digest", required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate(
        ValidationRequest(
            args.stage,
            args.profile,
            args.route,
            args.phase,
            args.artifact,
            args.canonical_prompt_sha256,
            args.capsule_digest,
            args.output,
        )
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["overall_status"] in {"PASS", "NOT_VERIFIED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
