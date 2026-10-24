from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from ai_story.errors import ArtifactError
from ai_story.image_candidates import select_best_candidate
from ai_story.image_qa import ImageQualityError
from ai_story.providers import landscape_provider

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE4L = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1"
PHASE4K = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4k-promoted-cover-v1"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4m-surgical-climax-v1"
BASE = (
    PHASE4L
    / "youth-torn-paper-boat/work/candidates/climax/attempt-2-base.png"
)
CHECKPOINT = OUTPUT_ROOT / "phase4mr-checkpoint.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run exactly one recoverable Phase 4M local-crop attempt."
    )
    parser.add_argument("--attempt", type=int, choices=(1, 2, 3, 4, 5), required=True)
    parser.add_argument(
        "--allow-busy-gpu", action="store_true",
        help="Bypass the GPU exclusivity guard; intended only for explicit diagnostics.",
    )
    return parser.parse_args()


def gpu_status() -> dict[str, int | bool]:
    completed = subprocess.run(
        [
            "nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True, capture_output=True, text=True,
    )
    utilization, used, total = [
        int(value.strip()) for value in completed.stdout.strip().split(",")
    ]
    exclusive = utilization <= 30 and used <= 4096
    return {
        "utilization_percent": utilization,
        "memory_used_mib": used,
        "memory_total_mib": total,
        "exclusive_enough": exclusive,
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    options = parse_args()
    base_data = BASE.read_bytes()
    cover_report = json.loads((PHASE4K / "phase4k-result.json").read_text(encoding="utf-8"))
    cover_digest = cover_report["promotion"]["approved_cover_sha256"]
    expected_cover = "412875dd1a06374b2c20bbbd6e722d1c538aa2e400d900bad636eb2dc01a4fad"
    if cover_digest != expected_cover:
        raise RuntimeError("Phase 4K cover invariant failed")
    status = gpu_status()
    if not status["exclusive_enough"] and not options.allow_busy_gpu:
        waiting = {
            "schema_version": "1.0",
            "phase": "4M-R",
            "status": "WAITING_FOR_EXCLUSIVE_GPU",
            "requested_attempt": options.attempt,
            "gpu": status,
            "full_scene_generation_performed": False,
            "phase4k_cover_digest_preserved": cover_digest,
        }
        write_json(OUTPUT_ROOT / "phase4mr-runtime.json", waiting)
        print(json.dumps(waiting, ensure_ascii=False))
        return

    checkpoint = (
        json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        if CHECKPOINT.is_file() else {
            "schema_version": "1.0",
            "phase": "4M-R",
            "source_base_sha256": hashlib.sha256(base_data).hexdigest(),
            "phase4k_cover_digest": cover_digest,
            "attempts": {},
        }
    )
    if checkpoint["source_base_sha256"] != hashlib.sha256(base_data).hexdigest():
        raise RuntimeError("Phase 4M-R base checkpoint mismatch")
    prior = checkpoint["attempts"].get(str(options.attempt))
    if prior and prior.get("status") in {"ASSESSED_PASS", "ASSESSED_FAIL"}:
        print(json.dumps({"status": "ALREADY_COMPLETE", "attempt": prior}, ensure_ascii=False))
        return
    seed = int.from_bytes(
        hashlib.sha256(f"phase4m:climax:{options.attempt}".encode()).digest()[:4], "big"
    )
    checkpoint["attempts"][str(options.attempt)] = {
        "status": "RUNNING",
        "seed": seed,
        "gpu_at_start": status,
    }
    write_json(CHECKPOINT, checkpoint)

    characters = PHASE4L / "youth-torn-paper-boat/work/characters"
    bo_reference = (characters / "bo.png").read_bytes()
    mother_reference = (characters / "me.png").read_bytes()
    edit = {
        "base_prompt": "Locked Phase 4L attempt 2 base; no full-scene regeneration.",
        "prompt": (
            "Use case: precise-object-edit. Remove the cup. Keep exactly one small folded "
            "paper boat between the facing hands. Preserve its controlled silhouette and "
            "scale. Refine only hand contact, paper texture, shadow, and light. Keep both "
            "people and the scene unchanged. No cup, mug, glass, ship, text, or extra object."
        ),
        "crop_box": [0.34, 0.40, 0.66, 0.74],
        "mask_box": [0.44, 0.52, 0.56, 0.63],
        "feather_pixels": 16,
        "strength": 0.46,
        "two_pass_cleanup": options.attempt >= 3,
        "neutralize_object_before_cleanup": options.attempt == 4,
        "hand_preserving_deterministic_cleanup": options.attempt == 5,
        "cleanup_strength": 0.72 if options.attempt == 4 else 0.42,
        "cleanup_feather_pixels": 10,
        "cleanup_prompt": (
            "Precise object removal. Reconstruct empty space and natural forearms between "
            "the two facing hands. Preserve both people, pose, lighting, and illustration "
            "style. No cup, mug, glass, pedestal, tray, boat, text, or new object."
        ),
        "interaction_centered_mask": True,
        "interaction_target_x": 0.5,
        "interaction_target_y": 0.575,
        "minimum_hand_confidence": 0.62,
        "prop_first_compositing": True,
    }
    output_candidates = OUTPUT_ROOT / "candidates"
    output_candidates.mkdir(parents=True, exist_ok=True)
    landscape, registry = landscape_provider("local", quality_preset="quality")
    candidates: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    try:
        for attempt in [options.attempt]:
            try:
                data, mask, evidence, artifacts = landscape._masked_prop_edit(
                    basename="climax.png",
                    attempt=attempt,
                    base_data=base_data,
                    edit=edit,
                    negative_prompt=(
                        "cup, mug, glass, ship, large boat, extra person, duplicate person, "
                        "malformed hands, text, watermark"
                    ),
                    seed=seed,
                )
                prefix = output_candidates / f"attempt-{attempt}"
                prefix.with_name(prefix.name + "-candidate.png").write_bytes(data)
                prefix.with_name(prefix.name + "-mask.png").write_bytes(mask)
                for name, artifact in artifacts.items():
                    prefix.with_name(prefix.name + f"-{name}.png").write_bytes(artifact)
                cleanup_assessment = None
                if edit["two_pass_cleanup"]:
                    cleanup_assessment = landscape.assessor.assess_fidelity_probes(
                        artifacts["cleanup-pass"],
                        fidelity_probes=[{
                            "probe_id": "cleanup_cup_absence",
                            "expected": "empty space between two facing hands with no object",
                            "forbidden": [
                                "a cup between the hands", "a mug between the hands",
                                "a drinking glass", "a pedestal", "a paper boat",
                            ],
                            "crop_box_pixels": evidence["cleanup_pass"][
                                "object_mask_box_pixels"
                            ],
                        }],
                    )
                    evidence["cleanup_pass"]["assessment"] = cleanup_assessment
                    write_json(
                        prefix.with_name(prefix.name + "-cleanup-assessment.json"),
                        cleanup_assessment,
                    )
                    if cleanup_assessment["status"] != "ASSESSED_PASS":
                        raise ArtifactError(
                            "Pass-1 cleanup gate failed: "
                            + ", ".join(cleanup_assessment["failed_probes"])
                        )
                    deterministic_cleanup = evidence["cleanup_pass"].get("neutralization")
                    if deterministic_cleanup and any(
                        deterministic_cleanup.get(gate) != "PASS"
                        for gate in (
                            "protected_hand_pixel_invariance", "skin_blob_gate"
                        )
                        if gate in deterministic_cleanup
                    ):
                        raise ArtifactError("Deterministic hand-protection gate failed")
                failed_prop_gates = [
                    name for name, status_value in evidence["controlled_prop"]["gates"].items()
                    if status_value != "PASS"
                ]
                if failed_prop_gates:
                    raise ArtifactError(
                        "Deterministic controlled-prop gates failed: "
                        + ", ".join(failed_prop_gates)
                    )
                fidelity_probes = [
                    {
                        "probe_id": "person_count",
                        "expected": "exactly one Vietnamese boy and his mother, two people",
                        "forbidden": ["one person", "three or more people"],
                    },
                    {
                        "probe_id": "natural_interaction",
                        "expected": "a boy and his mother seated close with hands meeting naturally",
                        "forbidden": ["isolated people", "stiff character sheet"],
                    },
                    {
                        "probe_id": "controlled_prop_scale",
                        "expected": "one small palm-sized folded paper boat between facing hands",
                        "forbidden": ["an oversized paper boat", "a full-size ship"],
                        "crop_box_pixels": evidence["crop_box_pixels"],
                    },
                    {
                        "probe_id": "cup_absence",
                        "expected": "hands holding a folded paper boat without a cup",
                        "forbidden": ["a cup", "a mug", "a drinking glass"],
                        "crop_box_pixels": evidence["crop_box_pixels"],
                    },
                ]
                assessment = landscape.assessor.assess(
                    data,
                    prompt=(
                        "A Vietnamese boy and his mother sit close together in a furnished "
                        "bedroom with one small folded paper boat between their hands."
                    ),
                    expected_dimensions=(3840, 2160),
                    asset_type="landscape",
                    identity_references=[bo_reference, mother_reference],
                    required_elements=[
                        "character:bo", "character:me", "prop:paper boat"
                    ],
                    forbidden_elements=["uncontrolled_text", "watermark"],
                    fidelity_probes=fidelity_probes,
                    identity_regions=[
                        {
                            "character_id": "bo",
                            "box_normalized": [0.25, 0.16, 0.52, 0.88],
                            "references": [bo_reference],
                        },
                        {
                            "character_id": "me",
                            "box_normalized": [0.48, 0.12, 0.77, 0.88],
                            "references": [mother_reference],
                        },
                    ],
                )
                assessment["masked_prop_inpaint"] = evidence
                write_json(
                    prefix.with_name(prefix.name + "-assessment.json"), assessment
                )
                candidates.append({
                    "attempt": attempt,
                    "seed": seed,
                    "path": str(prefix.with_name(prefix.name + "-candidate.png").resolve()),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "assessment": assessment,
                })
                checkpoint["attempts"][str(attempt)] = {
                    "status": "ASSESSED_PASS",
                    "seed": seed,
                    "path": str(prefix.with_name(prefix.name + "-candidate.png").resolve()),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "assessment_path": str(
                        prefix.with_name(prefix.name + "-assessment.json").resolve()
                    ),
                }
                write_json(CHECKPOINT, checkpoint)
            except ImageQualityError as exc:
                failure = {
                    "attempt": attempt,
                    "seed": seed,
                    "error": "ImageQualityError",
                    "detail": str(exc),
                    "assessment": exc.assessment,
                }
                failures.append(failure)
                write_json(output_candidates / f"attempt-{attempt}-failure.json", failure)
                checkpoint["attempts"][str(attempt)] = {
                    "status": "ASSESSED_FAIL",
                    "seed": seed,
                    "failure_path": str(
                        (output_candidates / f"attempt-{attempt}-failure.json").resolve()
                    ),
                    "detail": str(exc),
                }
                write_json(CHECKPOINT, checkpoint)
            except ArtifactError as exc:
                failure = {
                    "attempt": attempt,
                    "seed": seed,
                    "error": "ArtifactError",
                    "detail": str(exc),
                }
                failures.append(failure)
                write_json(output_candidates / f"attempt-{attempt}-failure.json", failure)
                checkpoint["attempts"][str(attempt)] = {
                    "status": "ASSESSED_FAIL",
                    "seed": seed,
                    "failure_path": str(
                        (output_candidates / f"attempt-{attempt}-failure.json").resolve()
                    ),
                    "detail": str(exc),
                }
                write_json(CHECKPOINT, checkpoint)
            except Exception as exc:
                failure = {
                    "attempt": attempt,
                    "seed": seed,
                    "error": type(exc).__name__,
                    "detail": str(exc),
                }
                failures.append(failure)
                write_json(output_candidates / f"attempt-{attempt}-failure.json", failure)
                checkpoint["attempts"][str(attempt)] = {
                    "status": "RUNTIME_FAIL",
                    "seed": seed,
                    "failure_path": str(
                        (output_candidates / f"attempt-{attempt}-failure.json").resolve()
                    ),
                    "detail": str(exc),
                }
                write_json(CHECKPOINT, checkpoint)
    finally:
        landscape.assessor.unload()
        if registry is not None:
            registry.close()

    selected = select_best_candidate(candidates) if candidates else None
    if selected:
        selected_data = Path(str(selected["path"])).read_bytes()
        (OUTPUT_ROOT / "selected-climax.png").write_bytes(selected_data)
    report = {
        "schema_version": "1.0",
        "phase": "4M",
        "status": "AWAITING_MANUAL_REVIEW" if selected else "ATTEMPT_FAILED",
        "case_id": "youth-torn-paper-boat",
        "role": "CLIMAX",
        "source_base": str(BASE.resolve()),
        "source_base_sha256": hashlib.sha256(base_data).hexdigest(),
        "full_scene_generation_performed": False,
        "local_crop_edits_attempted": 1,
        "attempt": options.attempt,
        "automatic_pass_count": len(candidates),
        "failures": failures,
        "selected": selected,
        "phase4k_cover_digest_preserved": cover_digest,
        "ending_modified": False,
        "source_package_modified": False,
        "checkpoint": str(CHECKPOINT.resolve()),
        "next_attempt_not_started": True,
    }
    write_json(OUTPUT_ROOT / "phase4m-result.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
