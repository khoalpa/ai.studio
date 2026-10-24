from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import torch
from run_phase4lr9r7r3r21r7r4r3_temporal_window_isolation import latent_critic

from ai_story.latent_discontinuity import (
    LatentDiscontinuityDecision,
    PairedLatentDiscontinuityConfig,
    evaluate_paired_latent_discontinuity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R4_R5_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5-terminal-profile-confirmation-v1")
R4_R5_RESULT = R4_R5_ROOT / "phase4lr9r7r3r21r7r4r5-result.json"
BASELINE_CACHE = R4_R5_ROOT / "branch-cache/baseline.pt"
ACTIVE_CACHE = R4_R5_ROOT / "branch-cache/confirmation.pt"
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r1-paired-critic-calibration-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r1-result.json"
EXPECTED_R4_R5_SHA256 = "d12062b2f944b80654455026423e5acf03d913eb1a23331cc8cc2dcbe9ffd9e8"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decision(payload: dict[str, Any]) -> LatentDiscontinuityDecision:
    return LatentDiscontinuityDecision(**payload)


def main() -> None:
    if RESULT_PATH.exists():
        raise RuntimeError("R4-R5-R1 already exists; refusing to overwrite")
    source_digest = sha256(R4_R5_RESULT)
    source = json.loads(R4_R5_RESULT.read_text(encoding="utf-8"))
    if source_digest != EXPECTED_R4_R5_SHA256 or source.get("status") != "FAIL":
        raise RuntimeError("R4-R5 source checkpoint changed")

    baseline_cache = torch.load(BASELINE_CACHE, map_location="cpu", weights_only=False)
    active_cache = torch.load(ACTIVE_CACHE, map_location="cpu", weights_only=False)
    for cached, expected_steps in ((baseline_cache, []), (active_cache, [22, 23])):
        if cached.get("seed") != 420918 or cached.get("active_steps") != expected_steps:
            raise RuntimeError("R4-R5 branch cache metadata changed")
    baseline_absolute = latent_critic(baseline_cache["branch"]["profiles"])
    active_absolute = latent_critic(active_cache["branch"]["profiles"])
    if baseline_absolute != source["baseline"]["latent_critic"]:
        raise RuntimeError("baseline cache does not reproduce R4-R5 critic")
    if active_absolute != source["profiles"]["confirmation"]["latent_critic"]:
        raise RuntimeError("active cache does not reproduce R4-R5 critic")

    config = PairedLatentDiscontinuityConfig()
    paired = evaluate_paired_latent_discontinuity(
        decision(baseline_absolute), decision(active_absolute), config
    )
    active_metrics = source["profiles"]["confirmation"]
    thresholds = source["thresholds"]
    metric_gates = {
        "relative_latent_delta": active_metrics["max_relative_latent_delta"]
        < thresholds["maximum_relative_latent_delta"],
        "update_norm_lower": active_metrics["minimum_update_norm_ratio"]
        >= thresholds["minimum_update_norm_ratio"],
        "update_norm_upper": active_metrics["maximum_update_norm_ratio"]
        <= thresholds["maximum_update_norm_ratio"],
        "final_spatial_ratio": active_metrics["final_spatial_ratio"]
        >= thresholds["minimum_final_spatial_ratio"],
        "all_steps_finite": active_metrics["all_steps_finite"],
        "identity_events_match": active_metrics["identity_events_match"],
        "pre_onset_clean": all(
            item["global_mean_abs_delta"] == 0.0 for item in active_metrics["steps"][:22]
        ),
    }

    clean = LatentDiscontinuityDecision(False, "NO_PERSISTENT_ABSOLUTE_DISCONTINUITY")
    shifted = LatentDiscontinuityDecision(
        True, active_absolute["status"], "row", 22, 38, 1.90658988, 4.62922169
    )
    amplified = LatentDiscontinuityDecision(
        True, active_absolute["status"], "row", 22, 36, 2.00658988, 4.62922169
    )
    controls = {
        "active_only_seam": asdict(
            evaluate_paired_latent_discontinuity(clean, decision(active_absolute), config)
        ),
        "shifted_boundary": asdict(
            evaluate_paired_latent_discontinuity(decision(baseline_absolute), shifted, config)
        ),
        "amplified_ratio": asdict(
            evaluate_paired_latent_discontinuity(decision(baseline_absolute), amplified, config)
        ),
    }
    controls_reject = all(item["blocked"] for item in controls.values())
    passed = not paired.blocked and all(metric_gates.values()) and controls_reject
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R1",
        "status": "PASS_PAIRED_BASELINE_CRITIC_CALIBRATION" if passed else "FAIL",
        "source_checkpoint": {
            "path": str(R4_R5_RESULT.resolve()),
            "sha256": source_digest,
            "status": source["status"],
        },
        "cache_evidence": {
            "baseline_sha256": sha256(BASELINE_CACHE),
            "active_sha256": sha256(ACTIVE_CACHE),
            "seed": 420918,
            "active_steps": [22, 23],
            "recomputed_from_profiles": True,
        },
        "critic_policy": {
            "mode": "PAIRED_SAME_SEED_BASELINE_DIFFERENTIAL",
            "config": asdict(config),
            "unpaired_absolute_critic_remains_authoritative": True,
        },
        "baseline_absolute_critic": baseline_absolute,
        "active_absolute_critic": active_absolute,
        "paired_decision": asdict(paired),
        "metric_gates": metric_gates,
        "negative_controls": controls,
        "negative_controls_reject": controls_reject,
        "locked_profile": {
            "active_blocks": list(range(28, 38)),
            "scale": 0.01,
            "active_steps": [22, 23],
            "seed_evidence": [420917, 420918],
            "status": "LOCKED_PENDING_DECODE_AUTHORIZATION" if passed else "REJECTED",
        },
        "guards": {
            "inference_performed": False,
            "transformer_called": False,
            "scheduler_called": False,
            "vae_called": False,
            "images_created": 0,
            "decode_authorized": False,
            "next_full_scene_attempt_authorized": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
