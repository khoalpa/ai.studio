"""Deterministic inference projection of an authoritative M1 Stage 1 capsule."""

from __future__ import annotations

import json
from typing import Any

from audio_story.adapters.llm.models import PromptCapsule
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes

PROJECTION_VERSION = "M5P-STAGE1-INFERENCE-1.0"
CONTENT_UNITS = (
    "STORY-DURATION-CONFIRMATION-01",
    "STORY-VALIDATION-ROOT-PREFLIGHT-01",
    "PROFILE-SAFETY-01",
    "EXECUTE-NOW-01",
)


def project_stage1_capsule(capsule: PromptCapsule) -> bytes:
    value = json.loads(capsule.canonical_bytes)
    if value.get("capsule_digest") != capsule.digest or value.get("stage") != "STAGE1":
        raise ValueError("capsule projection binding is invalid")
    by_id = {unit["identifier"]: unit for unit in value["units"]}
    if any(identifier not in by_id for identifier in CONTENT_UNITS):
        raise ValueError("capsule projection unit is missing")
    units: list[dict[str, Any]] = [by_id[identifier] for identifier in CONTENT_UNITS]
    projection = {
        "schema_version": PROJECTION_VERSION,
        "authoritative_capsule_digest": capsule.digest,
        "canonical_prompt_sha256": value["canonical_prompt_sha256"],
        "stage": value["stage"],
        "profile": value["profile"],
        "route": value["route"],
        "units": units,
    }
    result = canonical_json_bytes(projection)
    if sha256_bytes(result) == capsule.digest:
        raise ValueError("projection must not masquerade as the authoritative capsule")
    return result
