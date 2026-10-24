from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_story.latent_discontinuity import (
    BoundaryObservation,
    LatentDiscontinuityConfig,
    LatentDiscontinuityDecision,
    PairedLatentDiscontinuityConfig,
    evaluate_latent_discontinuity,
    evaluate_paired_latent_discontinuity,
    observation_from_profile,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
R21_R7_R4_R5_R3_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r1-reject-and-structural-design-v1/"
    "phase4lr9r7r3r21r7r4r5r3r1-result.json"
)
R5_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r5-late-step-decomposition-v1/phase4lr9r7r3r5-result.json"
)
R7_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r7-vae-instrumented-canary-v1/phase4lr9r7r3r7-result.json"
)
R10_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r10-offline-scale-causal-replay-v1/phase4lr9r7r3r10-result.json"
)
R11_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r11-latent-scale025-probe-v1/phase4lr9r7r3r11-result.json"
)
R12_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r12-latent-scale0375-probe-v1/phase4lr9r7r3r12-result.json"
)
R13_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r13-neutral-scale0375-canary-v1/phase4lr9r7r3r13-result.json"
)
R14_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r14-neutral-scale025-canary-v1/phase4lr9r7r3r14-result.json"
)
R15_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r15-vae-precursor-critic-lock-v1/phase4lr9r7r3r15-result.json"
)
R16_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r16-late-tail-adapter-cutoff-v1/phase4lr9r7r3r16-result.json"
)
R17_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r17-midpoint-conditioning-window-v1/phase4lr9r7r3r17-result.json"
)
R18_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r18-delayed-bounded-conditioning-v1/phase4lr9r7r3r18-result.json"
)
R19_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r19-delayed-bounded-canary-v1/phase4lr9r7r3r19-result.json"
)
R19_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r19r1-portrait-gate-calibration-v1/"
    "phase4lr9r7r3r19r1-result.json"
)
R19_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r19r2-positive-profile-lock-v1/phase4lr9r7r3r19r2-result.json"
)
R19_R3_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r19r3-manual-approval-v1/phase4lr9r7r3r19r3-result.json"
)
R20_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r20-locked-climax-v1/phase4lr9r7r3r20-result.json"
)
R20_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r20r1-scale0-control-v1/phase4lr9r7r3r20r1-result.json"
)
R20_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r20r2-bo-only-control-v1/phase4lr9r7r3r20r2-result.json"
)
R20_R3_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r20r3-mother-only-control-v1/phase4lr9r7r3r20r3-result.json"
)
R20_R4_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r20r4-time-multiplexed-control-v1/"
    "phase4lr9r7r3r20r4-result.json"
)
R20_R5_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r20r5-time-multiplexed-lock-v1/"
    "phase4lr9r7r3r20r5-result.json"
)
R21_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21-time-multiplexed-climax-v1/"
    "phase4lr9r7r3r21-result.json"
)
R21_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r1-negative-spatial-conditioning-lock-v1/"
    "phase4lr9r7r3r21r1-result.json"
)
R21_R1_LAYOUT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r1-negative-spatial-conditioning-lock-v1/"
    "regional-spatial-conditioning.json"
)
R21_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r2-regional-attention-dry-run-v1/"
    "phase4lr9r7r3r21r2-result.json"
)
R21_R3_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r3-full-regional-registration-smoke-v1/"
    "phase4lr9r7r3r21r3-result.json"
)
R21_R4_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r4-full-transformer-ab-v1/"
    "phase4lr9r7r3r21r4-result.json"
)
R21_R5_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r5-regional-trajectory-v1/"
    "phase4lr9r7r3r21r5-result.json"
)
R21_R6_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r6-regional-decode-authorization-v1/"
    "phase4lr9r7r3r21r6-result.json"
)
R21_R7_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7-regional-candidate-v1/"
    "phase4lr9r7r3r21r7-result.json"
)
R21_R7_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r1-negative-pose-contract-v1/"
    "phase4lr9r7r3r21r7r1-result.json"
)
R21_R7_R4_R5_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r1-paired-critic-calibration-v1/"
    "phase4lr9r7r3r21r7r4r5r1-result.json"
)
R21_R7_R4_R5_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r2-decode-authorization-v1/"
    "phase4lr9r7r3r21r7r4r5r2-result.json"
)
R21_R7_R4_R5_R3_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3-full-scene-candidate-v1/"
    "phase4lr9r7r3r21r7r4r5r3-result.json"
)


def synthetic_sequence(axis: str, amplitude: float) -> list[BoundaryObservation]:
    baseline = 1.0
    return [
        BoundaryObservation(0, axis, baseline, 0.96, 0.02, 12),
        BoundaryObservation(1, axis, baseline + amplitude, 0.96, 0.02, 31),
        BoundaryObservation(2, axis, baseline + amplitude * 0.99, 0.96, 0.02, 31),
    ]


def test_horizontal_positive_control_blocks() -> None:
    decision = evaluate_latent_discontinuity(synthetic_sequence("row", amplitude=0.25))
    assert decision.blocked is True
    assert decision.axis == "row"
    assert decision.onset_step == 1


def test_vertical_positive_control_blocks() -> None:
    decision = evaluate_latent_discontinuity(synthetic_sequence("column", amplitude=0.3))
    assert decision.blocked is True
    assert decision.axis == "column"


def test_paired_critic_suppresses_only_matching_baseline_feature() -> None:
    baseline = LatentDiscontinuityDecision(
        True,
        "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY",
        "row",
        22,
        36,
        1.904,
        4.65,
    )
    active = LatentDiscontinuityDecision(
        True,
        "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY",
        "row",
        22,
        36,
        1.907,
        4.63,
    )
    decision = evaluate_paired_latent_discontinuity(baseline, active)
    assert decision.blocked is False
    assert decision.status == "MATCHED_BASELINE_STATIC_FEATURE"
    assert decision.ratio_delta == pytest.approx(0.003)
    assert decision.robust_z_delta == pytest.approx(0.02)


