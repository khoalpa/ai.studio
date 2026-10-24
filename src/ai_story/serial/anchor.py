from __future__ import annotations

import copy
import json
import re
from enum import Enum
from pathlib import Path
from typing import Any

from ..errors import WorkflowError
from ..hashing import sha256_file

ROOT_FIELDS = ["schema_version", "series", "canon", "continuity", "episode_ledger", "canon_change_log"]
CONTRACT_FIELDS = [
    "required_threads", "required_obligations", "required_state_transitions",
    "required_conflict_transactions", "forbidden_reveals", "allowed_new_elements",
    "target_arc_milestone", "target_climax_payoff", "character_pressure",
    "continuity_warnings",
]


class EpisodeMode(str, Enum):
    START_SERIES = "START_SERIES"
    CONTINUE_SERIES = "CONTINUE_SERIES"
    FINALIZE_SERIES = "FINALIZE_SERIES"


def empty_contract() -> dict[str, Any]:
    return {
        "required_threads": [], "required_obligations": [],
        "required_state_transitions": [], "required_conflict_transactions": [],
        "forbidden_reveals": [], "allowed_new_elements": [],
        "target_arc_milestone": "", "target_climax_payoff": "",
        "character_pressure": "", "continuity_warnings": [],
    }


def create_template(title: str, premise: str, planned_arc_episodes: int = 12) -> dict[str, Any]:
    series_id = re.sub(r"[^a-z0-9]+", "_", title.casefold()).strip("_") or "serial_detective"
    return {
        "schema_version": "3.2.0",
        "series": {
            "series_id": series_id, "title": title, "premise": premise,
            "genre": "serialized detective audio drama", "language": "vi",
            "audience": "người trưởng thành từ 18 tuổi trở lên, nghe truyện trinh thám audio nhiều episode",
            "author": "An Nhiên", "channel": "Dạ Đàm Kỳ Án",
            "tone": "bí ẩn, tâm lý, hồi hộp có kiểm soát",
            "planned_arc_episodes": planned_arc_episodes, "created_episode": 1,
            "status": "active",
        },
        "canon": {
            "investigation_team": [], "recurring_characters": [], "recurring_locations": [],
            "organizations": [],
            "master_mystery": {"central_question": premise, "known_facts": [], "hidden_truth": "LOCKED_UNTIL_FINALE", "reveal_plan": [], "arc_milestones": [], "final_resolution_constraints": []},
            "world_rules": {"realism_level": "grounded", "technology_limit": "plausible and non-omnipotent", "legal_limit": "consequences and due process remain meaningful", "forbidden_devices": ["omniscient deduction", "unprepared supernatural solution", "operational crime instructions", "retcon without explicit continuity repair"]},
            "visual_bible": {"art_direction": "bright modern noir detective mystery, grounded realism, open shadows, illuminated faces and evidence", "palette": ["deep_blue", "evidence_amber"], "recurring_characters": [], "recurring_locations": [], "recurring_props": []},
        },
        "continuity": {
            "revision": 0, "latest_episode": 0, "timeline_cursor": None,
            "active_case_arc": {"status": "not_started", "part_index": 0, "part_total": 0, "local_progress": ""},
            "open_threads": [], "clue_ledger": [], "knowledge_states": [],
            "relationship_states": [], "unresolved_consequences": [], "recurring_assets": [],
            "architecture_state": {"state_registry": [], "open_obligations": [], "active_conflict_transactions": [], "climax_causality": {"setup_ids": [], "option_conflict": "", "irreversible_choice_state": "", "concrete_cost_ids": [], "persistent_consequence_ids": [], "target_episode": 0}, "continuity_evidence": []},
            "next_episode_contract": empty_contract(),
        },
        "episode_ledger": [],
        "canon_change_log": [],
    }


