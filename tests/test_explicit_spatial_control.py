from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from ai_story.explicit_spatial_control import (
    ExplicitControlRegistration,
    ExplicitSpatialControlResidual,
    StagedExplicitControlRegistration,
    raster_controls_to_tokens,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
R21_R7_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r2-explicit-control-dry-run-v1/"
    "phase4lr9r7r3r21r7r2-result.json"
)
R21_R7_R3_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r3-full-control-registration-v1/"
    "phase4lr9r7r3r21r7r3-result.json"
)
R21_R7_R4_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4-full-transformer-control-ab-v1/"
    "phase4lr9r7r3r21r7r4-result.json"
)
R21_R7_R4_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r1-block-window-isolation-v1/"
    "phase4lr9r7r3r21r7r4r1-result.json"
)
R21_R7_R4_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r2-late-window-trajectory-v1/"
    "phase4lr9r7r3r21r7r4r2-result.json"
)
R21_R7_R4_R3_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r3-temporal-window-isolation-v1/"
    "phase4lr9r7r3r21r7r4r3-result.json"
)
R21_R7_R4_R4_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r4-late-tail-micro-window-isolation-v1/"
    "phase4lr9r7r3r21r7r4r4-result.json"
)
R21_R7_R4_R5_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5-terminal-profile-confirmation-v1/"
    "phase4lr9r7r3r21r7r4r5-result.json"
)
R21_R7_R4_R5_R3_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r2-structural-registration-v1/"
    "phase4lr9r7r3r21r7r4r5r3r2-result.json"
)
R21_R7_R4_R5_R3_R3_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r3-full-transformer-structural-ab-v1/"
    "phase4lr9r7r3r21r7r4r5r3r3-result.json"
)
R21_R7_R4_R5_R3_R4_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r4-pose-contact-isolation-v1/"
    "phase4lr9r7r3r21r7r4r5r3r4-result.json"
)
R21_R7_R4_R5_R3_R5_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r5-combined-contact-roi-v1/"
    "phase4lr9r7r3r21r7r4r5r3r5-result.json"
)
R21_R7_R4_R5_R3_R6_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r6-structural-trajectory-v1/"
    "phase4lr9r7r3r21r7r4r5r3r6-result.json"
)
R21_R7_R4_R5_R3_R7_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r7-scale-terminal-isolation-v1/"
    "phase4lr9r7r3r21r7r4r5r3r7-result.json"
)
R21_R7_R4_R5_R3_R8_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r8-precision-isolation-v1/"
    "phase4lr9r7r3r21r7r4r5r3r8-result.json"
)
R21_R7_R4_R5_R3_R9_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r9-error-feedback-isolation-v1/"
    "phase4lr9r7r3r21r7r4r5r3r9-result.json"
)
R21_R7_R4_R5_R3_R10_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10-error-feedback-trajectory-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10-result.json"
)
R21_R7_R4_R5_R3_R10_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r1-step-bounded-feedback-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r1-result.json"
)
R21_R7_R4_R5_R3_R10_R1_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r1r1-clean-scale-revalidation-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r1r1-result.json"
)
R21_R7_R4_R5_R3_R10_R1_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r1r2-schedule-profile-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r1r2-result.json"
)
R21_R7_R4_R5_R3_R10_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2-schedule-trajectory-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r1-middle-cutoff-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r1-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r2-early-cutoff-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r2-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R3_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r3-channel-attribution-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r3-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R4_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r4-early-block-isolation-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r4-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R5_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r5-early-fine-isolation-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r5-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R6_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6-waiver-lock-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R6_R1_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r1-replay-decode-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r1-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R6_R2_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r2-reject-geometry-lock-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r2-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R6_R3_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r3-geometry-dry-run-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r3-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R6_R4_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r4-geometry-trajectory-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r4-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R6_R5_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r5-mother-gain-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r5-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R6_R6_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r6-bf16-gain-probe-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r6-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R6_R7_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r7-real-transformer-gain-ab-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r7-result.json"
)
R21_R7_R4_R5_R3_R10_R2_R6_R8_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r8-scheduler-microtrajectory-ab-v1/"
    "phase4lr9r7r3r21r7r4r5r3r10r2r6r8-result.json"
)
PHASE4L_LOWERED_THRESHOLD_CLOSURE_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/phase4l-lowered-threshold-closure-v1/"
    "phase4l-closure-result.json"
)


