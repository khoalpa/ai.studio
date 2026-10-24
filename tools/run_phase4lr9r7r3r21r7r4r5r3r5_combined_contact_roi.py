from __future__ import annotations

from typing import Any

import run_phase4lr9r7r3r21r7r4r5r3r4_pose_contact_isolation as runner
import torch
import torch.nn.functional as functional
from run_phase4lr9r7r3r21r7r4_full_transformer_control_ab import GRID

runner.R3_RESULT = runner.RESULT_PATH
runner.OUTPUT_ROOT = runner.BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r5-combined-contact-roi-v1")
runner.RESULT_PATH = runner.OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r5-result.json"
runner.PHASE = "4L-R9-R7-R3-R21-R7-R4-R5-R3-R5"
runner.PASS_STATUS = "PASS_COMBINED_SCHEDULE_AND_CONTACT_ROI_ISOLATION"
runner.EXPECTED_PRIOR_CLOSURE = "OPEN_PENDING_STRUCTURAL_CHANNEL_REDESIGN"
runner.PASS_CLOSURE = "OPEN_PENDING_LATENT_TRAJECTORY_AB"
runner.FAIL_CLOSURE = "OPEN_PENDING_COMBINED_STRUCTURAL_REDESIGN"
runner.COMBINED_PROFILE = "early_all_contact10"
runner.REQUIRE_NON_EARLY_PROFILE = False
runner.CHANNEL_ORDER = ("pose", "contact_core", "contact_6", "contact_10", "prop")
runner.WINDOWS = {"early_middle": list(range(18, 23))}
runner.PROFILES = {
    "early_pose_prop": {
        "channels": ["pose", "prop"],
        "window": "early_middle",
        "early_framing": True,
    },
    "early_contact_core": {
        "channels": ["contact_core"],
        "window": "early_middle",
        "early_framing": True,
    },
    "early_contact6": {
        "channels": ["contact_6"],
        "window": "early_middle",
        "early_framing": True,
    },
    "early_contact10": {
        "channels": ["contact_10"],
        "window": "early_middle",
        "early_framing": True,
    },
    "early_all_core": {
        "channels": ["pose", "contact_core", "prop"],
        "window": "early_middle",
        "early_framing": True,
    },
    "early_all_contact6": {
        "channels": ["pose", "contact_6", "prop"],
        "window": "early_middle",
        "early_framing": True,
    },
    "early_all_contact10": {
        "channels": ["pose", "contact_10", "prop"],
        "window": "early_middle",
        "early_framing": True,
    },
}


def split_controls() -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    raw = runner.load_control_tokens()
    framing = raw[..., :1]
    pose = raw[..., 1].reshape(1, 1, *GRID).float()
    prop = raw[..., 2].reshape(1, 1, *GRID).float()
    contacts: dict[str, torch.Tensor] = {}
    for name, kernel in (("contact_core", 3), ("contact_6", 5), ("contact_10", 7)):
        near_prop = functional.max_pool2d(
            prop, kernel_size=kernel, stride=1, padding=kernel // 2
        ).bool()
        contacts[name] = (pose.bool() & near_prop).reshape(1, -1, 1)
    pose_without_contact = pose.bool() & ~contacts["contact_core"].reshape(1, 1, *GRID)
    return framing, {
        "pose": pose_without_contact.reshape(1, -1, 1),
        **contacts,
        "prop": prop.bool().reshape(1, -1, 1),
    }


def negative_middle_dominance(prior: dict[str, Any]) -> float:
    return prior["profiles"]["combined_structural_full"]["minimum_spatial_dominance_ratio"]


runner.split_controls = split_controls
runner.negative_middle_dominance = negative_middle_dominance


if __name__ == "__main__":
    runner.main()
