"""Deterministic Stage 1 character fixtures, manifest and ZIP packaging."""

from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import zipfile
import zlib
from collections import OrderedDict
from pathlib import Path
from typing import Any

from audio_story.domain.stage1 import Stage1Error
from audio_story.validation.archives import inspect_zip, safe_extract
from audio_story.validation.canonical import canonical_json_bytes, sha256_bytes
from audio_story.validation.stage1 import (
    ordered_json_bytes,
    validate_anchor_bytes,
    validate_manifest_bytes,
)

PROMPT_VERSION = "3.16.13"


def build_series_anchor(story: dict[str, Any]) -> bytes:
    """Materialize the minimal current SERIAL_DETECTIVE continuity checkpoint."""
    meta = story["meta"]
    characters = story["characters"]
    anchor = OrderedDict(
        schema_version="3.2.0",
        series=OrderedDict(
            series_id=f"series:{sha256_bytes(str(meta['series']).encode())[:16]}",
            title=meta["series"],
            premise=story["outline"]["premise"],
            genre=meta["genre"],
            language=meta["language"],
            audience=meta["audience"],
            author=meta["author"],
            channel=meta["channel"],
            tone=meta["tone"],
            planned_arc_episodes=12,
            created_episode=1,
            status="active",
        ),
        canon=OrderedDict(
            investigation_team=[],
            recurring_characters=[
                OrderedDict(character_id=item["character_id"], name=item["name"])
                for item in characters
            ],
            recurring_locations=[],
            organizations=[],
            master_mystery=OrderedDict(
                central_question="Vụ việc bắt nguồn từ đâu?",
                known_facts=[],
                hidden_truth="Chưa tiết lộ",
                reveal_plan=[],
                arc_milestones=[],
                final_resolution_constraints=[],
            ),
            world_rules=OrderedDict(
                realism_level="grounded",
                technology_limit="plausible and non-omnipotent",
                legal_limit="consequences and due process remain meaningful",
                forbidden_devices=[
                    "omniscient deduction",
                    "unprepared supernatural solution",
                    "operational crime instructions",
                    "retcon without explicit continuity repair",
                ],
            ),
            visual_bible=OrderedDict(
                art_direction="bright modern noir detective mystery, grounded realism, open shadows, illuminated faces and evidence",
                palette=[],
                recurring_characters=[],
                recurring_locations=[],
                recurring_props=[],
            ),
        ),
        continuity=OrderedDict(
            revision=1,
            latest_episode=1,
            timeline_cursor="episode:1",
            active_case_arc=OrderedDict(
                status="active", part_index=1, part_total=12, local_progress="episode one"
            ),
            open_threads=[],
            clue_ledger=[],
            knowledge_states=[],
            relationship_states=[],
            unresolved_consequences=[],
            recurring_assets=[],
            architecture_state=OrderedDict(
                state_registry=[],
                open_obligations=[],
                active_conflict_transactions=[],
                climax_causality=OrderedDict(
                    setup_ids=[],
                    option_conflict="",
                    irreversible_choice_state="",
                    concrete_cost_ids=[],
                    persistent_consequence_ids=[],
                    target_episode=0,
                ),
                continuity_evidence=[],
            ),
            next_episode_contract=OrderedDict(
                required_threads=[],
                required_obligations=[],
                required_state_transitions=[],
                required_conflict_transactions=[],
                forbidden_reveals=[],
                allowed_new_elements=[],
                target_arc_milestone="",
                target_climax_payoff="",
                character_pressure="",
                continuity_warnings=[],
            ),
        ),
        episode_ledger=[OrderedDict(episode_number=1, title=meta["title"], anchor_revision=1)],
        canon_change_log=[
            OrderedDict(
                change_id="change:1",
                revision=1,
                episode_number=1,
                change_type="start_series",
                affected_ids=["$.series"],
                before=None,
                after="episode 1",
                reason="Stage 1 start-series commit",
            )
        ],
    )
    data = ordered_json_bytes(anchor)
    validate_anchor_bytes(data, story)
    return data


def mock_character_png(character_id: str, seed: int) -> bytes:
    """Create deterministic test-only 1536x2048 RGB PNG bytes."""
    color = hashlib.sha256(f"{character_id}:{seed}".encode()).digest()[:3]
    width, height = 1536, 2048
    row = b"\x00" + color * width
    raw = row * height
    metadata = json.dumps(
        {"provenance": "TEST_ONLY_M5_MOCK", "character_id": character_id},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"tEXt", b"audio_story\x00" + metadata)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def character_set_digest(story: dict[str, Any], assets: dict[str, bytes]) -> str:
    tuples = [
        [
            character["character_id"],
            character["reference_asset"]["reference_image"],
            sha256_bytes(assets[character["reference_asset"]["reference_image"]]),
        ]
        for character in story["characters"]
    ]
    return sha256_bytes(canonical_json_bytes(tuples))


def build_manifest(profile: str, story_bytes: bytes, members: OrderedDict[str, bytes]) -> bytes:
    files = [
        OrderedDict(
            path=path,
            sha256=sha256_bytes(data),
            size_bytes=len(data),
            owner_stage="STAGE1",
            mutation_status="CREATED_CURRENT_STAGE",
        )
        for path, data in members.items()
    ]
    digest_items = [
        {
            "path": item["path"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
            "owner_stage": item["owner_stage"],
        }
        for item in files
    ]
    manifest = OrderedDict(
        schema_version="1.0",
        package_stage="STAGE1",
        package_purpose="WORKFLOW_CHECKPOINT",
        operation_mode="CREATE",
        created_by_prompt_version=PROMPT_VERSION,
        active_profile=profile,
        story_sha256=sha256_bytes(story_bytes),
        parent_package_digest_sha256=None,
        allowed_next_stage="STAGE2",
        file_count=1 + len(files),
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
        package_digest_sha256=sha256_bytes(canonical_json_bytes(digest_items)),
    )
    data = ordered_json_bytes(manifest)
    validate_manifest_bytes(data, members, profile)
    return data


def build_story_zip(path: Path, manifest: bytes, members: OrderedDict[str, bytes]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in [("workflow_manifest.json", manifest), *members.items()]:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with tempfile.TemporaryDirectory(prefix="audio-story-m5-reopen-") as parent:
        actual = [member.path for member in inspect_zip(path)]
        root = safe_extract(path, Path(parent))
        expected = ["workflow_manifest.json", *members]
        if actual != expected:
            raise Stage1Error("S150_PACKAGE_REOPEN", "archive order/file set mismatch", "story.zip")
        for name, data in [("workflow_manifest.json", manifest), *members.items()]:
            if (root / name).read_bytes() != data:
                raise Stage1Error("S150_PACKAGE_REOPEN", "archive member mismatch", name)
        extracted_members: OrderedDict[str, bytes] = OrderedDict(
            (name, (root / name).read_bytes()) for name in members
        )
        validate_manifest_bytes(
            (root / "workflow_manifest.json").read_bytes(),
            extracted_members,
            json.loads(manifest)["active_profile"],
        )
        if "series_anchor.json" in extracted_members:
            story = json.loads(extracted_members["story.json"])
            validate_anchor_bytes(extracted_members["series_anchor.json"], story)
    return sha256_bytes(path.read_bytes())


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