def load_anchor(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Cannot load series anchor: {exc}") from exc


def validate_anchor(anchor: dict[str, Any]) -> None:
    if list(anchor) != ROOT_FIELDS or anchor.get("schema_version") != "3.2.0":
        raise WorkflowError("Series anchor root or schema version is invalid")
    series = anchor.get("series", {})
    continuity = anchor.get("continuity", {})
    if series.get("genre") != "serialized detective audio drama" or series.get("channel") != "Dạ Đàm Kỳ Án":
        raise WorkflowError("Series anchor discriminator is invalid")
    revision = continuity.get("revision")
    latest = continuity.get("latest_episode")
    if not isinstance(revision, int) or not isinstance(latest, int) or revision < 0 or latest < 0:
        raise WorkflowError("Series anchor revision/latest episode is invalid")
    ledger = anchor.get("episode_ledger", [])
    if [item.get("episode_number") for item in ledger] != list(range(1, latest + 1)):
        raise WorkflowError("Series episode ledger is not contiguous")
    if len({item.get("title") for item in ledger}) != len(ledger):
        raise WorkflowError("Series episode titles must be unique")
    contract = continuity.get("next_episode_contract", {})
    if list(contract) != CONTRACT_FIELDS:
        raise WorkflowError("Series next episode contract shape is invalid")
    if series.get("status") not in {"active", "completed"}:
        raise WorkflowError("Series lifecycle status is invalid")
    if series["status"] == "completed" and contract != empty_contract():
        raise WorkflowError("Completed series must have a terminal-empty contract")


class SeriesAnchorTransaction:
    def prepare(
        self,
        *,
        mode: EpisodeMode,
        title: str | None,
        premise: str,
        input_anchor: Path | None,
        planned_arc_episodes: int = 12,
    ) -> dict[str, Any]:
        if mode is EpisodeMode.START_SERIES:
            if not title:
                raise WorkflowError("START_SERIES requires a series title")
            base = create_template(title, premise, planned_arc_episodes)
        else:
            if input_anchor is None:
                raise WorkflowError(f"{mode.value} requires an authoritative series anchor")
            base = load_anchor(input_anchor)
            validate_anchor(base)
            if base["series"]["status"] != "active":
                raise WorkflowError("Cannot continue or finalize a completed series")
            if base["continuity"]["latest_episode"] < 1:
                raise WorkflowError(f"{mode.value} requires at least one committed episode")
        return copy.deepcopy(base)

    def apply_story_identity(self, anchor: dict[str, Any], story: dict[str, Any], mode: EpisodeMode) -> None:
        episode = anchor["continuity"]["latest_episode"] + 1
        story["meta"].update(
            {
                "title": f"{anchor['series']['title']}: Hồ Sơ {episode}",
                "series": anchor["series"]["title"], "episode": str(episode),
                "author": anchor["series"]["author"], "channel": anchor["series"]["channel"],
                "target": "18+", "audience": anchor["series"]["audience"],
                "genre": anchor["series"]["genre"],
                "tone": ["bí ẩn", "tâm lý", "hồi hộp có kiểm soát"],
            }
        )

    def commit(self, anchor: dict[str, Any], story: dict[str, Any], story_path: Path, mode: EpisodeMode) -> dict[str, Any]:
        working = copy.deepcopy(anchor)
        episode = working["continuity"]["latest_episode"] + 1
        revision = working["continuity"]["revision"] + 1
        if story["meta"]["series"] != working["series"]["title"] or int(story["meta"]["episode"]) != episode:
            raise WorkflowError("Story and series anchor episode identity do not match")
        if any(item["title"] == story["meta"]["title"] for item in working["episode_ledger"]):
            raise WorkflowError("Episode title already exists in the anchor ledger")
        if not working["canon"]["investigation_team"]:
            working["canon"]["investigation_team"] = [
                {"character_id": item["character_id"], "name": item["name"], "role": item["role"], "canonical_age_min": item["canonical_age_min"], "canonical_age_max": item["canonical_age_max"]}
                for item in story["characters"]
            ]
            working["canon"]["visual_bible"]["recurring_characters"] = [
                {"character_id": item["character_id"], "identity_traits": item["identity_traits"]}
                for item in story["characters"]
            ]
        working["continuity"]["revision"] = revision
        working["continuity"]["latest_episode"] = episode
        working["continuity"]["timeline_cursor"] = f"episode_{episode:04d}_end"
        working["continuity"]["active_case_arc"] = {
            "status": "completed" if mode is EpisodeMode.FINALIZE_SERIES else "active",
            "part_index": episode,
            "part_total": episode if mode is EpisodeMode.FINALIZE_SERIES else working["series"]["planned_arc_episodes"],
            "local_progress": f"Episode {episode} committed",
        }
        working["episode_ledger"].append(
            {"episode_number": episode, "title": story["meta"]["title"], "story_sha256": sha256_file(story_path), "anchor_revision": revision, "episode_mode": mode.value}
        )
        working["canon_change_log"].append(
            {"revision": revision, "change_type": "episode_commit", "episode_number": episode, "reason": mode.value, "affected_ids": ["continuity", f"episode_{episode:04d}"]}
        )
        if mode is EpisodeMode.FINALIZE_SERIES:
            working["series"]["status"] = "completed"
            working["continuity"]["next_episode_contract"] = empty_contract()
        else:
            working["continuity"]["next_episode_contract"] = {
                "required_threads": [], "required_obligations": [],
                "required_state_transitions": [], "required_conflict_transactions": [],
                "forbidden_reveals": ["master_hidden_truth"],
                "allowed_new_elements": ["one_new_witness_or_location"],
                "target_arc_milestone": "", "target_climax_payoff": "",
                "character_pressure": "Trust must change through observable action.",
                "continuity_warnings": ["Do not retcon established clues."],
            }
        validate_anchor(working)
        return working