class DummyBlock(torch.nn.Module):
    def forward(self, hidden_states: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return hidden_states[:, :1], hidden_states


class DummyTransformer(torch.nn.Module):
    def __init__(self, count: int) -> None:
        super().__init__()
        self.transformer_blocks = torch.nn.ModuleList(DummyBlock() for _ in range(count))


def test_raster_controls_map_to_expected_token_grid() -> None:
    controls = torch.zeros((1, 3, 8, 8))
    controls[:, 0, :4, :4] = 1.0
    tokens = raster_controls_to_tokens(controls, (4, 4))
    assert tokens.shape == (1, 16, 3)
    assert int(tokens[..., 0].sum().item()) == 4
    assert int(tokens[..., 1:].sum().item()) == 0


def test_scale_zero_is_exact_identity_and_active_control_is_local() -> None:
    hidden = torch.arange(24, dtype=torch.float32).reshape(1, 4, 6)
    controls = torch.zeros((1, 4, 2))
    controls[0, 1, 0] = 1.0
    controls[0, 3, 1] = 1.0
    adapter = ExplicitSpatialControlResidual(torch.eye(2, 6))
    zero = adapter(hidden, controls, scale=0.0)
    active = adapter(hidden, controls, scale=0.1)
    assert torch.equal(zero, hidden)
    assert torch.equal(active[:, [0, 2]], hidden[:, [0, 2]])
    assert not torch.equal(active[:, [1, 3]], hidden[:, [1, 3]])


def test_fp32_accumulation_preserves_zero_scale_and_changes_small_residual_rounding() -> None:
    hidden = torch.ones((1, 2, 4), dtype=torch.bfloat16)
    controls = torch.ones((1, 2, 1), dtype=torch.bfloat16)
    vectors = torch.tensor([[1.0, -1.0, 0.5, -0.5]])
    direct = ExplicitSpatialControlResidual(vectors)
    fp32 = ExplicitSpatialControlResidual(vectors, accumulate_in_fp32=True)
    assert torch.equal(fp32(hidden, controls, scale=0.0), hidden)
    assert direct(hidden, controls, scale=0.01).dtype == torch.bfloat16
    assert fp32(hidden, controls, scale=0.01).dtype == torch.bfloat16


def test_error_feedback_preserves_sub_ulp_residual_across_calls() -> None:
    hidden = torch.ones((1, 1, 1), dtype=torch.bfloat16)
    controls = torch.ones((1, 1, 1))
    direct = ExplicitSpatialControlResidual(torch.ones((1, 1)))
    feedback = ExplicitSpatialControlResidual(torch.ones((1, 1)), error_feedback=True)
    direct_output = hidden
    feedback_output = hidden
    for _ in range(8):
        direct_output = direct(direct_output, controls, scale=0.001)
        feedback_output = feedback(feedback_output, controls, scale=0.001)
    assert torch.equal(direct_output, hidden)
    assert not torch.equal(feedback_output, hidden)
    assert feedback.pending_error is not None
    feedback.reset_error_feedback()
    assert feedback.pending_error is None


def test_single_control_batch_broadcasts_across_cfg_batch() -> None:
    hidden = torch.zeros((2, 4, 6))
    controls = torch.zeros((1, 4, 2))
    controls[0, 2, 1] = 1.0
    adapter = ExplicitSpatialControlResidual(torch.eye(2, 6))
    active = adapter(hidden, controls, scale=0.25)
    assert active.shape == hidden.shape
    assert torch.equal(active[0], active[1])
    assert torch.count_nonzero(active[:, [0, 1, 3]]) == 0
    assert torch.count_nonzero(active[:, 2]) > 0


def test_invalid_control_shapes_are_rejected() -> None:
    with pytest.raises(ValueError, match="controls must have shape"):
        raster_controls_to_tokens(torch.zeros((1, 8, 8)), (4, 4))
    adapter = ExplicitSpatialControlResidual(torch.ones((2, 4)))
    with pytest.raises(ValueError, match="channel count"):
        adapter(torch.zeros((1, 3, 4)), torch.zeros((1, 3, 1)), scale=1.0)
    with pytest.raises(ValueError, match="control batch must be one"):
        adapter(torch.zeros((2, 3, 4)), torch.zeros((3, 3, 2)), scale=1.0)


def test_registration_lifecycle_preserves_scale_zero_and_removes_hooks() -> None:
    transformer = DummyTransformer(3)
    adapter = ExplicitSpatialControlResidual(torch.eye(2, 4))
    before_keys = set(transformer.state_dict())
    registration = ExplicitControlRegistration(transformer, adapter)
    controls = torch.ones((1, 3, 2))
    registration.configure(controls, [0.0, 0.0, 0.0])
    hidden = torch.randn((1, 3, 4))
    for block in transformer.transformer_blocks:
        _, output = block(hidden)
        assert torch.equal(output, hidden)
        assert len(block._forward_hooks) == 1
    assert set(transformer.state_dict()) - before_keys == {
        "explicit_spatial_control.channel_vectors"
    }
    with pytest.raises(RuntimeError, match="already registered"):
        ExplicitControlRegistration(transformer, adapter)
    registration.unregister()
    assert set(transformer.state_dict()) == before_keys
    assert all(not block._forward_hooks for block in transformer.transformer_blocks)


def test_staged_registration_is_independent_and_zero_scale_is_exact() -> None:
    transformer = DummyTransformer(4)
    registration = StagedExplicitControlRegistration(
        transformer,
        {
            "framing": ExplicitSpatialControlResidual(torch.eye(2, 4)),
            "contact": ExplicitSpatialControlResidual(torch.eye(2, 4)),
        },
    )
    hidden = torch.zeros((1, 3, 4))
    framing = torch.zeros((1, 3, 2))
    framing[:, 0, 0] = 1
    contact = torch.zeros((1, 3, 2))
    contact[:, 2, 1] = 1
    registration.configure_stage("framing", framing, [0.0] * 4)
    registration.configure_stage("contact", contact, [0.0] * 4)
    assert all(torch.equal(block(hidden)[1], hidden) for block in transformer.transformer_blocks)
    registration.configure_stage("framing", framing, [0.1, 0.0, 0.0, 0.0])
    assert not torch.equal(transformer.transformer_blocks[0](hidden)[1], hidden)
    assert torch.equal(transformer.transformer_blocks[1](hidden)[1], hidden)
    registration.unregister()


def test_r4_r5_r3_r2_structural_registration_and_zero_parity_are_locked() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_STRUCTURAL_REGISTRATION_AND_ZERO_PARITY"
    registration = payload["registration"]
    assert registration["transformer_blocks"] == 38
    assert registration["registered_hooks"] == 38
    assert registration["independent_stages"] == [
        "early_framing_cast",
        "middle_pose_contact",
    ]
    assert registration["zero_control_bitwise_parity_all_blocks"] is True
    assert all(item["max_abs_error"] == 0.0 for item in registration["zero_results"])
    assert all(route["exact_window_match"] for route in registration["routing"].values())
    assert registration["lifecycle_restored_after_unregister"] is True
    assert payload["phase4l_closure"]["all_requirements_satisfied"] is False
    assert payload["guards"]["images_created"] == 0
    assert all(
        value is False for key, value in payload["guards"].items() if key != "images_created"
    )


def test_r4_r5_r3_r3_rejects_insufficient_pose_contact_locality() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R3_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["identity_processors_preserved"] is True
    assert payload["assessment_revision"]["model_rerun"] is False
    profiles = payload["profiles"]
    assert profiles["early_framing_only"]["eligible"] is True
    assert profiles["middle_pose_contact_only"]["eligible"] is False
    assert profiles["combined"]["eligible"] is False
    assert profiles["middle_pose_contact_only"]["failed_checks"] == ["spatial_dominance_sufficient"]
    assert profiles["combined"]["failed_checks"] == ["spatial_dominance_sufficient"]
    threshold = payload["acceptance"]["minimum_spatial_dominance_ratio"]
    assert profiles["middle_pose_contact_only"]["minimum_spatial_dominance_ratio"] < threshold
    assert profiles["combined"]["minimum_spatial_dominance_ratio"] < threshold
    assert all(profile["pre_onset_clean"] for profile in profiles.values())
    assert all(profile["injection_window_effective"] for profile in profiles.values())
    assert payload["phase4l_closure"]["status"] == (
        "OPEN_PENDING_SINGLE_STEP_STRUCTURAL_CALIBRATION"
    )
    guards = payload["guards"]
    assert guards["full_transformer_forward_count"] == 4
    assert guards["scheduler_step_called"] is False
    assert guards["trajectory_run"] is False
    assert guards["vae_called"] is False
    assert guards["images_created"] == 0
    assert guards["new_generation_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r4_isolates_contact_and_combined_locality_blockers() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R4_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["channel_counts"] == {"pose": 15, "contact": 2, "prop": 4}
    profiles = payload["profiles"]
    assert profiles["pose_full"]["eligible"] is True
    assert profiles["prop_full"]["eligible"] is True
    assert profiles["contact_full"]["eligible"] is False
    assert profiles["contact_prop_full"]["eligible"] is False
    assert profiles["all_early_middle"]["eligible"] is True
    assert profiles["all_early_middle"]["minimum_spatial_dominance_ratio"] > 1.0
    assert profiles["combined_structural_full"]["eligible"] is False
    assert profiles["combined_structural_full"]["minimum_spatial_dominance_ratio"] < 0.95
    assert payload["selected_middle_profile"] == "all_early_middle"
    assert payload["combined_structural_pass"] is False
    assert payload["identity_processors_preserved"] is True
    assert payload["phase4l_closure"]["status"] == ("OPEN_PENDING_STRUCTURAL_CHANNEL_REDESIGN")
    guards = payload["guards"]
    assert guards["full_transformer_forward_count"] == 9
    assert guards["critic_threshold_relaxed"] is False
    assert guards["scheduler_step_called"] is False
    assert guards["trajectory_run"] is False
    assert guards["vae_called"] is False
    assert guards["images_created"] == 0
    assert guards["new_generation_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r5_selects_bounded_combined_contact_profile() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R5_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_COMBINED_SCHEDULE_AND_CONTACT_ROI_ISOLATION"
    assert payload["negative_fixture"]["middle_spatial_dominance"] < 0.95
    assert payload["channel_counts"] == {
        "pose": 15,
        "contact_core": 2,
        "contact_6": 6,
        "contact_10": 10,
        "prop": 4,
    }
    profiles = payload["profiles"]
    assert all(profile["eligible"] for profile in profiles.values())
    selected = profiles["early_all_contact10"]
    assert selected["minimum_spatial_dominance_ratio"] >= 0.95
    assert selected["window"] == "early_middle"
    assert selected["active_blocks"] == [*range(10), *range(18, 23)]
    assert payload["combined_structural_pass"] is True
    assert payload["identity_processors_preserved"] is True
    assert payload["phase4l_closure"]["status"] == ("OPEN_PENDING_LATENT_TRAJECTORY_AB")
    guards = payload["guards"]
    assert guards["full_transformer_forward_count"] == 8
    assert guards["critic_threshold_relaxed"] is False
    assert guards["scheduler_step_called"] is False
    assert guards["trajectory_run"] is False
    assert guards["vae_called"] is False
    assert guards["images_created"] == 0
    assert guards["new_generation_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r6_rejects_late_tail_diffusion_without_seam() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R6_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["profile"] == {
        "early_blocks": list(range(10)),
        "early_steps": list(range(2, 8)),
        "early_scale": 0.00125,
        "middle_blocks": list(range(18, 23)),
        "middle_steps": list(range(8, 16)),
        "middle_scale": 0.0025,
        "middle_channels": ["pose", "contact_10", "prop"],
    }
    assert payload["baseline"]["profile_count"] == 24
    assert payload["active"]["profile_count"] == 24
    assert payload["baseline"]["latent_critic"]["blocked"] is False
    assert payload["active"]["latent_critic"]["blocked"] is False
    assert payload["paired_critic"]["blocked"] is False
    gates = payload["gates"]
    assert gates["relative_latent_delta_bounded"] is False
    assert gates["final_spatial_ratio_sufficient"] is False
    assert all(
        passed
        for name, passed in gates.items()
        if name not in {"relative_latent_delta_bounded", "final_spatial_ratio_sufficient"}
    )
    comparison = payload["comparison"]
    assert comparison["maximum_relative_latent_delta"] > 0.05
    assert comparison["final_spatial_ratio"] < 0.95
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_TRAJECTORY_REPAIR"
    guards = payload["guards"]
    assert guards["transformer_forward_count"] == 48
    assert guards["scheduler_step_count"] == 48
    assert guards["trajectory_count"] == 2
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r7_rejects_scale_halving_and_terminal_refinement() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R7_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["eligible_profiles"] == []
    assert payload["selected_profile"] is None
    profiles = payload["profiles"]
    assert set(profiles) == {"a_half_scale", "b_half_scale_terminal"}
    for profile in profiles.values():
        assert profile["status"] == "FAIL"
        assert profile["gates"]["relative_latent_delta_bounded"] is False
        assert profile["gates"]["final_spatial_ratio_sufficient"] is False
        assert profile["gates"]["baseline_absolute_critic_clean"] is True
        assert profile["gates"]["active_absolute_critic_clean"] is True
        assert profile["gates"]["paired_critic_clean"] is True
        assert profile["comparison"]["maximum_relative_latent_delta"] > 0.1
        assert profile["comparison"]["final_spatial_ratio"] < 0.55
    terminal = profiles["b_half_scale_terminal"]["comparison"]
    plain = profiles["a_half_scale"]["comparison"]
    assert terminal["final_spatial_ratio"] < plain["final_spatial_ratio"]
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_TRAJECTORY_REPAIR"
    guards = payload["guards"]
    assert guards["total_trajectory_count"] == 3
    assert guards["baseline_reused_for_profile_b"] is True
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r8_rejects_precision_as_primary_cause() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R8_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_NUMERICAL_PRECISION_CAUSAL_ISOLATION"
    assert payload["probe_steps"] == [2, 8, 15, 22]
    assert payload["scales"] == [0.000625, 0.00125, 0.0025]
    assert payload["all_finite"] is True
    locality_deltas = []
    output_deltas = []
    zero_fractions = []
    for step in payload["results"].values():
        for scale in payload["scales"]:
            direct = step["variants"][f"bf16_direct_scale_{scale}"]
            fp32 = step["variants"][f"fp32_accumulate_scale_{scale}"]
            locality_deltas.append(
                abs(direct["minimum_localization_ratio"] - fp32["minimum_localization_ratio"])
            )
            output_deltas.append(
                abs(direct["final_output_mean_abs_delta"] - fp32["final_output_mean_abs_delta"])
            )
            zero_fractions.extend(
                [
                    direct["injection_boundary_quantization"]["quantized_to_zero_fraction"],
                    fp32["injection_boundary_quantization"]["quantized_to_zero_fraction"],
                ]
            )
    assert max(locality_deltas) < 0.01
    assert max(output_deltas) < 0.0005
    assert min(zero_fractions) > 0.98
    assert payload["phase4l_closure"]["status"] == ("OPEN_PENDING_PRECISION_PATH_DECISION")
    guards = payload["guards"]
    assert guards["transformer_forward_count"] == 28
    assert guards["scheduler_step_count"] == 0
    assert guards["trajectory_count"] == 0
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["production_profile_changed"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r9_selects_only_non_degrading_error_feedback_scale() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R9_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_ERROR_FEEDBACK_CAUSAL_ISOLATION"
    assert payload["all_finite"] is True
    decision = payload["error_feedback_decision"]
    assert decision == {
        "monotonic_global_response": True,
        "eligible_scales_with_non_degrading_locality_at_all_probes": [0.0025],
        "selected_scale": 0.0025,
        "trajectory_authorized": True,
    }
    for step in payload["results"].values():
        direct = step["variants"]["bf16_direct_scale_0.0025"]
        feedback = step["variants"]["error_feedback_scale_0.0025"]
        assert feedback["minimum_localization_ratio"] >= direct["minimum_localization_ratio"]
        assert feedback["pending_error_mean_abs"] > 0
        assert feedback["maximum_relative_global_delta"] < 0.01
    assert payload["phase4l_closure"]["status"] == ("OPEN_PENDING_ERROR_FEEDBACK_TRAJECTORY")
    guards = payload["guards"]
    assert guards["transformer_forward_count"] == 28
    assert guards["scheduler_step_count"] == 0
    assert guards["trajectory_count"] == 0
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["production_profile_changed"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_rejects_cross_step_error_feedback_trajectory() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["profile"]["error_feedback"] is True
    assert payload["profile"]["early_scale"] == 0.0025
    assert payload["profile"]["middle_scale"] == 0.0025
    gates = payload["gates"]
    assert gates["relative_latent_delta_bounded"] is False
    assert gates["final_spatial_ratio_sufficient"] is False
    assert all(
        passed
        for name, passed in gates.items()
        if name not in {"relative_latent_delta_bounded", "final_spatial_ratio_sufficient"}
    )
    comparison = payload["comparison"]
    assert comparison["maximum_relative_latent_delta"] > 0.10
    assert 0.63 < comparison["final_spatial_ratio"] < 0.65
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_TRAJECTORY_REPAIR"
    guards = payload["guards"]
    assert guards["transformer_forward_count"] == 24
    assert guards["scheduler_step_count"] == 24
    assert guards["trajectory_count"] == 1
    assert guards["baseline_loaded_from_cache"] is True
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_r1_invalidates_contaminated_r9_scale_selection() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R1_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_STEP_BOUNDED_ERROR_FEEDBACK_ISOLATION"
    assert payload["probe_steps"] == [2, 8, 15, 22]
    assert payload["scales"] == [0.0025]
    assert payload["all_finite"] is True
    decision = payload["lifecycle_decision"]
    assert decision["exact_r9_reproduction"] is False
    assert decision["maximum_r9_metric_delta"] > 0.25
    assert decision["cross_step_state_is_causal"] is True
    assert decision["maximum_reset_vs_carry_output_delta"] > 0
    assert decision["r9_scale_selection_invalidated"] is True
    assert decision["trajectory_authorized"] is False
    assert payload["phase4l_closure"]["status"] == ("OPEN_PENDING_CLEAN_SCALE_REVALIDATION")
    guards = payload["guards"]
    assert guards["transformer_forward_count"] == 12
    assert guards["scheduler_step_count"] == 0
    assert guards["trajectory_count"] == 0
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["production_profile_changed"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_r1_r1_rejects_all_clean_global_scales() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R1_R1_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_CLEAN_SCALE_ERROR_FEEDBACK_REVALIDATION"
    assert payload["scales"] == [0.000625, 0.00125, 0.0025]
    assert payload["all_finite"] is True
    decision = payload["error_feedback_decision"]
    assert decision == {
        "monotonic_global_response": True,
        "eligible_scales_with_non_degrading_locality_at_all_probes": [],
        "selected_scale": None,
        "trajectory_authorized": False,
    }
    for scale in payload["scales"]:
        step22 = payload["causal_comparison"][f"step_22_scale_{scale}"]
        assert step22["locality_delta"] < 0
    assert payload["causal_comparison"]["step_8_scale_0.00125"]["locality_delta"] < 0
    assert payload["phase4l_closure"]["status"] == ("OPEN_PENDING_RESIDUAL_PROFILE_REDESIGN")
    guards = payload["guards"]
    assert guards["transformer_forward_count"] == 28
    assert guards["scheduler_step_count"] == 0
    assert guards["trajectory_count"] == 0
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["production_profile_changed"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_r1_r2_selects_schedule_aligned_profile() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R1_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_SCHEDULE_ALIGNED_ASYMMETRIC_PROFILE"
    assert len(payload["profiles"]) == 4
    assert set(payload["eligible_profiles"]) == set(payload["profiles"])
    assert payload["selected_profile"] == "early_0.00125_middle_0.000625"
    selected = payload["selected_profile_values"]
    assert selected["early_scale"] == 0.00125
    assert selected["middle_scale"] == 0.000625
    assert selected["terminal_scale"] == 0.0
    assert selected["eligible"] is True
    assert all(selected["gates"].values())
    terminal = payload["terminal_zero_control_parity"]
    assert terminal == {
        "bitwise_equal": True,
        "maximum_absolute_delta": 0.0,
        "pending_error_unchanged": True,
        "terminal_scale": 0.0,
    }
    assert payload["trajectory_authorized"] is True
    assert payload["phase4l_closure"]["status"] == ("OPEN_PENDING_SCHEDULE_ALIGNED_TRAJECTORY")
    guards = payload["guards"]
    assert guards["transformer_forward_count"] == 0
    assert guards["scheduler_step_count"] == 0
    assert guards["trajectory_count"] == 0
    assert guards["reused_locked_measurements"] is True
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["production_profile_changed"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_r2_rejects_tail_amplified_schedule_trajectory() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    profile = payload["profile"]
    assert profile["early_scale"] == 0.00125
    assert profile["middle_scale"] == 0.000625
    assert profile["terminal_scale"] == 0.0
    assert profile["error_feedback"] is True
    assert profile["reset_error_feedback_per_forward"] is True
    gates = payload["gates"]
    assert gates["relative_latent_delta_bounded"] is False
    assert gates["final_spatial_ratio_sufficient"] is False
    assert all(
        passed
        for name, passed in gates.items()
        if name not in {"relative_latent_delta_bounded", "final_spatial_ratio_sufficient"}
    )
    comparison = payload["comparison"]
    assert 0.082 < comparison["maximum_relative_latent_delta"] < 0.084
    assert 0.90 < comparison["final_spatial_ratio"] < 0.901
    steps = comparison["steps"]
    assert steps[17]["relative_latent_delta"] < 0.05
    assert steps[17]["spatial_ratio"] >= 0.95
    assert steps[18]["relative_latent_delta"] > 0.05
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_TRAJECTORY_REPAIR"
    guards = payload["guards"]
    assert guards["transformer_forward_count"] == 24
    assert guards["scheduler_step_count"] == 24
    assert guards["trajectory_count"] == 1
    assert guards["baseline_loaded_from_cache"] is True
    assert guards["error_feedback_reset_count"] == 24
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_r2_r1_rejects_both_middle_cutoffs() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R1_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["eligible_profiles"] == []
    assert payload["selected_profile"] is None
    assert payload["trajectory_authorized"] is False
    a = payload["profiles"]["a_middle_8_11"]
    b = payload["profiles"]["b_middle_8_13"]
    assert a["middle_steps"] == [8, 9, 10, 11]
    assert b["middle_steps"] == [8, 9, 10, 11, 12, 13]
    for profile in (a, b):
        assert profile["status"] == "FAIL"
        assert profile["gates"]["relative_latent_delta_bounded"] is False
        assert profile["gates"]["final_spatial_ratio_sufficient"] is False
        assert profile["gates"]["baseline_absolute_critic_clean"] is True
        assert profile["gates"]["active_absolute_critic_clean"] is True
        assert profile["gates"]["paired_critic_clean"] is True
        assert profile["error_feedback_reset_count"] == 24
    assert (
        b["comparison"]["maximum_relative_latent_delta"]
        < a["comparison"]["maximum_relative_latent_delta"]
    )
    assert b["comparison"]["final_spatial_ratio"] > a["comparison"]["final_spatial_ratio"]
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_TRAJECTORY_REPAIR"
    guards = payload["guards"]
    assert guards["total_transformer_forward_count"] == 48
    assert guards["total_scheduler_step_count"] == 48
    assert guards["total_trajectory_count"] == 2
    assert guards["baseline_loaded_from_cache_for_all_profiles"] is True
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_r2_r2_rejects_both_early_cutoffs() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["eligible_profiles"] == []
    assert payload["selected_profile"] is None
    assert payload["trajectory_authorized"] is False
    a = payload["profiles"]["a_early_2_3"]
    b = payload["profiles"]["b_early_2_4"]
    assert a["early_steps"] == [2, 3]
    assert b["early_steps"] == [2, 3, 4]
    assert a["middle_steps"] == b["middle_steps"] == [8, 9, 10, 11, 12, 13]
    for profile in (a, b):
        assert profile["status"] == "FAIL"
        assert profile["gates"]["relative_latent_delta_bounded"] is False
        assert profile["gates"]["final_spatial_ratio_sufficient"] is False
        assert profile["gates"]["baseline_absolute_critic_clean"] is True
        assert profile["gates"]["active_absolute_critic_clean"] is True
        assert profile["gates"]["paired_critic_clean"] is True
        assert profile["gates"]["update_norm_bounded"] is True
        assert profile["error_feedback_reset_count"] == 24
    assert (
        a["comparison"]["maximum_relative_latent_delta"]
        < b["comparison"]["maximum_relative_latent_delta"]
    )
    assert a["comparison"]["final_spatial_ratio"] > b["comparison"]["final_spatial_ratio"]
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_TRAJECTORY_REPAIR"
    guards = payload["guards"]
    assert guards["total_transformer_forward_count"] == 48
    assert guards["total_scheduler_step_count"] == 48
    assert guards["total_trajectory_count"] == 2
    assert guards["baseline_loaded_from_cache_for_all_profiles"] is True
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["production_profile_changed"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_r2_r3_attributes_early_and_middle_failures() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R3_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["eligible_profiles"] == []
    assert payload["selected_profile"] is None
    assert payload["trajectory_authorized"] is False
    early = payload["profiles"]["a_early_only"]
    middle = payload["profiles"]["b_middle_only"]
    assert early["early_steps"] == [2, 3]
    assert early["middle_steps"] == []
    assert middle["early_steps"] == []
    assert middle["middle_steps"] == [8, 9, 10, 11, 12, 13]
    assert early["gates"]["relative_latent_delta_bounded"] is False
    assert early["gates"]["final_spatial_ratio_sufficient"] is False
    assert middle["gates"]["relative_latent_delta_bounded"] is True
    assert middle["gates"]["final_spatial_ratio_sufficient"] is False
    assert early["comparison"]["maximum_relative_latent_delta"] > 0.05
    assert middle["comparison"]["maximum_relative_latent_delta"] <= 0.05
    assert middle["comparison"]["final_spatial_ratio"] < early["comparison"]["final_spatial_ratio"]
    for profile in (early, middle):
        assert profile["status"] == "FAIL"
        assert profile["gates"]["baseline_absolute_critic_clean"] is True
        assert profile["gates"]["active_absolute_critic_clean"] is True
        assert profile["gates"]["paired_critic_clean"] is True
        assert profile["gates"]["update_norm_bounded"] is True
        assert profile["error_feedback_reset_count"] == 24
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_TRAJECTORY_REPAIR"
    guards = payload["guards"]
    assert guards["total_transformer_forward_count"] == 48
    assert guards["total_scheduler_step_count"] == 48
    assert guards["total_trajectory_count"] == 2
    assert guards["baseline_loaded_from_cache_for_all_profiles"] is True
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["production_profile_changed"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_r2_r4_attributes_early_block_group_failures() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R4_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["eligible_profiles"] == []
    assert payload["selected_profile"] is None
    assert payload["trajectory_authorized"] is False
    first = payload["profiles"]["a_blocks_0_4"]
    second = payload["profiles"]["b_blocks_5_9"]
    assert first["early_blocks"] == [0, 1, 2, 3, 4]
    assert second["early_blocks"] == [5, 6, 7, 8, 9]
    for profile in (first, second):
        assert profile["early_steps"] == [2, 3]
        assert profile["middle_steps"] == []
        assert profile["status"] == "FAIL"
        assert profile["gates"]["relative_latent_delta_bounded"] is False
        assert profile["gates"]["final_spatial_ratio_sufficient"] is False
        assert profile["gates"]["baseline_absolute_critic_clean"] is True
        assert profile["gates"]["active_absolute_critic_clean"] is True
        assert profile["gates"]["paired_critic_clean"] is True
        assert profile["gates"]["update_norm_bounded"] is True
        assert profile["error_feedback_reset_count"] == 24
    assert (
        first["comparison"]["maximum_relative_latent_delta"]
        < second["comparison"]["maximum_relative_latent_delta"]
    )
    assert first["comparison"]["final_spatial_ratio"] > second["comparison"]["final_spatial_ratio"]
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_TRAJECTORY_REPAIR"
    guards = payload["guards"]
    assert guards["total_transformer_forward_count"] == 48
    assert guards["total_scheduler_step_count"] == 48
    assert guards["total_trajectory_count"] == 2
    assert guards["baseline_loaded_from_cache_for_all_profiles"] is True
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["production_profile_changed"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_r2_r5_locks_non_linear_early_block_interaction() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R5_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["eligible_profiles"] == []
    assert payload["selected_profile"] is None
    assert payload["trajectory_authorized"] is False
    first = payload["profiles"]["a_blocks_0_2"]
    second = payload["profiles"]["b_blocks_3_4"]
    assert first["early_blocks"] == [0, 1, 2]
    assert second["early_blocks"] == [3, 4]
    for profile in (first, second):
        assert profile["early_steps"] == [2, 3]
        assert profile["middle_steps"] == []
        assert profile["status"] == "FAIL"
        assert profile["gates"]["relative_latent_delta_bounded"] is False
        assert profile["gates"]["final_spatial_ratio_sufficient"] is False
        assert profile["gates"]["baseline_absolute_critic_clean"] is True
        assert profile["gates"]["active_absolute_critic_clean"] is True
        assert profile["gates"]["paired_critic_clean"] is True
        assert profile["gates"]["update_norm_bounded"] is True
        assert profile["error_feedback_reset_count"] == 24
    assert (
        second["comparison"]["maximum_relative_latent_delta"]
        < first["comparison"]["maximum_relative_latent_delta"]
    )
    assert second["comparison"]["final_spatial_ratio"] > first["comparison"]["final_spatial_ratio"]
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_TRAJECTORY_REPAIR"
    guards = payload["guards"]
    assert guards["total_transformer_forward_count"] == 48
    assert guards["total_scheduler_step_count"] == 48
    assert guards["total_trajectory_count"] == 2
    assert guards["baseline_loaded_from_cache_for_all_profiles"] is True
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["new_generation_authorized"] is False
    assert guards["production_profile_changed"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r4_r5_r3_r10_r2_r6_locks_waiver_without_silent_regeneration() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R6_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCKED_MISSING_LOCKED_LATENT"
    waiver = payload["waiver"]
    assert waiver["type"] == "USER_ACCEPTED_RECORDED_DEVIATION"
    assert waiver["original_thresholds_unchanged"] == {
        "maximum_relative_latent_delta": 0.05,
        "minimum_final_spatial_ratio": 0.95,
    }
    assert waiver["accepted_profile"]["early_blocks"] == [0, 1, 2, 3, 4]
    assert waiver["accepted_profile"]["early_steps"] == [2, 3]
    assert waiver["accepted_profile"]["early_scale"] == 0.00125
    assert waiver["accepted_profile"]["maximum_relative_latent_delta"] > 0.05
    assert waiver["accepted_profile"]["final_spatial_ratio"] < 0.95
    assert waiver["critic_recalibrated_to_force_pass"] is False
    contract = payload["decode_contract"]
    assert contract["locked_latent_available"] is False
    assert contract["denoise_rerun_authorized"] is False
    assert contract["maximum_vae_decodes"] == 0
    assert contract["decode_authorized"] is False
    assert contract["stop_for_manual_review_after_decode"] is True
    assert payload["phase4l_closure"]["status"] == "OPEN_BLOCKED_MISSING_LOCKED_LATENT"
    assert payload["guards"] == {
        "denoise_runs": 0,
        "vae_calls": {"forward": 0, "decode": 0},
        "images_created": 0,
        "production_profile_changed": False,
        "phase4l_closed": False,
        "phase4n_opened": False,
    }


def test_r4_r5_r3_r10_r2_r6_r1_locks_single_replay_decode_rejection() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R6_R1_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "AUTO_REJECT_AWAITING_MANUAL_REVIEW"
    replay = payload["replay"]
    assert replay["trajectory_attempts"] == 1
    assert replay["deterministic_parity_pass"] is True
    assert replay["delta_error"] == 0.0
    assert replay["spatial_error"] == 0.0
    assert replay["replay_delta"] == replay["source_delta"]
    assert replay["replay_spatial_ratio"] == replay["source_spatial_ratio"]
    assert payload["automatic_qa"]["status"] == "ASSESSED_FAIL"
    gates = payload["automatic_qa"]["gates"]
    assert gates["photorealism_fidelity_gate"]["status"] == "PASS"
    assert gates["bo_identity"]["status"] == "PASS"
    assert gates["me_identity"]["status"] == "PASS"
    assert gates["text_artifact"]["status"] == "PASS"
    for gate in (
        "hand_anatomy_gate",
        "hand_prop_contact_gate",
        "paper_boat_shape_scale_gate",
        "two_visible_faces_cast_gate",
        "exactly_two_interaction_hands_gate",
    ):
        assert gates[gate]["status"] == "FAIL"
    assert payload["all_automatic_gates_pass"] is False
    assert payload["candidate_promotable"] is False
    assert payload["manual_review_required"] is True
    assert payload["manual_review_status"] == "PENDING"
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_MANUAL_REVIEW"
    assert payload["guards"]["exactly_one_denoise_replay"] is True
    assert payload["guards"]["exactly_one_vae_decode"] is True
    assert payload["guards"]["images_created"] == 1
    assert payload["guards"]["automatic_retry_started"] is False
    assert payload["guards"]["phase4l_closed"] is False
    assert payload["guards"]["phase4n_opened"] is False


def test_r4_r5_r3_r10_r2_r6_r2_locks_manual_reject_and_geometry_contract() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R6_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_MANUAL_REJECT_AND_GEOMETRY_FAILURE_LOCK"
    assert payload["manual_review"]["candidate_status"] == "REJECTED"
    assert payload["manual_review"]["reason"] == (
        "AUTOMATIC_AND_VISUAL_GEOMETRY_FAILURE_CONFIRMED"
    )
    assert len(payload["manual_review"]["candidate_sha256"]) == 64
    assert len(payload["manual_review"]["assessment_sha256"]) == 64
    assert payload["negative_regression"]["fixture_role"] == "REQUIRED_NEGATIVE"
    assert payload["negative_regression"]["locked_failure_gates"] == [
        "hand_anatomy_gate",
        "hand_prop_contact_gate",
        "paper_boat_shape_scale_gate",
        "two_visible_faces_cast_gate",
        "exactly_two_interaction_hands_gate",
    ]
    assert payload["negative_regression"]["passing_invariants"] == [
        "photorealism_fidelity_gate",
        "bo_identity",
        "me_identity",
        "text_artifact",
    ]
    contract_path = Path(payload["geometry_contract_path"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["requirements"]["visible_faces"]["exact_count"] == 2
    assert contract["requirements"]["interaction_hands"]["exact_count"] == 2
    assert contract["requirements"]["paper_boat"]["exact_count"] == 1
    assert contract["requirements"]["contact"]["both_hands_contact_same_boat"] is True
    assert contract["authorization_policy"]["latent_only_dry_run_required_before_next_decode"] is True
    assert contract["authorization_policy"]["next_decode_authorized"] is False
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_GEOMETRY_CONTROL_DRY_RUN"
    assert payload["guards"] == {
        "denoise_runs": 0,
        "vae_calls": {"forward": 0, "decode": 0},
        "images_created": 0,
        "next_candidate_authorized": False,
        "production_profile_changed": False,
        "phase4l_closed": False,
        "phase4n_opened": False,
    }


def test_r4_r5_r3_r10_r2_r6_r3_passes_geometry_layout_without_inference() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R6_R3_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_GEOMETRY_CONTROL_LAYOUT_DRY_RUN"
    assert payload["channel_order"] == [
        "bo_face",
        "me_face",
        "bo_hand",
        "me_hand",
        "paper_boat",
        "bo_contact",
        "me_contact",
    ]
    assert all(count > 0 for count in payload["token_counts"].values())
    assert all(payload["geometry_gates"].values())
    pixels = payload["pixel_metrics"]
    assert pixels["face_overlap_pixels"] == 0
    assert pixels["hand_overlap_pixels"] == 0
    assert pixels["bo_contact_hand_overlap_pixels"] > 0
    assert pixels["me_contact_hand_overlap_pixels"] > 0
    assert pixels["bo_contact_boat_overlap_pixels"] > 0
    assert pixels["me_contact_boat_overlap_pixels"] > 0
    assert pixels["interaction_controls_outside_roi_pixels"] == 0
    registration = payload["registration_smoke"]
    assert registration["status"] == "PASS"
    assert registration["transformer_blocks"] == 38
    assert registration["registered_control_hooks"] == 38
    assert registration["identity_processors_preserved"] is True
    assert registration["lifecycle_restored_after_unregister"] is True
    assert registration["transformer_forward_called"] is False
    assert registration["cuda_initialized"] is False
    assert payload["next_stage_authorized"] is True
    assert payload["next_decode_authorized"] is False
    assert payload["phase4l_closure"]["status"] == "OPEN_PENDING_GEOMETRY_LATENT_TRAJECTORY"
    assert payload["guards"] == {
        "subprocess_isolation": True,
        "cpu_only": True,
        "transformer_forward_called": False,
        "denoise_runs": 0,
        "latents_created": 0,
        "vae_instantiated": False,
        "vae_calls": {"forward": 0, "decode": 0},
        "images_created": 0,
        "production_profile_changed": False,
        "phase4l_closed": False,
        "phase4n_opened": False,
    }


def test_r4_r5_r3_r10_r2_r6_r4_passes_geometry_latent_trajectory_without_decode() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R6_R4_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_GEOMETRY_LATENT_TRAJECTORY"
    assert payload["profile"]["channels"] == [
        "bo_face",
        "me_face",
        "bo_hand",
        "me_hand",
        "paper_boat",
        "bo_contact",
        "me_contact",
    ]
    assert payload["profile"]["early_blocks"] == [0, 1, 2, 3, 4]
    assert payload["profile"]["early_steps"] == [2, 3]
    assert payload["profile"]["early_scale"] == 0.00125
    assert all(payload["waiver_gates"].values())
    assert all(payload["region_effects"].values())
    comparison = payload["comparison"]
    accepted = payload["accepted_waiver_baseline"]
    assert comparison["maximum_relative_latent_delta"] <= accepted["maximum_relative_latent_delta"]
    assert comparison["final_spatial_ratio"] >= accepted["final_spatial_ratio"]
    assert comparison["steps"][-1]["outside_mean_abs_delta"] <= accepted["final_outside_mean_abs_delta"]
    assert comparison["regions"]["bo_face"]["final_spatial_ratio"] > 1.0
    assert comparison["regions"]["bo_hand"]["final_spatial_ratio"] > 1.0
    assert comparison["regions"]["paper_boat"]["final_spatial_ratio"] > 1.0
    assert comparison["regions"]["bo_contact"]["final_spatial_ratio"] > 1.0
    assert comparison["regions"]["me_face"]["final_spatial_ratio"] < 1.0
    assert comparison["regions"]["me_hand"]["final_spatial_ratio"] < 1.0
    assert comparison["regions"]["me_contact"]["final_spatial_ratio"] < 1.0
    assert payload["next_decode_authorized"] is False
    assert payload["phase4l_closure"]["status"] == (
        "OPEN_PENDING_GEOMETRY_DECODE_AUTHORIZATION_REVIEW"
    )
    assert payload["guards"] == {
        "transformer_forward_count": 24,
        "scheduler_step_count": 24,
        "trajectory_count": 1,
        "baseline_loaded_from_cache": True,
        "vae_calls": {"forward": 0, "decode": 0},
        "images_created": 0,
        "decode_authorized": False,
        "production_profile_changed": False,
        "phase4l_closed": False,
        "phase4n_opened": False,
    }


def test_r4_r5_r3_r10_r2_r6_r5_rejects_ineffective_mother_gain() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R6_R5_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["profile"]["mother_gain"] == 1.5
    assert payload["profile"]["channel_gains"] == {
        "bo_face": 1.0,
        "me_face": 1.5,
        "bo_hand": 1.0,
        "me_hand": 1.5,
        "paper_boat": 1.0,
        "bo_contact": 1.0,
        "me_contact": 1.5,
    }
    assert payload["mother_improvement"] == {
        "me_contact": False,
        "me_face": False,
        "me_hand": False,
    }
    assert all(payload["bo_prop_retention"].values())
    assert payload["gates"]["all_mother_regions_improved"] is False
    for name, value in payload["gates"].items():
        if name != "all_mother_regions_improved":
            assert value is True
    for name, prior in payload["prior_geometry_regions"].items():
        current = payload["comparison"]["regions"][name]
        assert current["final_spatial_ratio"] == prior["final_spatial_ratio"]
    assert payload["next_decode_authorized"] is False
    assert payload["phase4l_closure"]["status"] == (
        "OPEN_PENDING_MOTHER_SIDE_REBALANCE_REPAIR"
    )
    assert payload["guards"] == {
        "transformer_forward_count": 24,
        "scheduler_step_count": 24,
        "trajectory_count": 1,
        "baseline_loaded_from_cache": True,
        "vae_calls": {"forward": 0, "decode": 0},
        "images_created": 0,
        "decode_authorized": False,
        "production_profile_changed": False,
        "phase4l_closed": False,
        "phase4n_opened": False,
    }


def test_r4_r5_r3_r10_r2_r6_r6_locks_bf16_gain_observability() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R6_R6_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_BF16_CHANNEL_GAIN_OBSERVABILITY_FORENSIC"
    assert payload["configuration"]["dtype"] == "torch.bfloat16"
    assert payload["configuration"]["scale"] == 0.00125
    assert payload["configuration"]["gains"] == [1.0, 1.5, 2.0, 4.0]
    conclusion = payload["conclusion"]
    assert conclusion["first_reset_gain_observable_against_gain_1"] == 1.5
    assert conclusion["first_gain_with_carry_output_evolution"] == 1.0
    assert conclusion["all_observed_values_finite"] is True
    assert conclusion["gain_1_5_observable_with_reset"] is True
    assert conclusion["carry_changes_outputs_at_gain_1_5"] is True
    reset = payload["reset_each_forward"]["profiles"]
    carry = payload["carry_across_forwards"]["profiles"]
    assert reset["1.0"]["unique_output_count"] == 1
    assert reset["1.5"]["unique_output_count"] == 1
    assert reset["1.5"]["first_output_differs_from_gain_1"] is True
    assert carry["1.0"]["unique_output_count"] == 8
    assert carry["1.5"]["unique_output_count"] == 8
    assert carry["1.5"]["observed_norm_by_forward"][-1] > reset["1.5"][
        "observed_norm_by_forward"
    ][-1]
    assert payload["next_decode_authorized"] is False
    assert payload["phase4l_closure"]["status"] == (
        "OPEN_PENDING_MOTHER_RESIDUAL_WRITE_POLICY"
    )
    assert payload["guards"] == {
        "cpu_only": True,
        "transformer_instantiated": False,
        "transformer_forward_called": False,
        "denoise_runs": 0,
        "latents_created": 0,
        "vae_instantiated": False,
        "vae_calls": {"forward": 0, "decode": 0},
        "images_created": 0,
        "production_profile_changed": False,
        "phase4l_closed": False,
        "phase4n_opened": False,
    }


def test_r4_r5_r3_r10_r2_r6_r7_observes_gain_in_real_transformer() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R6_R7_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_REAL_TRANSFORMER_GAIN_OBSERVABILITY_AB"
    assert payload["configuration"]["step_index"] == 2
    assert payload["configuration"]["active_blocks"] == [0, 1, 2, 3, 4]
    assert payload["configuration"]["scale"] == 0.00125
    assert payload["configuration"]["gains"] == {
        "a_gain_1": 1.0,
        "b_gain_1_5": 1.5,
    }
    records = payload["block_records"]
    assert [record["block"] for record in records] == [0, 1, 2, 3, 4]
    assert records[0]["pre_residual_ab_mean_abs_delta"] == 0.0
    for record in records:
        assert record["gain_1_5_write_norm"] > record["gain_1_write_norm"]
        assert record["write_norm_ratio"] > 1.0
        assert record["post_residual_ab_mean_abs_delta"] > 0.0
        assert record["mother_regions"]["me_face"]["localization_ratio"] > 1.0
        assert record["mother_regions"]["me_hand"]["localization_ratio"] > 1.0
        assert record["mother_regions"]["me_contact"]["localization_ratio"] > 1.0
    summary = payload["summary"]
    assert summary["write_observable"] is True
    assert summary["first_observable_block"] == 0
    assert summary["final_transformer_output_ab_mean_abs_delta"] > 0.0
    assert summary["gain_difference_propagated_to_final_output"] is True
    assert payload["next_decode_authorized"] is False
    assert payload["phase4l_closure"]["status"] == (
        "OPEN_PENDING_MOTHER_GAIN_INTEGRATION_DECISION"
    )
    assert payload["guards"] == {
        "full_transformer_forward_count": 2,
        "scheduler_step_called": False,
        "trajectory_run": False,
        "vae_called": False,
        "images_created": 0,
        "production_profile_changed": False,
        "phase4l_closed": False,
        "phase4n_opened": False,
    }


def test_r4_r5_r3_r10_r2_r6_r8_locks_scheduler_gain_persistence() -> None:
    payload = json.loads(R21_R7_R4_R5_R3_R10_R2_R6_R8_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_SCHEDULER_MICROTRAJECTORY_GAIN_AB"
    assert payload["configuration"]["probe_steps"] == [2, 3, 4]
    assert payload["configuration"]["control_steps"] == [2, 3]
    assert payload["configuration"]["passive_persistence_step"] == 4
    comparisons = payload["comparisons"]
    assert [item["step_index"] for item in comparisons] == [2, 3, 4]
    assert [item["control_active"] for item in comparisons] == [True, True, False]
    assert all(item["global_mean_abs_delta"] > 0.0 for item in comparisons)
    assert comparisons[2]["global_mean_abs_delta"] > comparisons[0]["global_mean_abs_delta"]
    assert comparisons[0]["mother_regions"]["me_hand"]["localization_ratio"] > 1.0
    assert comparisons[2]["mother_regions"]["me_hand"]["localization_ratio"] > 1.0
    summary = payload["summary"]
    assert summary["gain_difference_survives_active_scheduler_steps"] is True
    assert summary["gain_difference_survives_first_passive_step"] is True
    assert summary["scheduler_immediate_erasure"] is False
    assert summary["remaining_suspect"] == "later_denoise_tail_accumulation"
    assert payload["next_decode_authorized"] is False
    assert payload["phase4l_closure"]["status"] == (
        "OPEN_PENDING_TRAJECTORY_TAIL_LOCALIZATION"
    )
    assert payload["guards"] == {
        "transformer_forward_count": 6,
        "scheduler_step_count": 6,
        "full_trajectory_run": False,
        "vae_called": False,
        "images_created": 0,
        "production_profile_changed": False,
        "phase4l_closed": False,
        "phase4n_opened": False,
    }


def test_phase4l_closes_only_under_recorded_lowered_thresholds() -> None:
    payload = json.loads(
        PHASE4L_LOWERED_THRESHOLD_CLOSURE_RESULT.read_text(encoding="utf-8")
    )
    assert payload["status"] == "CLOSED_ACCEPTED_WITH_RECORDED_DEVIATIONS"
    assert payload["authorization_basis"] == "USER_DIRECTED_THRESHOLD_REDUCTION"
    assert payload["previous_state"]["status"] == "OPEN_PENDING_TRAJECTORY_TAIL_LOCALIZATION"
    assert payload["previous_state"]["mother_gain_full_trajectory_status"] == "FAIL"
    assert all(payload["locked_prerequisites"].values())
    assert all(payload["lowered_gate_checks"].values())
    assert payload["observed"]["count_above_neutral_localization"] == 2
    assert min(payload["observed"]["mother_region_localization_ratios"].values()) >= 0.95
    assert payload["observed"]["final_passive_ab_mean_abs_delta"] >= 0.0002
    closure = payload["phase4l_closure"]
    assert closure["all_lowered_requirements_satisfied"] is True
    assert closure["original_requirements_satisfied"] is False
    assert payload["phase4n"]["open_authorized"] is True
    assert payload["phase4n"]["opened"] is False
    assert payload["guards"] == {
        "thresholds_changed_in_production_profile": False,
        "model_inference_run": False,
        "vae_called": False,
        "images_created": 0,
        "production_candidate_promoted": False,
    }


def test_r7_r2_real_block_parity_locality_and_guards_are_locked() -> None:
    payload = json.loads(R21_R7_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_EXPLICIT_CONTROL_INTEGRATION_DRY_RUN"
    assert payload["contract_sha256"] == (
        "6aeae1c47d6423c92808ea4efc009bcb65fa6e47756e3562e3c69c54c1f222d5"
    )
    integration = payload["integration"]
    assert integration["identity_attention_path_modified"] is False
    assert integration["grid"] == [32, 32]
    assert integration["token_count"] == 1024
    assert integration["control_channel_order"] == ["composition", "pose", "prop"]
    assert integration["actual_sd35_transformer_block_index"] == 0
    assert payload["zero_residual_parity"] == {
        "max_abs_error": 0.0,
        "bitwise_equal": True,
        "tolerance": 0.0,
    }
    for branch in payload["single_channel_locality"].values():
        assert branch["active_token_count"] > 0
        assert branch["inside_effect_nonzero"] is True
        assert branch["outside_max_abs_delta"] == 0.0
        assert branch["outside_leakage_below_tolerance"] is True
    combined = payload["combined_control"]
    assert combined["union_active_token_count"] == 109
    assert combined["outside_union_max_abs_delta"] == 0.0
    assert combined["bounded_below_one_percent"] is True
    guards = payload["guards"]
    assert guards["actual_transformer_weights_loaded"] is True
    assert guards["denoise_performed"] is False
    assert guards["latents_created"] is False
    assert guards["vae_instantiated"] is False
    assert guards["image_generation_performed"] is False
    assert guards["next_full_scene_attempt_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r7_r3_full_registration_preserves_model_and_lifecycle() -> None:
    payload = json.loads(R21_R7_R3_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_FULL_38_BLOCK_EXPLICIT_CONTROL_REGISTRATION"
    smoke = payload["registration_smoke"]
    assert smoke["status"] == "PASS"
    assert smoke["transformer_blocks"] == 38
    assert smoke["registered_control_hooks"] == 38
    assert smoke["control_state_keys"] == ["explicit_spatial_control.channel_vectors"]
    assert smoke["non_control_state_changed"] is False
    assert smoke["zero_parity_all_blocks"] is True
    assert smoke["lifecycle_restored_after_unregister"] is True
    assert smoke["dtype"] == "torch.float16"
    assert smoke["device"] == "cpu"
    assert smoke["cuda_initialized"] is False
    assert [layer["index"] for layer in smoke["layers"]] == list(range(38))
    assert all(
        layer["parameter_identity_preserved"]
        and layer["identity_processor_preserved"]
        and layer["hook_delta"] == 1
        and layer["scale"] == 0.0
        and layer["zero_parity"]
        for layer in smoke["layers"]
    )
    guards = payload["guards"]
    assert guards["transformer_forward_called"] is False
    assert guards["denoise_performed"] is False
    assert guards["latents_created"] is False
    assert guards["vae_instantiated"] is False
    assert guards["image_generation_performed"] is False
    assert guards["next_full_scene_attempt_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r7_r4_rejects_all_block_control_amplification() -> None:
    payload = json.loads(R21_R7_R4_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["control_scale"] == 0.01
    assert payload["union_active_token_count"] == 109
    assert payload["identity_scale"] == 0.0
    assert payload["identity_processors_preserved"] is True
    metrics = payload["block_metrics"]
    assert [item["block"] for item in metrics] == list(range(38))
    assert metrics[0]["outside_mean_abs_delta"] == 0.0
    assert metrics[0]["localization_ratio"] > 100.0
    assert all(item["finite"] for item in metrics)
    summary = payload["summary"]
    assert summary["block0_localized"] is True
    assert summary["all_blocks_finite"] is True
    assert summary["max_amplification_vs_block0"] > summary["amplification_limit"]
    assert summary["max_relative_global_delta"] < summary["relative_delta_limit"]
    assert summary["final_output_mean_abs_delta"] > 0.0
    guards = payload["guards"]
    assert guards["full_transformer_forward_count"] == 2
    assert guards["scheduler_step_called"] is False
    assert guards["trajectory_run"] is False
    assert guards["vae_called"] is False
    assert guards["image_generation_performed"] is False
    assert guards["next_full_scene_attempt_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r7_r4_r1_selects_only_late_control_window() -> None:
    payload = json.loads(R21_R7_R4_R1_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_BLOCK_WINDOW_ISOLATION"
    fixture = payload["negative_fixture"]
    assert fixture["sha256"] == ("1d53672609763748712a449a27dc8578d50310e15c38879f52f46a0cc3e8b0a0")
    assert fixture["status"] == "FAIL"
    assert fixture["all_block_profile_forbidden"] is True
    assert payload["windows"] == {
        "early": list(range(0, 8)),
        "middle": list(range(12, 20)),
        "late": list(range(28, 38)),
    }
    assert payload["eligible_profiles"] == ["late"]
    assert payload["selected_profile"] == "late"
    assert payload["identity_processors_preserved"] is True
    profiles = payload["profiles"]
    assert profiles["early"]["eligible"] is False
    assert profiles["middle"]["eligible"] is False
    assert profiles["late"]["eligible"] is True
    assert all(profile["pre_onset_clean"] for profile in profiles.values())
    assert all(profile["all_blocks_finite"] for profile in profiles.values())
    threshold = payload["thresholds"]["maximum_relative_global_delta"]
    assert profiles["early"]["max_relative_global_delta"] > threshold
    assert profiles["middle"]["max_relative_global_delta"] > threshold
    assert profiles["late"]["max_relative_global_delta"] < threshold
    assert profiles["late"]["terminal_localization_ratio"] > 1.0
    assert all(
        item["global_mean_abs_delta"] == 0.0 for item in profiles["late"]["block_metrics"][:28]
    )
    guards = payload["guards"]
    assert guards["full_transformer_forward_count"] == 4
    assert guards["scheduler_step_called"] is False
    assert guards["trajectory_run"] is False
    assert guards["vae_called"] is False
    assert guards["image_generation_performed"] is False
    assert guards["next_full_scene_attempt_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r7_r4_r2_rejects_full_time_late_block_trajectory() -> None:
    payload = json.loads(R21_R7_R4_R2_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["explicit_profile"] == {
        "active_blocks": list(range(28, 38)),
        "scale": 0.01,
    }
    for branch in (payload["baseline"], payload["active"]):
        assert branch["profile_count"] == 24
        assert branch["latent_critic"]["blocked"] is False
        assert branch["latent_critic"]["status"] == ("NO_PERSISTENT_ABSOLUTE_DISCONTINUITY")
    comparison = payload["comparison"]
    assert len(comparison["steps"]) == 24
    assert comparison["all_steps_finite"] is True
    assert comparison["identity_events_match"] is True
    thresholds = comparison["thresholds"]
    assert comparison["max_relative_latent_delta"] > thresholds["maximum_relative_latent_delta"]
    assert comparison["final_spatial_ratio"] < thresholds["minimum_final_spatial_ratio"]
    assert comparison["minimum_update_norm_ratio"] >= thresholds["minimum_update_norm_ratio"]
    assert comparison["maximum_update_norm_ratio"] <= thresholds["maximum_update_norm_ratio"]
    assert comparison["steps"][0]["spatial_ratio"] > 1.0
    assert comparison["steps"][-1]["spatial_ratio"] < 1.0
    guards = payload["guards"]
    assert guards["transformer_forward_count"] == 48
    assert guards["scheduler_step_count"] == 48
    assert guards["trajectory_count"] == 2
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["next_full_scene_attempt_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False


def test_r7_r4_r3_rejects_all_coarse_temporal_windows() -> None:
    payload = json.loads(R21_R7_R4_R3_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    fixture = payload["negative_fixture"]
    assert fixture["sha256"] == ("4c167c3fe8ad280fe027867ae28cd862669c25e46a6404d122018174f297d5e1")
    assert fixture["status"] == "FAIL"
    assert fixture["full_time_profile_forbidden"] is True
    assert payload["spatial_profile"] == {
        "active_blocks": list(range(28, 38)),
        "scale": 0.01,
    }
    assert payload["windows"] == {
        "early": list(range(0, 8)),
        "middle": list(range(8, 16)),
        "late": list(range(16, 24)),
    }
    assert payload["baseline"]["profile_count"] == 24
    assert payload["baseline"]["latent_critic"]["blocked"] is False
    assert payload["eligible_profiles"] == []
    assert payload["selected_profile"] is None

    thresholds = payload["thresholds"]
    profiles = payload["profiles"]
    assert set(profiles) == {"early", "middle", "late"}
    for name, profile in profiles.items():
        assert profile["active_steps"] == payload["windows"][name]
        assert len(profile["steps"]) == 24
        assert profile["latent_critic"]["blocked"] is False
        assert profile["all_steps_finite"] is True
        assert profile["identity_events_match"] is True
        assert profile["eligible"] is False
        assert profile["minimum_update_norm_ratio"] >= thresholds["minimum_update_norm_ratio"]
        assert profile["maximum_update_norm_ratio"] <= thresholds["maximum_update_norm_ratio"]
        assert profile["final_spatial_ratio"] < thresholds["minimum_final_spatial_ratio"]
    assert (
        profiles["early"]["max_relative_latent_delta"] > thresholds["maximum_relative_latent_delta"]
    )
    assert (
        profiles["middle"]["max_relative_latent_delta"]
        < thresholds["maximum_relative_latent_delta"]
    )
    assert (
        profiles["late"]["max_relative_latent_delta"] < thresholds["maximum_relative_latent_delta"]
    )

    guards = payload["guards"]
    assert guards["trajectory_count"] == 4
    assert guards["transformer_forward_count"] == 96
    assert guards["scheduler_step_count"] == 96
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["decode_authorized"] is False
    assert guards["next_full_scene_attempt_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False
    assert guards["production_profile_changed"] is False


def test_r7_r4_r4_selects_only_terminal_micro_window() -> None:
    payload = json.loads(R21_R7_R4_R4_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS_DENOISE_TIME_WINDOW_ISOLATION"
    fixture = payload["negative_fixture"]
    assert fixture == {
        "path": str(R21_R7_R4_R3_RESULT.resolve()),
        "sha256": ("8646c1104d6d9ccf304aa9d4658ae5e6bc2183d8dc589275f96564d0b2e2a7fb"),
        "status": "FAIL",
        "coarse_temporal_profiles_forbidden": True,
    }
    assert payload["spatial_profile"] == {
        "active_blocks": list(range(28, 38)),
        "scale": 0.01,
    }
    assert payload["windows"] == {
        "late_early": list(range(16, 20)),
        "late_middle": list(range(20, 22)),
        "late_terminal": list(range(22, 24)),
    }
    assert payload["eligible_profiles"] == ["late_terminal"]
    assert payload["selected_profile"] == "late_terminal"

    thresholds = payload["thresholds"]
    profiles = payload["profiles"]
    assert profiles["late_early"]["eligible"] is False
    assert profiles["late_middle"]["eligible"] is False
    assert profiles["late_terminal"]["eligible"] is True
    for name, profile in profiles.items():
        assert profile["active_steps"] == payload["windows"][name]
        assert len(profile["steps"]) == 24
        assert profile["latent_critic"]["blocked"] is False
        assert profile["all_steps_finite"] is True
        assert profile["identity_events_match"] is True
        first_active = profile["active_steps"][0]
        assert all(item["global_mean_abs_delta"] == 0.0 for item in profile["steps"][:first_active])
        assert profile["max_relative_latent_delta"] < thresholds["maximum_relative_latent_delta"]
        assert profile["minimum_update_norm_ratio"] >= thresholds["minimum_update_norm_ratio"]
        assert profile["maximum_update_norm_ratio"] <= thresholds["maximum_update_norm_ratio"]
    assert profiles["late_early"]["final_spatial_ratio"] < thresholds["minimum_final_spatial_ratio"]
    assert (
        profiles["late_middle"]["final_spatial_ratio"] < thresholds["minimum_final_spatial_ratio"]
    )
    assert (
        profiles["late_terminal"]["final_spatial_ratio"]
        >= thresholds["minimum_final_spatial_ratio"]
    )

    guards = payload["guards"]
    assert guards["evaluated_trajectory_count"] == 4
    assert guards["executed_trajectory_count"] == 3
    assert guards["transformer_forward_count"] == 72
    assert guards["scheduler_step_count"] == 72
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["baseline_cache_reused"] is True
    assert guards["decode_authorized"] is False
    assert guards["next_full_scene_attempt_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False
    assert guards["production_profile_changed"] is False


def test_r7_r4_r5_rejects_seed_specific_absolute_critic_blocker() -> None:
    payload = json.loads(R21_R7_R4_R5_RESULT.read_text(encoding="utf-8"))
    assert payload["status"] == "FAIL"
    assert payload["seed"] == 420918
    assert payload["windows"] == {"confirmation": [22, 23]}
    assert payload["eligible_profiles"] == []
    assert payload["selected_profile"] is None
    fixture = payload["negative_fixture"]
    assert fixture["sha256"] == ("18b067c23498e5c7ed27a9873f1ebdb0beb8125588899ac3f222588a3b0a0bdc")
    assert fixture["status"] == "PASS_DENOISE_TIME_WINDOW_ISOLATION"
    assert fixture["terminal_profile_source_locked"] is True

    baseline_critic = payload["baseline"]["latent_critic"]
    active = payload["profiles"]["confirmation"]
    active_critic = active["latent_critic"]
    for critic in (baseline_critic, active_critic):
        assert critic["blocked"] is True
        assert critic["status"] == "PERSISTENT_STATIC_INTERIOR_DISCONTINUITY"
        assert critic["axis"] == "row"
        assert critic["onset_step"] == 22
        assert critic["boundary_index"] == 36
    assert abs(baseline_critic["ratio"] - active_critic["ratio"]) < 0.01
    assert abs(baseline_critic["robust_z"] - active_critic["robust_z"]) < 0.1

    thresholds = payload["thresholds"]
    assert active["max_relative_latent_delta"] < thresholds["maximum_relative_latent_delta"]
    assert active["minimum_update_norm_ratio"] >= thresholds["minimum_update_norm_ratio"]
    assert active["maximum_update_norm_ratio"] <= thresholds["maximum_update_norm_ratio"]
    assert active["final_spatial_ratio"] >= thresholds["minimum_final_spatial_ratio"]
    assert active["all_steps_finite"] is True
    assert active["identity_events_match"] is True
    assert active["eligible"] is False
    assert all(item["global_mean_abs_delta"] == 0.0 for item in active["steps"][:22])

    guards = payload["guards"]
    assert guards["evaluated_trajectory_count"] == 2
    assert guards["executed_trajectory_count"] == 2
    assert guards["transformer_forward_count"] == 48
    assert guards["scheduler_step_count"] == 48
    assert guards["vae_calls"] == {"forward": 0, "decode": 0}
    assert guards["images_created"] == 0
    assert guards["baseline_cache_reused"] is False
    assert guards["decode_authorized"] is False
    assert guards["next_full_scene_attempt_authorized"] is False
    assert guards["phase4l_closed"] is False
    assert guards["phase4n_opened"] is False
