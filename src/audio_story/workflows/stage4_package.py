"""M9 Stage 4 package assembly and exact-byte postwrite verification."""

from __future__ import annotations

import io
import tempfile
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_story.domain.stage4 import Stage4Error, Stage4PackageInput
from audio_story.validation.archives import inspect_zip, safe_extract
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage1 import ordered_json_bytes
from audio_story.validation.stage4 import (
    assert_stage3_members_unchanged,
    validate_video_prompts_for_source,
)


@dataclass(frozen=True, slots=True)
class Stage4Package:
    manifest_bytes: bytes
    video_prompts_bytes: bytes
    zip_bytes: bytes
    archive_sha256: str
    package_digest_sha256: str


def build_stage4_package(source: Stage4PackageInput, video_prompts_bytes: bytes) -> Stage4Package:
    validate_video_prompts_for_source(video_prompts_bytes, source)
    assert_stage3_members_unchanged(source, source.members)
    members: OrderedDict[str, bytes] = OrderedDict()
    for path, data in source.members.items():
        if path == "series_anchor.json":
            continue
        members[path] = data
    members["video_prompts.json"] = video_prompts_bytes
    if "series_anchor.json" in source.members:
        members["series_anchor.json"] = source.members["series_anchor.json"]
    manifest, package_digest = _manifest(source, members)
    archive = _zip(manifest, members)
    _reopen(archive, manifest, members, source)
    return Stage4Package(
        manifest, video_prompts_bytes, archive, sha256_bytes(archive), package_digest
    )


def write_stage4_package(package: Stage4Package, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(package.zip_bytes)
    if sha256_bytes(path.read_bytes()) != package.archive_sha256:
        raise Stage4Error("M9E001_POSTWRITE", "archive bytes changed after write", str(path))
    inspect_zip(path)


def _manifest(source: Stage4PackageInput, members: OrderedDict[str, bytes]) -> tuple[bytes, str]:
    owners = {item["path"]: item["owner_stage"] for item in source.manifest["files"]}
    files = [
        OrderedDict(
            path=path,
            sha256=sha256_bytes(data),
            size_bytes=len(data),
            owner_stage=owners.get(path, "STAGE4"),
            mutation_status="READ_ONLY" if path in source.members else "CREATED_CURRENT_STAGE",
        )
        for path, data in members.items()
    ]
    projection = [
        {key: item[key] for key in ("path", "sha256", "size_bytes", "owner_stage")}
        for item in files
    ]
    digest = sha256_bytes(canonical_json_bytes(projection))
    manifest = OrderedDict(
        schema_version="1.0",
        package_stage="STAGE4",
        package_purpose="VIDEO_PRODUCTION_RELEASE",
        operation_mode="CREATE",
        created_by_prompt_version="3.16.13+M9-ADR-001",
        active_profile=source.manifest["active_profile"],
        story_sha256=sha256_bytes(source.members["story.json"]),
        parent_package_digest_sha256=source.package_digest_sha256,
        allowed_next_stage=None,
        file_count=len(files) + 1,
        files=files,
        validation=OrderedDict(
            manifest_schema_status="PASS",
            archive_security_status="PASS",
            file_set_status="PASS",
            file_digest_status="PASS",
            stage_ownership_status="PASS",
            parent_binding_status="PASS",
            stage_gate_status="PASS",
            status="PASS",
        ),
        package_digest_sha256=digest,
    )
    return ordered_json_bytes(manifest), digest


def _zip(manifest: bytes, members: OrderedDict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in [("workflow_manifest.json", manifest), *members.items()]:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return output.getvalue()


def _reopen(
    archive_bytes: bytes,
    manifest: bytes,
    members: OrderedDict[str, bytes],
    source: Stage4PackageInput,
) -> None:
    with tempfile.TemporaryDirectory(prefix="audio-story-m9-") as temp:
        path = Path(temp) / "story.zip"
        path.write_bytes(archive_bytes)
        if [entry.path for entry in inspect_zip(path)] != ["workflow_manifest.json", *members]:
            raise Stage4Error("M9E010_ORDER", "archive member order mismatch", "story.zip")
        root = safe_extract(path, Path(temp) / "extract")
        for name, data in [("workflow_manifest.json", manifest), *members.items()]:
            if (root / name).read_bytes() != data:
                raise Stage4Error("M9E011_BYTES", "archive member bytes changed", name)
        validate_video_prompts_for_source((root / "video_prompts.json").read_bytes(), source)
        import json

        parsed: dict[str, Any] = json.loads((root / "workflow_manifest.json").read_bytes())
        if parsed["parent_package_digest_sha256"] != source.package_digest_sha256:
            raise Stage4Error("M9E012_PARENT", "parent binding mismatch", "workflow_manifest.json")
