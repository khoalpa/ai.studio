from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import torch

from ai_story.explicit_spatial_control import (
    ExplicitControlRegistration,
    ExplicitSpatialControlResidual,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image"
R2_RESULT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r2-explicit-control-dry-run-v1/"
    "phase4lr9r7r3r21r7r2-result.json"
)
OUTPUT_ROOT = BASELINE_ROOT / (
    "phase4lr9r7r3r21r7r3-full-control-registration-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r21r7r3-result.json"
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
ADAPTER_WEIGHT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter/ip-adapter.bin")
BLOCK_COUNT = 38
CHANNEL_COUNT = 3
HIDDEN_SIZE = 2432
SEED = 420917


def parameter_ids(module: torch.nn.Module) -> list[int]:
    return [id(parameter) for parameter in module.parameters()]


def worker() -> dict[str, Any]:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from diffusers import SD3Transformer2DModel

    started = time.perf_counter()
    transformer = SD3Transformer2DModel.from_pretrained(
        LARGE_ROOT,
        subfolder="transformer",
        local_files_only=True,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
    )
    state = torch.load(ADAPTER_WEIGHT, map_location="cpu", weights_only=True)
    transformer._load_ip_adapter_weights(state, low_cpu_mem_usage=True)
    del state
    gc.collect()

    blocks = transformer.transformer_blocks
    before_parameter_ids = [parameter_ids(block) for block in blocks]
    before_processor_ids = [id(block.attn.processor) for block in blocks]
    before_hook_counts = [len(block._forward_hooks) for block in blocks]
    before_state_keys = set(transformer.state_dict().keys())

    generator = torch.Generator(device="cpu").manual_seed(SEED)
    vectors = torch.randn((CHANNEL_COUNT, HIDDEN_SIZE), generator=generator)
    control = ExplicitSpatialControlResidual(vectors).to(dtype=torch.float16)
    registration = ExplicitControlRegistration(transformer, control)
    registration.configure(None, [0.0] * BLOCK_COUNT)

    registered_parameter_ids = [parameter_ids(block) for block in blocks]
    registered_processor_ids = [id(block.attn.processor) for block in blocks]
    registered_hook_counts = [len(block._forward_hooks) for block in blocks]
    registered_state_keys = set(transformer.state_dict().keys())
    control_state_keys = sorted(registered_state_keys - before_state_keys)
    non_control_state_changed = (
        registered_state_keys - set(control_state_keys) != before_state_keys
    )

    hidden = torch.randn((1, 16, HIDDEN_SIZE), generator=generator).half()
    token_controls = torch.ones((1, 16, CHANNEL_COUNT)).half()
    zero_outputs = [
        control(hidden, token_controls, scale=scale)
        for scale in registration.block_scales
    ]
    zero_parity_all_blocks = all(torch.equal(output, hidden) for output in zero_outputs)

    registration.unregister()
    after_hook_counts = [len(block._forward_hooks) for block in blocks]
    after_state_keys = set(transformer.state_dict().keys())
    lifecycle_restored = (
        after_hook_counts == before_hook_counts
        and after_state_keys == before_state_keys
        and not hasattr(transformer, ExplicitControlRegistration.module_name)
    )
    layer_records = [
        {
            "index": index,
            "parameter_identity_preserved": (
                registered_parameter_ids[index] == before_parameter_ids[index]
            ),
            "identity_processor_preserved": (
                registered_processor_ids[index] == before_processor_ids[index]
            ),
            "hook_delta": registered_hook_counts[index] - before_hook_counts[index],
            "scale": 0.0,
            "zero_parity": torch.equal(zero_outputs[index], hidden),
        }
        for index in range(BLOCK_COUNT)
    ]
    passed = (
        len(blocks) == BLOCK_COUNT
        and len(registration.handles) == 0
        and control_state_keys == [
            "explicit_spatial_control.channel_vectors"
        ]
        and not non_control_state_changed
        and zero_parity_all_blocks
        and lifecycle_restored
        and all(
            record["parameter_identity_preserved"]
            and record["identity_processor_preserved"]
            and record["hook_delta"] == 1
            and record["scale"] == 0.0
            and record["zero_parity"]
            for record in layer_records
        )
        and not torch.cuda.is_initialized()
    )
    result = {
        "status": "PASS" if passed else "FAIL",
        "transformer_class": transformer.__class__.__name__,
        "transformer_blocks": len(blocks),
        "registered_control_hooks": sum(
            registered_hook_counts[index] - before_hook_counts[index]
            for index in range(BLOCK_COUNT)
        ),
        "control_state_keys": control_state_keys,
        "non_control_state_changed": non_control_state_changed,
        "zero_parity_all_blocks": zero_parity_all_blocks,
        "lifecycle_restored_after_unregister": lifecycle_restored,
        "layers": layer_records,
        "dtype": str(control.channel_vectors.dtype),
        "device": str(control.channel_vectors.device),
        "cpu_only": True,
        "cuda_initialized": torch.cuda.is_initialized(),
        "load_registration_seconds": round(time.perf_counter() - started, 2),
    }
    del transformer, blocks, control, registration, zero_outputs
    gc.collect()
    return result


def run_worker() -> dict[str, Any]:
    environment = os.environ.copy()
    environment.update(
        {
            "CUDA_VISIBLE_DEVICES": "",
            "HF_HUB_OFFLINE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"Registration worker failed: {stderr[-4000:]}")
    lines = [line for line in stdout.splitlines() if line.startswith("{")]
    if not lines:
        raise RuntimeError(f"Registration worker returned no result: {stderr[-2000:]}")
    result = json.loads(lines[-1])
    result["stderr_tail"] = stderr[-500:] if stderr else ""
    return result


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker()), flush=True)
        return
    if RESULT_PATH.exists():
        raise RuntimeError("R21-R7-R3 already exists; refusing to overwrite checkpoint")
    prior = json.loads(R2_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_EXPLICIT_CONTROL_INTEGRATION_DRY_RUN":
        raise RuntimeError("R21-R7-R2 explicit control dry-run must pass")
    registration = run_worker()
    passed = registration["status"] == "PASS"
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R21-R7-R3",
        "status": "PASS_FULL_38_BLOCK_EXPLICIT_CONTROL_REGISTRATION"
        if passed
        else "FAIL",
        "registration_smoke": registration,
        "conclusion": (
            "All 38 SD3.5 Large blocks accept an isolated scale-zero explicit-control "
            "hook without replacing block parameters or IP-Adapter processors; hook and "
            "module state are fully removed during unregister lifecycle."
            if passed
            else "Explicit-control registration, parity, isolation, or lifecycle failed."
        ),
        "guards": {
            "subprocess_isolation": True,
            "cpu_only": True,
            "full_pipeline_loaded": False,
            "transformer_forward_called": False,
            "denoise_performed": False,
            "latents_created": False,
            "vae_instantiated": False,
            "image_generation_performed": False,
            "next_full_scene_attempt_authorized": False,
            "phase4l_closed": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    write_json(RESULT_PATH, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
