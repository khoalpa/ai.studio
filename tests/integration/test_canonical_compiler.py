from __future__ import annotations

import json
from pathlib import Path

import pytest

from audio_story.domain.enums import Profile, Stage
from audio_story.domain.models import CompileRequest
from audio_story.prompt_compiler import (
    audio_mode_collision_finding,
    compile_capsule,
    parse_prompt,
)
from audio_story.prompt_compiler.capsule import AUDIT_GUARD, LEGACY_GUARD

ROOT = Path(__file__).parents[2]
CANONICAL = ROOT / "canonical" / "ChatGPT_prompt_v3.16.13.txt"
SNAPSHOT = ROOT / "tests" / "fixtures" / "m1_capsule_digests.json"


@pytest.fixture(scope="module")
def parsed():  # type: ignore[no-untyped-def]
    return parse_prompt(CANONICAL.read_bytes())


def test_canonical_integrity_and_inventory(parsed) -> None:  # type: ignore[no-untyped-def]
    assert (
        parsed.source_sha256 == "4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27"
    )
    assert len(parsed.blocks) == 27
    assert len(parsed.registries) == 11


def test_twelve_route_snapshots_are_stable(parsed) -> None:  # type: ignore[no-untyped-def]
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    actual = {
        f"{stage.value}-{profile.value}": compile_capsule(
            parsed, CompileRequest(stage, profile)
        ).digest
        for stage in Stage
        for profile in Profile
    }
    assert actual == expected
    assert len(actual) == 12


def test_capsule_bytes_and_digest_are_deterministic(parsed) -> None:  # type: ignore[no-untyped-def]
    request = CompileRequest(Stage.STAGE2, Profile.ADULT_STANDARD)
    first = compile_capsule(parsed, request)
    second = compile_capsule(parsed, request)
    assert first.canonical_bytes == second.canonical_bytes
    assert first.digest == second.digest


def test_dormant_stage_profile_and_overlay_are_absent(parsed) -> None:  # type: ignore[no-untyped-def]
    capsule = compile_capsule(parsed, CompileRequest(Stage.STAGE1, Profile.YOUTH_SAFE))
    blocks = set(capsule.document["active_blocks"])
    assert "PROFILE_YOUTH_SAFE" in blocks
    assert "PROFILE_ADULT_STANDARD" not in blocks
    assert "PROFILE_SERIAL_DETECTIVE" not in blocks
    assert "IMAGE_TRANSACTION_KERNEL" not in blocks
    assert "LEGACY_INPUT_COMPATIBILITY" not in blocks
    assert "FRAMEWORK_RELEASE_AUDIT" not in blocks
    assert len(capsule.canonical_bytes) < parsed.source_size


def test_overlays_require_their_exact_activation_guards(parsed) -> None:  # type: ignore[no-untyped-def]
    legacy = compile_capsule(
        parsed,
        CompileRequest(
            Stage.STAGE2,
            Profile.YOUTH_SAFE,
            activation_guards=frozenset({LEGACY_GUARD}),
        ),
    )
    audit = compile_capsule(
        parsed,
        CompileRequest(
            Stage.STAGE4,
            Profile.ADULT_STANDARD,
            activation_guards=frozenset({AUDIT_GUARD}),
        ),
    )
    assert "LEGACY_INPUT_COMPATIBILITY" in legacy.document["active_blocks"]
    assert "FRAMEWORK_RELEASE_AUDIT" in audit.document["active_blocks"]


def test_one_byte_change_rebinds_source_and_capsule() -> None:
    source = CANONICAL.read_bytes()
    changed = source.replace(b"PROMPT VERSION", b"PROMPt VERSION", 1)
    assert changed != source
    original = parse_prompt(source)
    modified = parse_prompt(changed)
    request = CompileRequest(Stage.STAGE1, Profile.YOUTH_SAFE)
    assert modified.source_sha256 != original.source_sha256
    assert compile_capsule(modified, request).digest != compile_capsule(original, request).digest


def test_audio_mode_collision_is_reported_without_resolution(parsed) -> None:  # type: ignore[no-untyped-def]
    finding = audio_mode_collision_finding(parsed)
    assert finding is not None
    assert finding.code == "PCF001_STAGE4_AUDIO_MODE_DEFAULT_COLLISION"
    assert "no value was selected" in finding.message