@pytest.mark.parametrize(
    ("baseline", "active"),
    [
        (
            LatentDiscontinuityDecision(False, "CLEAN"),
            LatentDiscontinuityDecision(
                True, "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY", "row", 22, 36, 1.9, 4.6
            ),
        ),
        (
            LatentDiscontinuityDecision(
                True, "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY", "row", 22, 36, 1.9, 4.6
            ),
            LatentDiscontinuityDecision(
                True, "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY", "row", 22, 38, 1.9, 4.6
            ),
        ),
        (
            LatentDiscontinuityDecision(
                True, "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY", "row", 22, 36, 1.9, 4.6
            ),
            LatentDiscontinuityDecision(
                True, "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY", "row", 22, 36, 2.0, 4.6
            ),
        ),
    ],
)
def test_paired_critic_keeps_real_regressions_blocked(
    baseline: LatentDiscontinuityDecision,
    active: LatentDiscontinuityDecision,
) -> None:
    decision = evaluate_paired_latent_discontinuity(
        baseline, active, PairedLatentDiscontinuityConfig()
    )
    assert decision.blocked is True


@pytest.mark.parametrize("amplitude", [0.05, 0.1, 0.15, 0.25, 0.5])
def test_controlled_positive_amplitudes(amplitude: float) -> None:
    config = LatentDiscontinuityConfig(minimum_absolute_growth=1.04)
    decision = evaluate_latent_discontinuity(synthetic_sequence("row", amplitude=amplitude), config)
    assert decision.blocked is (amplitude >= 0.25)


def test_transient_spike_does_not_block() -> None:
    sequence = synthetic_sequence("row", amplitude=0.3)
    sequence[-1] = BoundaryObservation(2, "row", 1.0, 0.96, 0.02, 31)
    assert evaluate_latent_discontinuity(sequence).blocked is False


def test_moving_peak_does_not_block() -> None:
    sequence = synthetic_sequence("row", amplitude=0.3)
    sequence[-1] = BoundaryObservation(2, "row", 1.29, 0.96, 0.02, 47)
    assert evaluate_latent_discontinuity(sequence).blocked is False


def test_r5_denominator_collapse_is_locked_negative() -> None:
    payload = json.loads(R5_RESULT.read_text(encoding="utf-8"))
    observations = []
    for step in payload["smoke"]["tail_steps"]:
        boundaries = step["latent_after"]["boundaries"]
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries")):
            observations.append(
                observation_from_profile(step=step["step"], axis=axis, profile=boundaries[key])
            )
    decision = evaluate_latent_discontinuity(observations)
    assert decision.blocked is False
    assert decision.status == "NO_PERSISTENT_ABSOLUTE_DISCONTINUITY"


def test_static_interior_seam_blocks_without_growth() -> None:
    sequence = [
        BoundaryObservation(0, "row", 1.3, 0.96, 0.02, 31),
        BoundaryObservation(1, "row", 1.29, 0.96, 0.02, 31),
    ]
    decision = evaluate_latent_discontinuity(sequence)
    assert decision.blocked is True
    assert decision.status == "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY"
    assert decision.absolute_growth is None


def test_static_edge_seam_does_not_block() -> None:
    sequence = [
        BoundaryObservation(0, "row", 1.3, 0.96, 0.02, 0),
        BoundaryObservation(1, "row", 1.29, 0.96, 0.02, 1),
    ]
    assert evaluate_latent_discontinuity(sequence).blocked is False


def test_r7_static_latent_seam_is_locked_positive() -> None:
    payload = json.loads(R7_RESULT.read_text(encoding="utf-8"))
    observations = []
    for step in payload["generation"]["latent_tail_profiles"]:
        boundaries = step["boundaries"]
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries")):
            observations.append(
                observation_from_profile(step=step["step"], axis=axis, profile=boundaries[key])
            )
    decision = evaluate_latent_discontinuity(observations)
    assert decision.blocked is True
    assert decision.status == "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY"
    assert decision.axis == "row"
    assert decision.boundary_index == 5


def test_scale_ab_causal_replay_locks_ip_adapter() -> None:
    payload = json.loads(R10_RESULT.read_text(encoding="utf-8"))
    analysis = payload["analysis"]
    assert payload["status"] == "PASS"
    assert analysis["scale0_row_persistent_window"] is None
    assert analysis["scale05_row_persistent_window"]["onset_step"] == 18
    assert analysis["scale05_row_indices"] == [5] * 8
    assert analysis["causal_conclusion"] == ("IP_ADAPTER_SCALE_0_5_CREATES_STATIC_ROW_SEAM")


