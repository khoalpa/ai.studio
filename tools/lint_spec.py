from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SpecError(Exception):
    pass


def load(relative: str) -> dict:
    path = ROOT / relative
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"Cannot load {relative}: {exc}") from exc


def unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise SpecError(f"Duplicate {label}: {values}")


def lint() -> list[str]:
    registry = load("spec/registry.json")
    gates_document = load("spec/gates.json")
    matrix = load("spec/execution_matrix.json")
    contract = load("spec/mvp_contract.json")
    stage1 = load("spec/stage1.json")
    stage2 = load("spec/stage2.json")
    stage3 = load("spec/stage3.json")
    stage4 = load("spec/stage4.json")
    stage6 = load("spec/stage6.json")
    providers = load("spec/providers.json")
    release = load("spec/release.json")

    enums = registry["enums"]
    for name, values in enums.items():
        unique(values, f"enum value in {name}")

    profiles = enums["profiles"]
    stages = enums["stages"]
    operations = enums["operation_modes"]
    if set(registry["profiles"]) != set(profiles):
        raise SpecError("Profile registry differs from profiles enum")

    workflow = registry["workflow"]
    if workflow["stage_order"] != stages:
        raise SpecError("stage_order must exactly match stages enum")
    for index, stage in enumerate(stages):
        expected = stages[index + 1] if index + 1 < len(stages) else None
        if workflow["transitions"].get(stage) != expected:
            raise SpecError(f"Invalid transition for {stage}")
        if stage not in workflow["purpose_by_stage"]:
            raise SpecError(f"Missing package purpose for {stage}")

    if len(registry["zone_image_basenames"]) != 10:
        raise SpecError("ZONE must contain exactly ten image basenames")
    unique(registry["zone_image_basenames"], "ZONE basename")

    valid_owners = set(stages) | {"CURRENT_STAGE"}
    for artifact, definition in registry["artifacts"].items():
        if definition["owner_stage"] not in valid_owners:
            raise SpecError(f"Invalid owner for {artifact}")
    if set(registry["file_sets"]) != set(stages):
        raise SpecError("Every stage must have one file set")

    gate_list = gates_document["gates"]
    gate_ids = [gate["id"] for gate in gate_list]
    unique(gate_ids, "gate id")
    gate_map = {gate["id"]: gate for gate in gate_list}
    detectors = set(enums["detector_classes"])
    severities = set(enums["gate_severities"])
    for gate in gate_list:
        if gate["detector"] not in detectors:
            raise SpecError(f"Invalid detector for {gate['id']}")
        if gate["severity"] not in severities:
            raise SpecError(f"Invalid severity for {gate['id']}")
        if not set(gate["stages"]).issubset(stages):
            raise SpecError(f"Invalid stage on {gate['id']}")
        if gate["profiles"] != ["ALL"] and not set(gate["profiles"]).issubset(profiles):
            raise SpecError(f"Invalid profile on {gate['id']}")

    if set(matrix["defaults"]) != set(stages):
        raise SpecError("Matrix defaults must cover all stages")
    for stage, ids in matrix["defaults"].items():
        unique(ids, f"default gate on {stage}")
        for gate_id in ids:
            if gate_id not in gate_map:
                raise SpecError(f"Unknown gate {gate_id} on {stage}")
            if stage not in gate_map[gate_id]["stages"]:
                raise SpecError(f"Gate {gate_id} is not applicable to {stage}")

    route_keys: set[tuple[str, str, str]] = set()
    for route in matrix["routes"]:
        profile = route["profile"]
        stage = route["stage"]
        if profile not in profiles or stage not in stages:
            raise SpecError(f"Invalid route {profile}/{stage}")
        for gate_id in route["extra_gates"]:
            if gate_id not in gate_map:
                raise SpecError(f"Unknown extra gate {gate_id}")
            gate = gate_map[gate_id]
            if stage not in gate["stages"] or profile not in gate["profiles"]:
                raise SpecError(f"Extra gate {gate_id} not applicable to {profile}/{stage}")
        for operation in route["operations"]:
            key = (profile, stage, operation)
            if key in route_keys:
                raise SpecError(f"Duplicate route {key}")
            route_keys.add(key)

    expected_routes = {(p, s, o) for p in profiles for s in stages for o in operations}
    if route_keys != expected_routes:
        missing = sorted(expected_routes - route_keys)
        extra = sorted(route_keys - expected_routes)
        raise SpecError(f"Route coverage mismatch; missing={missing}, extra={extra}")

    if contract["status"] not in {
        "FROZEN_FOR_MILESTONE_1",
        "EXTENDED_FOR_MILESTONE_6",
        "RELEASE_CANDIDATE_MILESTONE_G",
    }:
        raise SpecError("MVP contract status is invalid")
    if not contract["release_rules"]["not_verified_blocks_publish"]:
        raise SpecError("NOT_VERIFIED must block publish")
    expected_zones = [
        "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
        "CLIMAX", "FALLING", "ENDING", "FAREWELL",
    ]
    if stage1["zones"] != expected_zones:
        raise SpecError("Stage 1 zones differ from the canonical order")
    if stage1["prompt_version"] != registry["source"]["prompt_version"]:
        raise SpecError("Stage 1 prompt version differs from the canonical source")
    if stage1.get("local_prompt_template_version") != "stage1-local/1.3":
        raise SpecError("Stage 1 local prompt template version is invalid")
    expected_duration_keys = {
        "YOUTH_SAFE", "ADULT_STANDARD", "SERIAL_DETECTIVE_START_SERIES",
        "SERIAL_DETECTIVE_CONTINUE_SERIES", "SERIAL_DETECTIVE_FINALIZE_SERIES",
    }
    if set(stage1["duration_defaults"]) != expected_duration_keys:
        raise SpecError("Stage 1 MVP duration defaults are incomplete")
    if stage2["enabled_mode"] != "ZONE":
        raise SpecError("Stage 2 MVP must enable only ZONE mode")
    if list(stage2["asset_roles"]) != registry["zone_image_basenames"]:
        raise SpecError("Stage 2 asset role order differs from canonical basenames")
    if list(stage2["zone_by_basename"]) != registry["zone_image_basenames"]:
        raise SpecError("Stage 2 zone map order differs from canonical basenames")
    if [stage2["landscape"]["width"], stage2["landscape"]["height"]] != [3840, 2160]:
        raise SpecError("Stage 2 landscape dimensions differ from the canonical size")
    if [stage3["portrait"]["width"], stage3["portrait"]["height"]] != [1080, 1920]:
        raise SpecError("Stage 3 portrait dimensions differ from the canonical size")
    if len(stage3["quality_dimensions"]) != 12:
        raise SpecError("Stage 3 quality dimension registry must contain twelve dimensions")
    if stage4["video_prompt_schema_version"] != "1.2":
        raise SpecError("Stage 4 must use video prompt schema 1.2")
    if stage4["clip_duration_options"] != [4, 6, 8]:
        raise SpecError("Stage 4 clip duration options differ from canonical values")
    if stage4["sentence_usable_span_max_seconds"] != 7.95:
        raise SpecError("Stage 4 usable span maximum differs from canonical value")
    if stage4.get("production_plan_schema_version") != "1.0":
        raise SpecError("Stage 4 production plan schema version is invalid")
    if stage4.get("subtitle_formats") != ["SRT", "WEBVTT"]:
        raise SpecError("Stage 4 subtitle formats are invalid")
    for aspect in ("LANDSCAPE_16_9", "PORTRAIT_9_16"):
        preset = stage4.get("export_presets", {}).get(aspect, {})
        if not preset.get("width") or not preset.get("height") or not preset.get("fps"):
            raise SpecError(f"Stage 4 export preset is incomplete: {aspect}")
    if stage6["series_anchor_schema_version"] != "3.2.0":
        raise SpecError("Milestone 6 must use anchor schema 3.2.0")
    if providers.get("active_mode") not in {
        "deterministic", "local", "local_sd35", "hybrid", "text_local"
    }:
        raise SpecError("Provider active_mode is invalid")
    provider_roles = {"story", "character_image", "safety", "landscape", "portrait"}
    for mode in ("deterministic", "local", "local_sd35", "hybrid", "text_local"):
        selected = providers.get("modes", {}).get(mode, {})
        if set(selected) != provider_roles:
            raise SpecError(f"Provider mode {mode} does not cover every role")
        if not set(selected.values()).issubset(providers.get("adapters", {})):
            raise SpecError(f"Provider mode {mode} references an unknown adapter")
    runtimes = providers.get("runtimes", {})
    for name, adapter in providers.get("adapters", {}).items():
        if adapter.get("runtime") not in runtimes:
            raise SpecError(f"Provider adapter {name} references an unknown runtime")
    policy = providers.get("policy", {})
    if policy.get("fallback") != "disabled":
        raise SpecError("Provider fallback must be disabled")
    if int(policy.get("retry_attempts", 0)) < 1:
        raise SpecError("Provider retry_attempts must be positive")
    diffusion = runtimes.get("diffusers", {})
    for key in ("character_work_size", "landscape_work_size", "portrait_work_size"):
        size = diffusion.get(key, [])
        if len(size) != 2 or any(not isinstance(value, int) or value <= 0 or value % 64 for value in size):
            raise SpecError(f"Diffusers {key} must contain positive multiples of 64")
    qa = diffusion.get("qa", {})
    if not qa.get("require_ocr") or not qa.get("require_semantic"):
        raise SpecError("Local image production mode requires OCR and semantic QA")
    local_mode = providers["modes"]["local"]
    if any(local_mode[role] != "local_sd35" for role in ("character_image", "landscape", "portrait")):
        raise SpecError("Local mode must use SD 3.5 Medium for all canonical image roles")
    image_models = providers.get("image_models", {})
    if set(image_models) != {"sd35_medium"}:
        raise SpecError("Provider configuration must only define the SD3.5 image profile")
    for name, profile in image_models.items():
        if profile.get("family") != "sd3" or not profile.get("model_id"):
            raise SpecError(f"Invalid image model profile: {name}")
    serial_routes = [route for route in matrix["routes"] if route["profile"] == "SERIAL_DETECTIVE"]
    if any(route["status"] == "DEFERRED" for route in serial_routes):
        raise SpecError("SERIAL_DETECTIVE routes must match the enabled Milestone 6 runtime")
    if release.get("schema_version") != "1.0":
        raise SpecError("Release specification schema version is invalid")
    if release.get("channels") != ["development", "production"]:
        raise SpecError("Release channels are invalid")
    if release.get("runtime_may_self_assert_framework_audit") is not False:
        raise SpecError("Runtime must not self-assert framework audit")
    if set(release.get("bundle_members", [])) != {
        "checksums.sha256", "release_manifest.json", "release_report.json", "story.zip",
    }:
        raise SpecError("Release bundle member set is invalid")

    return [
        f"profiles={len(profiles)}",
        f"stages={len(stages)}",
        f"routes={len(route_keys)}",
        f"gates={len(gate_ids)}",
        f"artifacts={len(registry['artifacts'])}",
        "stage1=enabled",
        "stage2_zone=enabled",
        "stage3=enabled",
        "stage4=enabled",
        "serial=enabled",
        "release=enabled",
        f"provider_mode={providers['active_mode']}",
    ]


def main() -> int:
    try:
        summary = lint()
    except SpecError as exc:
        print(f"SPEC_INVALID: {exc}", file=sys.stderr)
        return 1
    print("SPEC_VALID " + " ".join(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
