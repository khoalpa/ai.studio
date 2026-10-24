from __future__ import annotations

import hashlib
import json
from pathlib import Path

import torch

from ai_story.explicit_spatial_control import (
    ExplicitSpatialControlResidual,
    StagedExplicitControlRegistration,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R1_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r1-reject-and-structural-design-v1")
R1_RESULT = R1_ROOT / "phase4lr9r7r3r21r7r4r5r3r1-result.json"
CONTRACT_PATH = R1_ROOT / "structural-conditioning-contract.json"
OUTPUT_ROOT = BASELINE_ROOT / ("phase4lr9r7r3r21r7r4r5r3r2-structural-registration-v1")
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r4r5r3r2-result.json"
EXPECTED_CONTRACT_SHA256 = "43aff9756ab14039321d2f18fc83208a39d5134c77fc59971d2005bb87f405a8"


class ProbeBlock(torch.nn.Module):
    def forward(self, hidden_states: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return hidden_states[:, :1], hidden_states


class ProbeTransformer(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.transformer_blocks = torch.nn.ModuleList(ProbeBlock() for _ in range(38))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scales(blocks: list[int], scale: float) -> list[float]:
    return [scale if index in blocks else 0.0 for index in range(38)]


def main() -> None:
    if RESULT_PATH.exists():
        previous = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        if previous.get("status") != "FAIL":
            raise RuntimeError("R3-R2 checkpoint already passed; refusing to overwrite")
    r1 = json.loads(R1_RESULT.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract_digest = sha256(CONTRACT_PATH)
    if (
        r1["status"] != "PASS_REJECTED_ATTEMPT_AND_STRUCTURAL_SPIKE_DESIGN"
        or contract_digest != EXPECTED_CONTRACT_SHA256
        or r1["structural_conditioning"]["contract_sha256"] != contract_digest
    ):
        raise RuntimeError("R3-R1 checkpoint or structural contract changed")

    stages = {stage["id"]: stage for stage in contract["stages"]}
    transformer = ProbeTransformer()
    hidden = torch.arange(32 * 16, dtype=torch.bfloat16).reshape(1, 32, 16)
    framing_controls = torch.zeros((1, 32, 2), dtype=torch.bfloat16)
    framing_controls[:, 3:9, 0] = 1
    framing_controls[:, 23:29, 1] = 1
    pose_controls = torch.zeros((1, 32, 3), dtype=torch.bfloat16)
    pose_controls[:, 12:20, :] = 1
    adapters = {
        "early_framing_cast": ExplicitSpatialControlResidual(
            torch.eye(2, 16, dtype=torch.bfloat16)
        ),
        "middle_pose_contact": ExplicitSpatialControlResidual(
            torch.eye(3, 16, dtype=torch.bfloat16)
        ),
    }
    before_state = set(transformer.state_dict())
    registration = StagedExplicitControlRegistration(transformer, adapters)
    registered_state = set(transformer.state_dict()) - before_state
    hook_counts = [len(block._forward_hooks) for block in transformer.transformer_blocks]

    zero_results: list[dict[str, object]] = []
    registration.configure_stage("early_framing_cast", framing_controls, [0.0] * 38)
    registration.configure_stage("middle_pose_contact", pose_controls, [0.0] * 38)
    for index, block in enumerate(transformer.transformer_blocks):
        _, output = block(hidden)
        zero_results.append(
            {
                "block": index,
                "bitwise_equal": torch.equal(output, hidden),
                "max_abs_error": float((output.float() - hidden.float()).abs().max()),
            }
        )

    route_results: dict[str, dict[str, object]] = {}
    stage_inputs = {
        "early_framing_cast": framing_controls,
        "middle_pose_contact": pose_controls,
    }
    route_hidden = torch.zeros_like(hidden)
    for name in stage_inputs:
        active_blocks = stages[name]["active_blocks"]
        for stage_name, controls in stage_inputs.items():
            registration.configure_stage(
                stage_name,
                controls,
                scales(active_blocks, 0.001) if stage_name == name else [0.0] * 38,
            )
        changed_blocks = []
        for index, block in enumerate(transformer.transformer_blocks):
            _, output = block(route_hidden)
            if not torch.equal(output, route_hidden):
                changed_blocks.append(index)
        route_results[name] = {
            "expected_active_blocks": active_blocks,
            "observed_changed_blocks": changed_blocks,
            "exact_window_match": changed_blocks == active_blocks,
        }

    registration.unregister()
    lifecycle_restored = set(transformer.state_dict()) == before_state and all(
        not block._forward_hooks for block in transformer.transformer_blocks
    )
    passed = (
        all(item["bitwise_equal"] for item in zero_results)
        and all(item["exact_window_match"] for item in route_results.values())
        and all(count == 1 for count in hook_counts)
        and lifecycle_restored
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R4-R5-R3-R2",
        "status": "PASS_STRUCTURAL_REGISTRATION_AND_ZERO_PARITY" if passed else "FAIL",
        "contract_sha256": contract_digest,
        "registration": {
            "transformer_blocks": 38,
            "registered_hooks": sum(hook_counts),
            "independent_stages": sorted(adapters),
            "registered_state_keys": sorted(registered_state),
            "dtype": str(hidden.dtype),
            "device": str(hidden.device),
            "zero_control_bitwise_parity_all_blocks": all(
                item["bitwise_equal"] for item in zero_results
            ),
            "zero_results": zero_results,
            "routing": route_results,
            "lifecycle_restored_after_unregister": lifecycle_restored,
        },
        "phase4l_closure": {
            "status": "OPEN_PENDING_SINGLE_STEP_STRUCTURAL_AB",
            "newly_satisfied": [
                "independent_stage_registration",
                "exact_zero_control_parity",
                "block_window_routing",
                "registration_lifecycle_cleanup",
            ],
            "all_requirements_satisfied": False,
        },
        "guards": {
            "production_transformer_loaded": False,
            "full_transformer_forward_called": False,
            "scheduler_called": False,
            "denoise_performed": False,
            "latents_created": False,
            "vae_called": False,
            "images_created": 0,
            "new_generation_authorized": False,
            "production_profile_changed": False,
            "source_package_modified": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
        },
    }
    write_json(RESULT_PATH, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
