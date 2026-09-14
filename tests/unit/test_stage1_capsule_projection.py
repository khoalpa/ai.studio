import json
from pathlib import Path

import pytest

from audio_story.adapters.llm.models import PromptCapsule
from audio_story.workflows.stage1_capsule_projection import (
    CONTENT_UNITS,
    PROJECTION_VERSION,
    project_stage1_capsule,
)


def test_stage1_projection_preserves_authority_and_selected_units() -> None:
    from audio_story.domain.enums import Profile, Route, Stage
    from audio_story.domain.models import CompileRequest
    from audio_story.prompt_compiler import compile_capsule, parse_prompt

    canonical_path = Path(__file__).parents[2] / "canonical" / "ChatGPT_prompt_v3.16.13.txt"
    compiled = compile_capsule(
        parse_prompt(canonical_path.read_bytes()),
        CompileRequest(Stage.STAGE1, Profile.YOUTH_SAFE, Route.CREATE),
    )
    capsule = PromptCapsule(compiled.canonical_bytes, compiled.digest)
    projection = json.loads(project_stage1_capsule(capsule))
    assert projection["schema_version"] == PROJECTION_VERSION
    assert projection["authoritative_capsule_digest"] == capsule.digest
    assert tuple(unit["identifier"] for unit in projection["units"]) == CONTENT_UNITS
    assert len(project_stage1_capsule(capsule)) < len(capsule.canonical_bytes)


def test_stage1_projection_rejects_false_binding() -> None:
    with pytest.raises(ValueError, match="binding"):
        project_stage1_capsule(PromptCapsule(b'{"stage":"STAGE1"}', "a" * 64))
