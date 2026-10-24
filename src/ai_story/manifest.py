from __future__ import annotations

import platform
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from .config import registry
from .hashing import package_digest
from .models import ArtifactRecord, Operation, Profile, Stage
from .state_machine import WorkflowStateMachine

MANIFEST_FIELDS = [
    "schema_version",
    "package_stage",
    "package_purpose",
    "operation_mode",
    "created_by_prompt_version",
    "active_profile",
    "story_sha256",
    "parent_package_digest_sha256",
    "allowed_next_stage",
    "file_count",
    "files",
    "validation",
    "generation",
    "package_digest_sha256",
]


def build_manifest(
    *,
    stage: Stage,
    operation: Operation,
    profile: Profile,
    records: list[ArtifactRecord],
    parent_package_digest_sha256: str | None,
    generation: dict[str, Any] | None = None,
    allow_next_stage: bool = True,
    artifact_class: str = "PRODUCTION_CANDIDATE",
    content_quality_status: str = "NOT_ASSESSED",
    validation_ledger: dict[str, Any] | None = None,
) -> OrderedDict[str, Any]:
    config = registry()
    by_path = {record.path: record for record in records}
    story = by_path.get("story.json")
    next_stage = WorkflowStateMachine.allowed_next(stage)
    validation = {
        "status": "PASS",
        "validator": "ai_story.package_reopen_verifier",
        "scope": "WORKFLOW_INTEGRITY",
        "execution_status": "SUCCEEDED" if allow_next_stage else "COMPLETED_WITH_WARNINGS",
        "integrity_status": "PASS",
        "content_quality_status": content_quality_status,
        "continuation_policy": (
            "BLOCKED" if not allow_next_stage
            else "CONTINUE_WITH_WARNINGS"
            if content_quality_status != "PASS"
            or artifact_class in {"EDITORIAL_DRAFT", "TEST_FIXTURE"}
            else "CONTINUE"
        ),
        "artifact_class": artifact_class,
        "validation_ledger_digest_sha256": (
            validation_ledger.get("ledger_digest_sha256") if validation_ledger else None
        ),
        "open_warning_count": (
            validation_ledger.get("summary", {}).get("open_warning_count", 0)
            if validation_ledger else 0
        ),
    }
    return OrderedDict(
        [
            ("schema_version", config["workflow"]["manifest_schema_version"]),
            ("package_stage", stage.value),
            ("package_purpose", config["workflow"]["purpose_by_stage"][stage.value]),
            ("operation_mode", operation.value),
            ("created_by_prompt_version", config["source"]["prompt_version"]),
            ("active_profile", profile.value),
            ("story_sha256", story.sha256 if story else None),
            ("parent_package_digest_sha256", parent_package_digest_sha256),
            ("allowed_next_stage", next_stage.value if next_stage and allow_next_stage else None),
            ("file_count", len(records) + 1),
            ("files", [record.to_dict() for record in sorted(records, key=lambda item: item.path)]),
            ("validation", validation),
            ("generation", generation or {
                "provider_mode": "unspecified",
                "providers": [],
                "prompt_template_version": None,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "host": {
                    "python": platform.python_version(),
                    "implementation": platform.python_implementation(),
                    "platform": sys.platform,
                },
                "peak_memory_bytes": None,
            }),
            ("package_digest_sha256", package_digest(records)),
        ]
    )