def test_scale025_probe_is_retrospectively_blocked_by_precursor_critic() -> None:
    payload = json.loads(R11_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_CLEAN_SCALE_0_25"
    assert payload["probe"]["ip_adapter_scale"] == 0.25
    assert payload["probe"]["progress_event_count"] == 24
    assert payload["probe"]["images_created"] == 0
    observations = []
    for step in payload["probe"]["tail_profiles"]:
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries")):
            observations.append(
                observation_from_profile(
                    step=step["step"], axis=axis, profile=step["boundaries"][key]
                )
            )
    decision = evaluate_latent_discontinuity(observations)
    assert decision.blocked is True
    assert decision.status == "PERSISTENT_VAE_AMPLIFICATION_PRECURSOR"
    assert decision.boundary_index == 38
    assert payload["guards"]["neutral_generation_authorized"] is False


def test_scale0375_probe_is_retrospectively_blocked_by_precursor_critic() -> None:
    payload = json.loads(R12_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_CLEAN_SCALE_0_375"
    assert payload["probe"]["ip_adapter_scale"] == 0.375
    assert payload["probe"]["progress_event_count"] == 24
    assert payload["probe"]["images_created"] == 0
    observations = []
    for step in payload["probe"]["tail_profiles"]:
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries")):
            observations.append(
                observation_from_profile(
                    step=step["step"], axis=axis, profile=step["boundaries"][key]
                )
            )
    decision = evaluate_latent_discontinuity(observations)
    assert decision.blocked is True
    assert decision.status == "PERSISTENT_VAE_AMPLIFICATION_PRECURSOR"
    assert decision.boundary_index == 35
    assert payload["analysis"]["candidate_upper_bound"] == 0.375
    assert payload["guards"]["phase4n_opened"] is False


def test_scale0375_decoded_canary_is_locked_negative() -> None:
    payload = json.loads(R13_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
    assert payload["attempt_count"] == 1
    assert payload["generation"]["ip_adapter_scale"] == 0.375
    assert payload["generation"]["latent_critic"]["blocked"] is False
    assert payload["generation"]["vae_calls"] == {"forward": 0, "decode": 1}
    assert payload["automatic_qa"]["gate_count"] == 7
    assert set(payload["automatic_qa"]["failed_gate_ids"]) == {
        "anatomy",
        "localized_face_neck_anatomy",
        "single_subject",
    }
    assert payload["candidate_promotable"] is False
    assert payload["next_attempt_started"] is False
    assert payload["phase4n_opened"] is False


def test_scale025_decoded_canary_is_locked_negative() -> None:
    payload = json.loads(R14_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
    assert payload["attempt_count"] == 1
    assert payload["generation"]["ip_adapter_scale"] == 0.25
    assert payload["generation"]["latent_critic"]["blocked"] is False
    assert payload["generation"]["vae_calls"] == {"forward": 0, "decode": 1}
    assert payload["automatic_qa"]["gate_count"] == 7
    assert set(payload["automatic_qa"]["failed_gate_ids"]) == {
        "anatomy",
        "localized_face_neck_anatomy",
        "single_subject",
    }
    assert payload["candidate_promotable"] is False
    assert payload["next_attempt_started"] is False
    assert payload["phase4n_opened"] is False


def test_vae_amplification_precursor_lock_checkpoint() -> None:
    payload = json.loads(R15_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["controls"]["scale0_clean"]["blocked"] is False
    assert payload["controls"]["scale0375_negative"]["status"] == (
        "PERSISTENT_VAE_AMPLIFICATION_PRECURSOR"
    )
    assert payload["controls"]["scale025_negative"]["status"] == (
        "PERSISTENT_VAE_AMPLIFICATION_PRECURSOR"
    )
    assert payload["analysis"]["conclusion"] == ("VAE_AMPLIFICATION_PRECURSOR_LOCKED")
    assert payload["guards"]["image_generation_performed"] is False


def test_late_tail_adapter_cutoff_remains_blocked() -> None:
    payload = json.loads(R16_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_BLOCKED_LATE_TAIL_CUTOFF"
    assert payload["probe"]["ip_adapter_scale_schedule"] == [
        {"effective_step": 0, "scale": 0.25},
        {"effective_step": 16, "scale": 0.0},
    ]
    stored = payload["probe"]["latent_critic"]
    assert stored["blocked"] is True
    assert stored["status"] == "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY"
    assert stored["onset_step"] == 22
    assert stored["boundary_index"] == 38
    observations = []
    for step in payload["probe"]["tail_profiles"]:
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries")):
            observations.append(
                observation_from_profile(
                    step=step["step"], axis=axis, profile=step["boundaries"][key]
                )
            )
    assert evaluate_latent_discontinuity(observations).blocked is True
    assert payload["probe"]["forbidden_calls"] == {
        "vae_forward": 0,
        "vae_decode": 0,
    }
    assert payload["guards"]["image_generation_performed"] is False


def test_midpoint_conditioning_window_remains_blocked() -> None:
    payload = json.loads(R17_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_BLOCKED_MIDPOINT_CUTOFF"
    assert payload["probe"]["ip_adapter_scale_schedule"] == [
        {"effective_step": 0, "scale": 0.25},
        {"effective_step": 8, "scale": 0.0},
    ]
    stored = payload["probe"]["latent_critic"]
    assert stored["blocked"] is True
    assert stored["status"] == "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY"
    assert stored["onset_step"] == 22
    assert stored["boundary_index"] == 38
    assert stored["ratio"] == pytest.approx(1.73856225)
    assert stored["robust_z"] == pytest.approx(3.85094308)
    assert payload["probe"]["progress_event_count"] == 24
    assert payload["probe"]["forbidden_calls"] == {
        "vae_forward": 0,
        "vae_decode": 0,
    }
    assert payload["guards"]["image_generation_performed"] is False


def test_delayed_bounded_conditioning_window_is_clean() -> None:
    payload = json.loads(R18_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_CLEAN_DELAYED_BOUNDED_WINDOW"
    assert payload["probe"]["ip_adapter_scale_schedule"] == [
        {"effective_step": 0, "scale": 0.0},
        {"effective_step": 8, "scale": 0.25},
        {"effective_step": 16, "scale": 0.0},
    ]
    stored = payload["probe"]["latent_critic"]
    assert stored["blocked"] is False
    assert stored["status"] == "NO_PERSISTENT_ABSOLUTE_DISCONTINUITY"
    observations = []
    for step in payload["probe"]["tail_profiles"]:
        for axis, key in (("row", "row_boundaries"), ("column", "column_boundaries")):
            observations.append(
                observation_from_profile(
                    step=step["step"], axis=axis, profile=step["boundaries"][key]
                )
            )
    assert evaluate_latent_discontinuity(observations).blocked is False
    assert payload["probe"]["progress_event_count"] == 24
    assert payload["probe"]["forbidden_calls"] == {
        "vae_forward": 0,
        "vae_decode": 0,
    }
    assert payload["probe"]["images_created"] == 0
    assert payload["guards"]["image_generation_performed"] is False
    assert payload["guards"]["neutral_generation_authorized"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_delayed_bounded_decoded_canary_is_locked_for_review() -> None:
    payload = json.loads(R19_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
    assert payload["attempt_count"] == 1
    assert payload["generation"]["ip_adapter_scale_schedule"] == [
        {"effective_step": 0, "scale": 0.0},
        {"effective_step": 8, "scale": 0.25},
        {"effective_step": 16, "scale": 0.0},
    ]
    assert payload["generation"]["latent_critic"]["blocked"] is False
    assert payload["generation"]["vae_calls"] == {"forward": 0, "decode": 1}
    assert payload["automatic_qa"]["gate_count"] == 7
    assert payload["automatic_qa"]["passed_gate_count"] == 4
    assert set(payload["automatic_qa"]["failed_gate_ids"]) == {
        "anatomy",
        "localized_face_neck_anatomy",
        "single_subject",
    }
    assert payload["candidate_promotable"] is False
    assert payload["next_attempt_started"] is False
    assert payload["climax_generated"] is False
    assert payload["phase4n_opened"] is False


def test_portrait_gate_calibration_separates_controls() -> None:
    payload = json.loads(R19_R1_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["control_assertions"] == {
        "r19_positive_passed": True,
        "r13_negative_rejected": True,
        "r14_negative_rejected": True,
    }
    assert payload["controls"]["r19_positive"]["passed_gate_count"] == 7
    assert payload["controls"]["r19_positive"]["failed_gate_ids"] == []
    assert payload["controls"]["r13_negative"]["failed_gate_ids"] == ["anatomy"]
    assert set(payload["controls"]["r14_negative"]["failed_gate_ids"]) == {
        "anatomy",
        "localized_face_neck_anatomy",
    }
    assert payload["guards"]["image_generation_performed"] is False
    assert payload["guards"]["climax_generated"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_positive_control_profile_lock_waits_for_manual_review() -> None:
    payload = json.loads(R19_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "AWAITING_MANUAL_REVIEW_PROFILE_LOCKED"
    assert payload["positive_control"]["automatic_qa_status"] == "ASSESSED_PASS"
    assert payload["positive_control"]["passed_gate_count"] == 7
    assert payload["positive_control"]["promoted_as_regression_fixture"] is True
    assert payload["positive_control"]["promoted_to_production"] is False
    assert set(payload["negative_controls"]) == {"r13_negative", "r14_negative"}
    assert payload["locked_profile"]["ip_adapter_scale_schedule"] == [
        {"effective_step": 0, "scale": 0.0},
        {"effective_step": 8, "scale": 0.25},
        {"effective_step": 16, "scale": 0.0},
    ]
    assert payload["manual_review"] == {
        "required": True,
        "status": "PENDING",
        "climax_generation_authorized": False,
    }
    assert payload["guards"]["image_generation_performed"] is False
    assert payload["guards"]["climax_generated"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_manual_approval_authorizes_exactly_one_climax_attempt() -> None:
    payload = json.loads(R19_R3_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "MANUAL_APPROVE_ONE_CLIMAX_ATTEMPT_AUTHORIZED"
    assert payload["manual_review"]["status"] == "MANUAL_APPROVE"
    assert all(status == "PASS" for status in payload["manual_review"]["checklist"].values())
    assert payload["authorization"] == {
        "target": "youth-torn-paper-boat/climax.png",
        "maximum_attempts": 1,
        "attempts_consumed": 0,
        "full_scene_only": True,
        "profile_override_allowed": False,
        "automatic_qa_required": True,
        "manual_review_after_generation_required": True,
        "authorized": True,
    }
    assert payload["guards"]["image_generation_performed"] is False
    assert payload["guards"]["climax_generated"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_locked_climax_attempt_is_blocked_before_decode() -> None:
    payload = json.loads(R20_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "AUTO_BLOCKED_PRE_DECODE"
    assert payload["attempt_count"] == 1
    assert payload["authorization_consumed"] is True
    assert payload["attempts_consumed"] == 1
    assert payload["candidate_path"] is None
    assert payload["generation"]["latent_critic"]["status"] == (
        "PERSISTENT_VAE_AMPLIFICATION_PRECURSOR"
    )
    assert payload["generation"]["latent_critic"]["axis"] == "row"
    assert payload["generation"]["latent_critic"]["onset_step"] == 22
    assert payload["generation"]["latent_critic"]["boundary_index"] == 50
    assert payload["generation"]["vae_decode_calls"] == 0
    assert payload["generation"]["images_created"] == 0
    assert payload["next_attempt_started"] is False
    assert payload["phase4n_opened"] is False


def test_full_scene_scale0_control_is_clean_and_latent_only() -> None:
    payload = json.loads(R20_R1_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_CLEAN_SCALE0_CONTROL"
    assert payload["generation"]["ip_adapter_scale_schedule"] == [
        {"effective_step": 0, "scale": 0.0}
    ]
    assert payload["generation"]["latent_critic"] == {
        "blocked": False,
        "status": "NO_PERSISTENT_ABSOLUTE_DISCONTINUITY",
        "axis": None,
        "onset_step": None,
        "boundary_index": None,
        "ratio": None,
        "robust_z": None,
        "absolute_growth": None,
    }
    assert payload["generation"]["vae_calls"] == {"forward": 0, "decode": 0}
    assert payload["generation"]["images_created"] == 0
    assert payload["causal_conclusion"] == (
        "MULTI_REFERENCE_IDENTITY_CONDITIONING_CAUSES_PRECURSOR"
    )
    assert payload["guards"]["additional_generation_authorized"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_bo_only_delayed_window_is_clean_and_isolates_mean_aggregation() -> None:
    payload = json.loads(R20_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_CLEAN_BO_ONLY_DELAYED_WINDOW"
    assert payload["generation"]["identity_conditioning"] == "BO_ONLY"
    assert payload["generation"]["ip_adapter_scale_schedule"] == [
        {"effective_step": 0, "scale": 0.0},
        {"effective_step": 8, "scale": 0.25},
        {"effective_step": 16, "scale": 0.0},
    ]
    assert payload["generation"]["latent_critic"]["blocked"] is False
    assert payload["generation"]["latent_critic"]["status"] == (
        "NO_PERSISTENT_ABSOLUTE_DISCONTINUITY"
    )
    assert payload["generation"]["vae_calls"] == {"forward": 0, "decode": 0}
    assert payload["generation"]["images_created"] == 0
    assert payload["causal_conclusion"] == ("MEAN_TWO_REFERENCE_AGGREGATION_CAUSES_PRECURSOR")
    assert payload["guards"]["additional_generation_authorized"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_mother_only_delayed_window_confirms_mean_aggregation_cause() -> None:
    payload = json.loads(R20_R3_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_CLEAN_MOTHER_ONLY_DELAYED_WINDOW"
    assert payload["generation"]["identity_conditioning"] == "ME_ONLY"
    assert payload["generation"]["ip_adapter_scale_schedule"] == [
        {"effective_step": 0, "scale": 0.0},
        {"effective_step": 8, "scale": 0.25},
        {"effective_step": 16, "scale": 0.0},
    ]
    assert payload["generation"]["latent_critic"]["blocked"] is False
    assert payload["generation"]["latent_critic"]["status"] == (
        "NO_PERSISTENT_ABSOLUTE_DISCONTINUITY"
    )
    assert payload["generation"]["vae_calls"] == {"forward": 0, "decode": 0}
    assert payload["generation"]["images_created"] == 0
    assert payload["causal_conclusion"] == (
        "MEAN_TWO_REFERENCE_AGGREGATION_CAUSES_PRECURSOR_CONFIRMED"
    )
    assert payload["guards"]["additional_generation_authorized"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_time_multiplexed_two_identity_conditioning_is_latent_safe() -> None:
    payload = json.loads(R20_R4_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_CLEAN_TIME_MULTIPLEXED_TWO_IDENTITY"
    assert payload["generation"]["identity_conditioning"] == ("TIME_MULTIPLEXED_BO_ME")
    assert payload["generation"]["identity_schedule"] == [
        {"effective_step": 0, "identity": "BO"},
        {"effective_step": 12, "identity": "ME"},
    ]
    assert payload["generation"]["ip_adapter_scale_schedule"] == [
        {"effective_step": 0, "scale": 0.0},
        {"effective_step": 8, "scale": 0.25},
        {"effective_step": 16, "scale": 0.0},
    ]
    assert payload["generation"]["latent_critic"]["blocked"] is False
    assert payload["generation"]["vae_calls"] == {"forward": 0, "decode": 0}
    assert payload["generation"]["images_created"] == 0
    assert payload["causal_conclusion"] == (
        "TIME_MULTIPLEXED_TWO_IDENTITY_CONDITIONING_IS_LATENT_SAFE"
    )
    assert payload["guards"]["additional_generation_authorized"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_time_multiplexed_profile_reauthorizes_one_attempt_only() -> None:
    payload = json.loads(R20_R5_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_ONE_FULL_SCENE_ATTEMPT_REAUTHORIZED"
    assert payload["prior_attempt"]["authorization_consumed"] is True
    assert payload["prior_attempt"]["candidate_created"] is False
    assert payload["causal_evidence"]["status"] == ("PASS_CLEAN_TIME_MULTIPLEXED_TWO_IDENTITY")
    assert payload["locked_profile"]["identity_schedule"] == [
        {"effective_step": 0, "identity": "BO"},
        {"effective_step": 12, "identity": "ME"},
    ]
    assert payload["authorization"] == {
        "target": "youth-torn-paper-boat/climax.png",
        "maximum_attempts": 1,
        "attempts_consumed": 0,
        "full_scene_only": True,
        "time_multiplexed_identity_required": True,
        "profile_override_allowed": False,
        "automatic_qa_required": True,
        "manual_review_after_generation_required": True,
        "authorized": True,
    }
    assert len(payload["required_image_gates"]) == 9
    assert payload["guards"]["image_generation_performed"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_time_multiplexed_climax_is_rejected_on_structural_image_gates() -> None:
    payload = json.loads(R21_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
    assert payload["attempt_count"] == 1
    assert payload["authorization_consumed"] is True
    assert payload["attempts_consumed"] == 1
    assert payload["candidate_sha256"] == (
        "ef78fd36781dfa3ffb2f32874da246564097ceb90c0e6ef66c0aa3da2e2bd1d6"
    )
    assert payload["generation"]["identity_conditioning"] == ("TIME_MULTIPLEXED_BO_ME")
    assert payload["generation"]["identity_schedule"] == [
        {"effective_step": 0, "identity": "BO"},
        {"effective_step": 12, "identity": "ME"},
    ]
    assert payload["generation"]["latent_critic"]["blocked"] is False
    assert payload["generation"]["latent_critic"]["status"] == (
        "NO_PERSISTENT_ABSOLUTE_DISCONTINUITY"
    )
    assert payload["generation"]["vae_calls"] == {"forward": 0, "decode": 1}
    assert payload["generation"]["images_created"] == 1
    assert payload["automatic_qa"]["gate_count"] == 9
    assert payload["automatic_qa"]["passed_gate_count"] == 4
    assert set(payload["automatic_qa"]["failed_gate_ids"]) == {
        "hand_anatomy_gate",
        "hand_prop_contact_gate",
        "paper_boat_shape_scale_gate",
        "two_visible_faces_cast_gate",
        "exactly_two_interaction_hands_gate",
    }
    assert payload["automatic_qa"]["gates"]["bo_identity"]["status"] == "PASS"
    assert payload["automatic_qa"]["gates"]["me_identity"]["status"] == "PASS"
    assert payload["candidate_promotable"] is False
    assert payload["manual_review_required"] is True
    assert payload["next_attempt_started"] is False
    assert payload["phase4n_opened"] is False


def test_r21_negative_fixture_and_regional_spatial_contract_are_locked() -> None:
    payload = json.loads(R21_R1_RESULT.read_text(encoding="utf-8"))
    layout = json.loads(R21_R1_LAYOUT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_NEGATIVE_LOCK_AND_SPATIAL_DESIGN"
    assert payload["negative_fixture"]["sha256"] == (
        "ef78fd36781dfa3ffb2f32874da246564097ceb90c0e6ef66c0aa3da2e2bd1d6"
    )
    assert payload["negative_fixture"]["all_five_structural_gates_reject"] is True
    assert set(payload["negative_fixture"]["failed_gate_ids"]) == {
        "hand_anatomy_gate",
        "hand_prop_contact_gate",
        "paper_boat_shape_scale_gate",
        "two_visible_faces_cast_gate",
        "exactly_two_interaction_hands_gate",
    }
    assert all(payload["regional_spatial_conditioning"]["validation"].values())
    assert layout["conditioning"]["identity_mode"] == ("REGIONAL_TIME_MULTIPLEXED_BO_ME")
    assert layout["regions"]["bo_identity"]["side"] == "left"
    assert layout["regions"]["mother_identity"]["side"] == "right"
    assert layout["regions"]["interaction"]["required_hand_count"] == 2
    assert layout["regions"]["interaction"]["required_prop_count"] == 1
    assert layout["conditioning"]["spatial_policy"] == {
        "bo_tokens_attend_only_to": "bo_identity",
        "mother_tokens_attend_only_to": "mother_identity",
        "identity_mask_overlap_allowed": False,
        "interaction_roi_receives_identity_tokens": False,
        "interaction_roi_control": "POSE_AND_GEOMETRY_ONLY",
    }
    assert payload["guards"]["image_generation_performed"] is False
    assert payload["guards"]["next_full_scene_attempt_authorized"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_regional_attention_is_native_equivalent_and_leak_free() -> None:
    payload = json.loads(R21_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_REGIONAL_ATTENTION_DRY_RUN"
    assert payload["transformer_mapping"] == {
        "image_size": 512,
        "vae_scale_factor": 8,
        "latent_size": [64, 64],
        "patch_size": 2,
        "query_grid": [32, 32],
        "query_token_count": 1024,
        "block_index": 0,
        "block_count": 38,
    }
    assert payload["regional_masks"] == {
        "sampling": "TOKEN_CENTER_HALF_OPEN_BOX",
        "bo_active_tokens": 317,
        "mother_active_tokens": 317,
        "interaction_tokens": 56,
        "identity_overlap_tokens": 0,
        "interaction_subtracted_from_identity_masks": True,
    }
    dry_run = payload["attention_dry_run"]
    assert dry_run["full_mask_native_max_abs_error"] <= dry_run["tolerance"]
    assert all(
        error <= dry_run["tolerance"] for error in dry_run["context_max_abs_errors"].values()
    )
    for branch in ("bo_step_10", "mother_step_14"):
        metrics = dry_run[branch]
        assert metrics["inside_effect_nonzero"] is True
        assert metrics["outside_leakage_below_tolerance"] is True
        assert metrics["interaction_leakage_below_tolerance"] is True
        assert metrics["outside_max_abs_delta"] == 0.0
        assert metrics["interaction_max_abs_delta"] == 0.0
    assert payload["guards"]["single_transformer_attention_block_only"] is True
    assert payload["guards"]["denoise_performed"] is False
    assert payload["guards"]["image_generation_performed"] is False
    assert payload["guards"]["next_full_scene_attempt_authorized"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_all_sd35_ip_adapter_blocks_register_regional_processor() -> None:
    payload = json.loads(R21_R3_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_FULL_38_BLOCK_REGISTRATION"
    smoke = payload["registration_smoke"]
    assert smoke["transformer_blocks"] == 38
    assert smoke["attention_processors"] == 42
    assert smoke["native_ip_processors_before"] == 38
    assert smoke["regional_ip_processors_after"] == 38
    assert smoke["non_ip_processors_preserved"] == 4
    assert smoke["registered_layer_indices"] == list(range(38))
    assert all(
        registration["base_object_preserved"]
        and registration["parameter_identity_preserved"]
        and registration["dtype"] == ["torch.float16"]
        and registration["device"] == ["cpu"]
        and registration["scale"] == 0.25
        and registration["accepts_regional_attention_mask"]
        for registration in smoke["registrations"]
    )
    assert smoke["kwargs_routing"] == {
        "transformer_accepts_joint_attention_kwargs": True,
        "transformer_passes_kwargs_to_block": True,
        "block_passes_kwargs_to_attention": True,
        "regional_kwarg_name": "regional_attention_mask",
    }
    assert smoke["cuda_initialized"] is False
    assert payload["guards"]["transformer_forward_called"] is False
    assert payload["guards"]["image_generation_performed"] is False
    assert payload["guards"]["next_full_scene_attempt_authorized"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_full_transformer_regional_identity_stays_spatially_dominant() -> None:
    payload = json.loads(R21_R4_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_FULL_TRANSFORMER_SINGLE_STEP_AB"
    assert payload["fixed_latent_shape"] == [1, 16, 64, 64]
    assert payload["query_grid"] == [32, 32]
    assert payload["scale"] == 0.25
    assert set(payload["branches"]) == {"BO", "ME"}
    for identity, expected_step in (("BO", 10), ("ME", 14)):
        branch = payload["branches"][identity]
        assert branch["step_index"] == expected_step
        assert len(branch["block_metrics"]) == 38
        assert [item["block"] for item in branch["block_metrics"]] == list(range(38))
        assert min(item["localization_ratio"] for item in branch["block_metrics"]) > 1.5
        assert max(item["interaction_to_inside_ratio"] for item in branch["block_metrics"]) < 0.61
        assert branch["final_output_mean_abs_delta"] > 0
        assert branch["all_blocks_finite"] is True
    assert payload["guards"]["full_transformer_forward_count"] == 4
    assert payload["guards"]["scheduler_step_called"] is False
    assert payload["guards"]["trajectory_run"] is False
    assert payload["guards"]["vae_called"] is False
    assert payload["guards"]["image_generation_performed"] is False
    assert payload["guards"]["next_full_scene_attempt_authorized"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_regional_time_multiplexed_trajectory_is_clean_and_latent_only() -> None:
    payload = json.loads(R21_R5_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_CLEAN_REGIONAL_TIME_MULTIPLEXED_TRAJECTORY"
    assert payload["baseline_a"]["status"] == "PASS_CLEAN_SCALE0_CONTROL"
    assert payload["regional_b"]["events"] == [
        {"effective_step": 0, "scale": 0.0, "identity": "BO"},
        {"effective_step": 8, "scale": 0.25, "identity": "BO"},
        {"effective_step": 12, "scale": 0.25, "identity": "ME"},
        {"effective_step": 16, "scale": 0.0, "identity": "ME"},
    ]
    assert payload["regional_b"]["profile_count"] == 24
    assert payload["regional_b"]["latent_critic"]["blocked"] is False
    assert payload["regional_b"]["latent_critic"]["status"] == (
        "NO_PERSISTENT_ABSOLUTE_DISCONTINUITY"
    )
    assert payload["guards"]["vae_calls"] == {"forward": 0, "decode": 0}
    assert payload["guards"]["images_created"] == 0
    assert payload["guards"]["next_decode_authorized"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_regional_profile_authorizes_exactly_one_decode_attempt() -> None:
    payload = json.loads(R21_R6_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_ONE_FULL_SCENE_DECODE_ATTEMPT_AUTHORIZED"
    assert len(payload["evidence_locks"]) == 5
    assert len(payload["required_image_gates"]) == 9
    assert payload["authorization"] == {
        "target": "youth-torn-paper-boat/climax.png",
        "maximum_trajectory_attempts": 1,
        "maximum_vae_decodes": 1,
        "attempts_consumed": 0,
        "regional_time_multiplexing_required": True,
        "spatial_contract_override_allowed": False,
        "profile_override_allowed": False,
        "automatic_retry_allowed": False,
        "automatic_qa_required": True,
        "manual_review_required": True,
        "authorized": True,
    }
    closure = payload["phase4l_closure"]
    assert closure["status"] == "OPEN_PENDING_AUTHORIZED_ATTEMPT"
    assert closure["requirements"][0]["status"] == "PASS"
    assert all(item["status"] == "PENDING" for item in closure["requirements"][1:])
    assert closure["all_requirements_satisfied"] is False
    assert payload["guards"]["image_generation_performed"] is False
    assert payload["guards"]["phase4l_closed"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_regional_candidate_consumes_one_attempt_and_is_not_promotable() -> None:
    payload = json.loads(R21_R7_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
    assert payload["attempt_count"] == 1
    assert payload["authorization_consumed"] is True
    assert payload["attempts_consumed"] == 1
    assert payload["candidate_sha256"] == (
        "bcd0ae3e8a1a0b4299ab1f35abfcac71dcbafe9e8c075740d5d02b5522d4c3ca"
    )
    generation = payload["generation"]
    assert generation["events"] == [
        {"effective_step": 0, "scale": 0.0, "identity": "BO"},
        {"effective_step": 8, "scale": 0.25, "identity": "BO"},
        {"effective_step": 12, "scale": 0.25, "identity": "ME"},
        {"effective_step": 16, "scale": 0.0, "identity": "ME"},
    ]
    assert generation["latent_critic"]["blocked"] is False
    assert generation["latent_critic"]["status"] == ("NO_PERSISTENT_ABSOLUTE_DISCONTINUITY")
    assert generation["vae_calls"] == {"forward": 0, "decode": 1}
    assert generation["images_created"] == 1
    qa = payload["automatic_qa"]
    assert qa["status"] == "ASSESSED_FAIL"
    assert qa["gate_count"] == 9
    assert qa["passed_gate_count"] == 4
    assert set(qa["failed_gate_ids"]) == {
        "hand_anatomy_gate",
        "hand_prop_contact_gate",
        "paper_boat_shape_scale_gate",
        "two_visible_faces_cast_gate",
        "exactly_two_interaction_hands_gate",
    }
    assert qa["gates"]["bo_identity"]["status"] == "PASS"
    assert qa["gates"]["me_identity"]["status"] == "PASS"
    assert payload["candidate_promotable"] is False
    assert payload["next_attempt_started"] is False
    assert payload["phase4l_closed"] is False
    assert payload["phase4n_opened"] is False
    assert payload["source_package_modified"] is False
    assert payload["guards"]["automatic_retry_started"] is False


def test_r7_negative_and_explicit_pose_composition_contract_are_locked() -> None:
    payload = json.loads(R21_R7_R1_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_NEGATIVE_LOCK_AND_EXPLICIT_CONTROL_DESIGN"
    fixture = payload["negative_fixture"]
    assert fixture["sha256"] == ("bcd0ae3e8a1a0b4299ab1f35abfcac71dcbafe9e8c075740d5d02b5522d4c3ca")
    assert fixture["critic_status"] == "ASSESSED_FAIL"
    assert fixture["all_five_structural_gates_reject"] is True
    assert set(fixture["failed_gate_ids"]) == {
        "hand_anatomy_gate",
        "hand_prop_contact_gate",
        "paper_boat_shape_scale_gate",
        "two_visible_faces_cast_gate",
        "exactly_two_interaction_hands_gate",
    }
    control = payload["explicit_control"]
    assert all(control["validation"].values())
    assert control["ready_for_integration_dry_run"] is True
    assert control["not_yet_wired_to_transformer"] is True
    assert payload["diagnosis"] == {
        "regional_identity_succeeded": True,
        "structural_control_failed": True,
        "root_boundary": (
            "Regional IP-Adapter masks constrain identity influence but do not "
            "hard-constrain framing, limb topology, contact, or prop geometry."
        ),
    }
    guards = payload["guards"]
    assert guards["image_generation_performed"] is False
    assert guards["inference_performed"] is False
    assert guards["transformer_called"] is False
    assert guards["vae_called"] is False
    assert guards["new_decode_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_summary_only_checkpoint_is_non_authoritative() -> None:
    decision = evaluate_latent_discontinuity([])
    assert decision.blocked is False
    assert decision.status == "INSUFFICIENT_ABSOLUTE_EVIDENCE"


def test_invalid_single_frame_persistence_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        evaluate_latent_discontinuity(
            synthetic_sequence("row", amplitude=0.3),
            LatentDiscontinuityConfig(persistence_steps=1),
        )


def test_r4_r5_r1_reclassifies_only_matched_same_seed_baseline_feature() -> None:
    payload = json.loads(R21_R7_R4_R5_R1_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_PAIRED_BASELINE_CRITIC_CALIBRATION"
    assert payload["source_checkpoint"]["sha256"] == (
        "d12062b2f944b80654455026423e5acf03d913eb1a23331cc8cc2dcbe9ffd9e8"
    )
    assert payload["cache_evidence"]["seed"] == 420918
    assert payload["cache_evidence"]["active_steps"] == [22, 23]
    assert payload["cache_evidence"]["recomputed_from_profiles"] is True
    policy = payload["critic_policy"]
    assert policy["mode"] == "PAIRED_SAME_SEED_BASELINE_DIFFERENTIAL"
    assert policy["unpaired_absolute_critic_remains_authoritative"] is True
    assert policy["config"] == {
        "maximum_ratio_delta": 0.02,
        "maximum_robust_z_delta": 0.25,
        "onset_step_tolerance": 0,
        "boundary_index_tolerance": 0,
    }
    paired = payload["paired_decision"]
    assert paired["blocked"] is False
    assert paired["status"] == "MATCHED_BASELINE_STATIC_FEATURE"
    assert paired["ratio_delta"] < policy["config"]["maximum_ratio_delta"]
    assert paired["robust_z_delta"] < policy["config"]["maximum_robust_z_delta"]
    assert paired["onset_step_delta"] == 0
    assert paired["boundary_index_delta"] == 0
    assert all(payload["metric_gates"].values())
    assert payload["negative_controls_reject"] is True
    assert all(control["blocked"] for control in payload["negative_controls"].values())
    assert payload["locked_profile"] == {
        "active_blocks": list(range(28, 38)),
        "scale": 0.01,
        "active_steps": [22, 23],
        "seed_evidence": [420917, 420918],
        "status": "LOCKED_PENDING_DECODE_AUTHORIZATION",
    }
    guards = payload["guards"]
    assert guards["inference_performed"] is False
    assert guards["transformer_called"] is False
    assert guards["scheduler_called"] is False
    assert guards["vae_called"] is False
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["next_full_scene_attempt_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r2_authorizes_exactly_one_locked_decode_attempt() -> None:
    payload = json.loads(R21_R7_R4_R5_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_ONE_FULL_SCENE_DECODE_ATTEMPT_AUTHORIZED"
    assert set(payload["evidence_locks"]) == {
        "r4_r4_profile_selection",
        "r4_r5_independent_confirmation",
        "r4_r5_r1_paired_calibration",
        "spatial_contract",
        "explicit_control",
        "paired_critic",
        "bo_reference",
        "mother_reference",
    }
    profile = payload["locked_profile"]
    assert profile["seed"] == 420917
    assert profile["resolution"] == [512, 512]
    assert profile["pipeline_dtype"] == "torch.bfloat16"
    assert profile["steps"] == 24
    assert profile["guidance_scale"] == 5.0
    assert profile["identity_mode"] == "REGIONAL_TIME_MULTIPLEXED_BO_ME"
    assert profile["explicit_control"] == {
        "active_blocks": list(range(28, 38)),
        "scale": 0.01,
        "active_steps": [22, 23],
    }
    assert profile["paired_critic"]["mode"] == ("PAIRED_SAME_SEED_BASELINE_DIFFERENTIAL")
    assert profile["paired_critic"]["unpaired_absolute_critic_remains_authoritative"] is True
    assert profile["automatic_retry_allowed"] is False
    assert payload["locked_profile_sha256"] == (
        "512096d1b73e0599a7fbe6b629d2c315474f2593cae203fb3b97210eee8f9d13"
    )
    assert len(payload["required_image_gates"]) == 9
    assert payload["required_latent_gates"] == [
        "paired_latent_discontinuity_gate",
        "vae_amplification_precursor_gate",
    ]
    assert payload["authorization"] == {
        "target": "youth-torn-paper-boat/climax.png",
        "maximum_trajectory_attempts": 1,
        "maximum_vae_decodes": 1,
        "attempts_consumed": 0,
        "profile_override_allowed": False,
        "critic_policy_override_allowed": False,
        "automatic_retry_allowed": False,
        "automatic_qa_required": True,
        "manual_review_required": True,
        "authorized": True,
    }
    closure = payload["phase4l_closure"]
    assert closure["status"] == "OPEN_PENDING_AUTHORIZED_ATTEMPT"
    assert closure["requirements"][0]["status"] == "PASS"
    assert all(item["status"] == "PENDING" for item in closure["requirements"][1:])
    assert closure["all_requirements_satisfied"] is False
    assert all(value is False for value in payload["guards"].values())


def test_r4_r5_r3_consumes_authorization_and_rejects_structural_failures() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
    assert payload["attempt"] == 1
    assert payload["attempt_count"] == 1
    assert payload["authorization_consumed"] is True
    assert payload["attempts_consumed"] == 1
    assert payload["authorization_sha256"] == (
        "2029eff8e1429d13a05b6c93f728159defdeae2b517924b2eeb55ba5f6df60fd"
    )
    assert payload["locked_profile_sha256"] == (
        "512096d1b73e0599a7fbe6b629d2c315474f2593cae203fb3b97210eee8f9d13"
    )
    assert payload["candidate_sha256"] == (
        "21624955f0fa89b9ddb410232a2d510927b0264f7d0b419d02f829baf85f84c7"
    )
    generation = payload["generation"]
    assert generation["trajectory_completed_before_recovery"] is True
    assert generation["trajectory_rerun"] is False
    assert generation["recovered_from_locked_terminal_cache"] is True
    assert generation["explicit_control"] == {
        "active_blocks": list(range(28, 38)),
        "scale": 0.01,
        "active_steps": [22, 23],
    }
    assert generation["absolute_latent_critic"]["blocked"] is False
    assert generation["paired_latent_critic"]["blocked"] is False
    assert generation["vae_calls"] == {"forward": 0, "decode": 1}
    assert generation["images_created"] == 1

    qa = payload["automatic_qa"]
    assert qa["status"] == "ASSESSED_FAIL"
    assert qa["gate_count"] == 9
    assert qa["passed_gate_count"] == 4
    assert set(qa["failed_gate_ids"]) == {
        "hand_anatomy_gate",
        "hand_prop_contact_gate",
        "paper_boat_shape_scale_gate",
        "two_visible_faces_cast_gate",
        "exactly_two_interaction_hands_gate",
    }
    assert qa["gates"]["photorealism_fidelity_gate"]["status"] == "PASS"
    assert qa["gates"]["bo_identity"]["status"] == "PASS"
    assert qa["gates"]["me_identity"]["status"] == "PASS"
    assert qa["gates"]["text_artifact"]["status"] == "PASS"
    assert all(gate["status"] == "PASS" for gate in payload["latent_qa"].values())
    assert payload["all_automatic_gates_pass"] is False
    assert payload["candidate_promotable"] is False
    assert payload["manual_review_required"] is True
    assert payload["manual_review_status"] == "PENDING"
    assert payload["next_attempt_started"] is False
    assert payload["phase4l_closed"] is False
    assert payload["phase4n_opened"] is False
    assert payload["source_package_modified"] is False
    assert payload["guards"] == {
        "exactly_one_trajectory_attempt_consumed": True,
        "exactly_one_vae_decode": True,
        "profile_override_used": False,
        "critic_policy_override_used": False,
        "automatic_retry_started": False,
    }


def test_r4_r5_r3_r1_locks_rejection_and_structural_spike_contract() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R1_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_REJECTED_ATTEMPT_AND_STRUCTURAL_SPIKE_DESIGN"
    assert payload["manual_disposition"] == {
        "status": "REJECTED",
        "candidate_promotable": False,
        "reason": "FIVE_MANDATORY_STRUCTURAL_IMAGE_GATES_FAILED",
    }
    fixture = payload["negative_fixture"]
    assert fixture["sha256"] == ("21624955f0fa89b9ddb410232a2d510927b0264f7d0b419d02f829baf85f84c7")
    assert fixture["all_five_structural_gates_must_reject"] is True
    assert len(fixture["failed_gate_ids"]) == 5
    assert payload["diagnosis"]["latent_safety"] == "PASS"
    assert payload["diagnosis"]["structural_conditioning"] == "FAIL"

    contract_path = Path(payload["structural_conditioning"]["contract_path"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["identity_schedule_unchanged"] == [
        {"step": 0, "identity": "bo", "scale": 0.0},
        {"step": 8, "identity": "bo", "scale": 0.25},
        {"step": 12, "identity": "mother", "scale": 0.25},
        {"step": 16, "identity": "mother", "scale": 0.0},
    ]
    assert [stage["id"] for stage in contract["stages"]] == [
        "early_framing_cast",
        "middle_pose_contact",
        "terminal_refinement",
    ]
    assert contract["isolation"]["zero_control_bitwise_parity_required"] is True
    assert contract["progression"][0] == "registration_and_zero_parity_dry_run"
    assert contract["generation_authorized"] is False
    assert payload["phase4l_closure"]["all_requirements_satisfied"] is False
    guards = payload["guards"]
    assert guards["images_created"] == 0
    assert all(value is False for key, value in guards.items() if key != "images_created")
