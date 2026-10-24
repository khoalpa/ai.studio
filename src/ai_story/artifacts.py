from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath

from .config import registry
from .errors import ArtifactError
from .hashing import sha256_file
from .models import ArtifactRecord, Stage


def normalize_member_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ArtifactError(f"Unsafe artifact path: {value}")
    if ":" in path.parts[0]:
        raise ArtifactError(f"Drive-qualified artifact path: {value}")
    return path.as_posix()


def artifact_owner(member_path: str) -> str:
    normalized = normalize_member_path(member_path)
    definitions = registry()["artifacts"]
    matches: list[str] = []
    for pattern, definition in definitions.items():
        if pattern == normalized or fnmatch.fnmatchcase(normalized, pattern):
            matches.append(definition["owner_stage"])
    if len(matches) != 1:
        raise ArtifactError(f"Artifact must have exactly one owner: {normalized}")
    return matches[0]


def scan_artifacts(root: Path, stage: Stage) -> list[ArtifactRecord]:
    if not root.is_dir():
        raise ArtifactError(f"Artifact root is not a directory: {root}")
    records: list[ArtifactRecord] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = normalize_member_path(path.relative_to(root).as_posix())
        if relative == registry()["workflow"]["manifest_name"]:
            continue
        owner = artifact_owner(relative)
        if owner != "CURRENT_STAGE":
            order = registry()["workflow"]["stage_order"]
            if order.index(owner) > order.index(stage.value):
                raise ArtifactError(f"Future-stage artifact {relative} is not allowed in {stage.value}")
        records.append(
            ArtifactRecord(
                path=relative,
                owner_stage=owner,
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path),
            )
        )
    return records


def validate_stage_file_set(records: list[ArtifactRecord], stage: Stage) -> None:
    paths = {record.path for record in records}
    required = {
        "story.json", "story_validation.json", "story_contract.json",
        "outline_evidence.json", "quality_decision.json",
        "validation_ledger.json",
    }
    character_paths = {path for path in paths if fnmatch.fnmatchcase(path, "characters/*.png")}
    if not character_paths:
        raise ArtifactError("At least one character reference image is required")

    if stage in {Stage.STAGE2, Stage.STAGE3, Stage.STAGE4}:
        required.update({"visual_plan.json", "visual_bible.json"})
        expected_landscape = {f"landscape/{name}" for name in registry()["zone_image_basenames"]}
        actual_landscape = {path for path in paths if fnmatch.fnmatchcase(path, "landscape/*.png")}
        if actual_landscape != expected_landscape:
            raise ArtifactError("Landscape set must match the ten canonical ZONE basenames")
    if stage in {Stage.STAGE3, Stage.STAGE4}:
        required.add("package_quality_report.json")
        expected_portrait = {f"portrait/{name}" for name in registry()["zone_image_basenames"]}
        actual_portrait = {path for path in paths if fnmatch.fnmatchcase(path, "portrait/*.png")}
        if actual_portrait != expected_portrait:
            raise ArtifactError("Portrait set must match the ten canonical ZONE basenames")
    if stage is Stage.STAGE4:
        required.update(
            {"video_prompts.json", "production_plan.json", "subtitles.srt", "subtitles.vtt"}
        )

    missing = sorted(required - paths)
    if missing:
        raise ArtifactError(f"Missing required artifacts for {stage.value}: {missing}")
