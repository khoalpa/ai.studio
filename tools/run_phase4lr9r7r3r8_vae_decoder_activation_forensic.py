from __future__ import annotations

import gc
import hashlib
import io
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import psutil
import torch
from PIL import Image
from run_phase4lr9r7r3r3_latent_trajectory_ab import (
    ADAPTER_ROOT,
    GUIDANCE_SCALE,
    LARGE_ROOT,
    NEGATIVE_PROMPT,
    PROMPT,
    REFERENCE,
    REFERENCE_CROP_BOX,
    REFERENCE_SHA256,
    SEED,
    SIGLIP_ROOT,
    STEPS,
    digest,
    gpu_used_mib,
)
from run_phase4lr9r7r3r5_late_step_decomposition import boundary_diagnostics

from ai_story.latent_discontinuity import (
    LatentDiscontinuityConfig,
    evaluate_latent_discontinuity,
    observation_from_profile,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
R7_RESULT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r7-vae-instrumented-canary-v1/phase4lr9r7r3r7-result.json"
)
OUTPUT_ROOT = PROJECT_ROOT / (
    "artifacts/baselines/real-v1/image/"
    "phase4lr9r7r3r8-vae-decoder-activation-forensic-v1"
)
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3r8-result.json"
WORKER_LOG = OUTPUT_ROOT / "worker.log"
TAIL_START = 16
CRITIC_CONFIG = LatentDiscontinuityConfig()


def tensor_sha256(tensor: torch.Tensor) -> str:
    return hashlib.sha256(
        tensor.detach().float().cpu().numpy().tobytes()
    ).hexdigest()


def image_sha256(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def first_tensor(value) -> torch.Tensor:
    if isinstance(value, torch.Tensor):
        return value
    if isinstance(value, (tuple, list)):
        for item in value:
            try:
                return first_tensor(item)
            except TypeError:
                continue
    if hasattr(value, "sample") and isinstance(value.sample, torch.Tensor):
        return value.sample
    raise TypeError(f"No tensor found in hook output {type(value)!r}")


def activation_record(name: str, tensor: torch.Tensor) -> dict:
    value = tensor.detach().float().cpu()
    diagnostics = boundary_diagnostics(value)
    height = int(value.shape[-2])
    width = int(value.shape[-1])
    row = diagnostics["row_boundaries"]
    column = diagnostics["column_boundaries"]
    return {
        "name": name,
        "shape": list(value.shape),
        "source_dtype": str(tensor.dtype),
        "finite": bool(torch.isfinite(value).all().item()),
        "rms": round(float(value.square().mean().sqrt().item()), 8),
        "row_maximum_normalized_position": round(
            (row["maximum_index"] + 0.5) / max(height - 1, 1), 8
        ),
        "column_maximum_normalized_position": round(
            (column["maximum_index"] + 0.5) / max(width - 1, 1), 8
        ),
        "boundaries": diagnostics,
    }


def worker() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from diffusers import StableDiffusion3Pipeline
    from transformers import SiglipImageProcessor, SiglipVisionModel

    pipe = StableDiffusion3Pipeline.from_pretrained(
        LARGE_ROOT,
        local_files_only=True,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    feature_extractor = SiglipImageProcessor.from_pretrained(
        SIGLIP_ROOT, local_files_only=True
    )
    image_encoder = SiglipVisionModel.from_pretrained(
        SIGLIP_ROOT,
        local_files_only=True,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    pipe.register_modules(
        feature_extractor=feature_extractor, image_encoder=image_encoder
    )
    pipe.load_ip_adapter(
        ADAPTER_ROOT,
        weight_name="ip-adapter.bin",
        image_encoder_folder=None,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    pipe.set_ip_adapter_scale(0.5)
    pipe.enable_model_cpu_offload(device="cuda")
    pipe.vae.disable_tiling()
    pipe.vae.disable_slicing()

    tail_profiles = []

    def capture_latents(_pipe, step_index, timestep, callback_kwargs):
        if step_index >= TAIL_START:
            latent = callback_kwargs["latents"].detach().cpu()
            tail_profiles.append(
                {
                    "step": int(step_index),
                    "timestep": float(timestep.item()),
                    "boundaries": boundary_diagnostics(latent),
                }
            )
        return callback_kwargs

    with Image.open(REFERENCE) as source:
        identity_crop = source.convert("RGB").crop(REFERENCE_CROP_BOX)
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    started = time.perf_counter()
    with torch.inference_mode():
        output = pipe(
            prompt=PROMPT,
            negative_prompt=NEGATIVE_PROMPT,
            ip_adapter_image=identity_crop,
            height=512,
            width=512,
            num_inference_steps=STEPS,
            guidance_scale=GUIDANCE_SCALE,
            num_images_per_prompt=1,
            generator=generator,
            output_type="latent",
            callback_on_step_end=capture_latents,
            callback_on_step_end_tensor_inputs=["latents"],
        )
    final_latent = output.images.detach()
    observations = []
    for item in tail_profiles:
        for axis, key in (
            ("row", "row_boundaries"),
            ("column", "column_boundaries"),
        ):
            observations.append(
                observation_from_profile(
                    step=item["step"],
                    axis=axis,
                    profile=item["boundaries"][key],
                )
            )
    critic = evaluate_latent_discontinuity(observations, CRITIC_CONFIG)
    if critic.blocked:
        raise RuntimeError(
            "Corrected latent critic blocked decoder forensic: "
            + json.dumps(asdict(critic))
        )

    activations = []
    hooks = []

    def register(name: str, module) -> None:
        def capture(_module, _inputs, output_value):
            activations.append(
                activation_record(name, first_tensor(output_value))
            )

        hooks.append(module.register_forward_hook(capture))

    absent_stages = []
    if pipe.vae.post_quant_conv is None:
        absent_stages.append("post_quant_conv")
    else:
        register("post_quant_conv", pipe.vae.post_quant_conv)
    register("decoder.conv_in", pipe.vae.decoder.conv_in)
    register("decoder.mid_block", pipe.vae.decoder.mid_block)
    for index, block in enumerate(pipe.vae.decoder.up_blocks):
        register(f"decoder.up_blocks.{index}", block)
    register("decoder.conv_norm_out", pipe.vae.decoder.conv_norm_out)
    register("decoder.conv_out", pipe.vae.decoder.conv_out)

    scaled_latent = (
        final_latent / pipe.vae.config.scaling_factor
    ) + pipe.vae.config.shift_factor
    decoder_input = activation_record("decoder_input", scaled_latent)
    decode_started = time.perf_counter()
    with torch.inference_mode():
        decoded = pipe.vae.decode(
            scaled_latent.to(pipe._execution_device), return_dict=False
        )[0]
    decode_seconds = round(time.perf_counter() - decode_started, 3)
    for hook in hooks:
        hook.remove()
    in_memory_image = pipe.image_processor.postprocess(
        decoded, output_type="pil"
    )[0]
    in_memory_hash = image_sha256(in_memory_image)
    decoded_record = activation_record("decoded_tensor", decoded)
    metrics = {
        "generation_seconds": round(time.perf_counter() - started, 3),
        "decode_seconds": decode_seconds,
        "seed": SEED,
        "steps": STEPS,
        "guidance_scale": GUIDANCE_SCALE,
        "ip_adapter_scale": 0.5,
        "final_latent_sha256": tensor_sha256(final_latent),
        "latent_critic": asdict(critic),
        "decoder_input": decoder_input,
        "decoder_activations": activations,
        "absent_decoder_stages": absent_stages,
        "decoded_tensor": decoded_record,
        "in_memory_png_sha256": in_memory_hash,
        "images_persisted": 0,
        "vae_decode_calls": 1,
        "vae_tiling_enabled": bool(pipe.vae.use_tiling),
        "vae_slicing_enabled": bool(pipe.vae.use_slicing),
        "cuda_max_allocated_mib": round(
            torch.cuda.max_memory_allocated() / 1024**2, 2
        ),
    }
    pipe.maybe_free_model_hooks()
    del output, final_latent, scaled_latent, decoded, in_memory_image
    del generator, identity_crop, feature_extractor, image_encoder, pipe
    gc.collect()
    torch.cuda.empty_cache()
    metrics["cuda_allocated_mib_after_cleanup"] = round(
        torch.cuda.memory_allocated() / 1024**2, 2
    )
    print(json.dumps(metrics), flush=True)


def strongest_axis(record: dict) -> dict:
    row = record["boundaries"]["row_boundaries"]
    column = record["boundaries"]["column_boundaries"]
    if row["maximum_robust_z"] >= column["maximum_robust_z"]:
        axis = "row"
        profile = row
        position = record["row_maximum_normalized_position"]
    else:
        axis = "column"
        profile = column
        position = record["column_maximum_normalized_position"]
    return {
        "axis": axis,
        "maximum": profile["maximum"],
        "ratio": profile["maximum_to_median_ratio"],
        "robust_z": profile["maximum_robust_z"],
        "normalized_position": position,
    }


def interior_profile_signal(values: list[float]) -> dict:
    margin = max(2, round(len(values) * 0.02))
    interior = values[margin : len(values) - margin]
    median = statistics.median(interior)
    mad = statistics.median(abs(value - median) for value in interior)
    maximum = max(interior)
    index = values.index(maximum)
    return {
        "maximum": maximum,
        "maximum_index": index,
        "normalized_position": round((index + 0.5) / len(values), 8),
        "ratio": round(maximum / max(median, 1e-12), 8),
        "robust_z": round(
            (maximum - median) / max(1.4826 * mad, 1e-12), 8
        ),
    }


def target_neighborhood_signal(record: dict, target_position: float) -> dict:
    values = record["boundaries"]["row_boundaries"]["values"]
    margin = max(2, round(len(values) * 0.02))
    interior = values[margin : len(values) - margin]
    median = statistics.median(interior)
    mad = statistics.median(abs(value - median) for value in interior)
    center = round(target_position * len(values) - 0.5)
    radius = max(2, round(len(values) * 0.015))
    start = max(margin, center - radius)
    stop = min(len(values) - margin, center + radius + 1)
    index = max(range(start, stop), key=lambda item: values[item])
    maximum = values[index]
    return {
        "name": record["name"],
        "maximum": maximum,
        "maximum_index": index,
        "normalized_position": round((index + 0.5) / len(values), 8),
        "robust_z": round(
            (maximum - median) / max(1.4826 * mad, 1e-12), 8
        ),
    }


def build_analysis(smoke: dict) -> dict:
    records = [
        smoke["decoder_input"],
        *smoke["decoder_activations"],
        smoke["decoded_tensor"],
    ]
    sequence = [
        {"name": record["name"], **strongest_axis(record)}
        for record in records
    ]
    target_position = smoke["decoder_input"][
        "row_maximum_normalized_position"
    ]
    target_trace = [
        target_neighborhood_signal(record, target_position)
        for record in records
    ]
    target_jumps = [
        {
            "from": previous["name"],
            "to": current["name"],
            "robust_z_delta": round(
                current["robust_z"] - previous["robust_z"], 8
            ),
        }
        for previous, current in zip(target_trace, target_trace[1:])
    ]
    largest_target_jump = max(
        target_jumps, key=lambda item: item["robust_z_delta"]
    )
    interior_sequence = []
    for record in records:
        row = interior_profile_signal(
            record["boundaries"]["row_boundaries"]["values"]
        )
        column = interior_profile_signal(
            record["boundaries"]["column_boundaries"]["values"]
        )
        strongest = row if row["robust_z"] >= column["robust_z"] else column
        interior_sequence.append(
            {
                "name": record["name"],
                "axis": "row" if strongest is row else "column",
                **strongest,
            }
        )
    input_target_z = target_trace[0]["robust_z"]
    output_target_z = target_trace[-1]["robust_z"]
    if input_target_z >= 3.5 and output_target_z > input_target_z:
        interpretation = "LATENT_SEED_WITH_DECODER_AMPLIFICATION"
    elif input_target_z < 3.5 <= output_target_z:
        interpretation = "DECODER_GENERATED_DISCONTINUITY"
    else:
        interpretation = "NO_TARGET_DISCONTINUITY_AMPLIFICATION"
    return {
        "layer_sequence_legacy_including_edges": sequence,
        "interior_layer_sequence": interior_sequence,
        "target_row_normalized_position": target_position,
        "target_neighborhood_trace": target_trace,
        "largest_target_robust_z_jump": largest_target_jump,
        "interpretation": interpretation,
    }


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    if "--reanalyze-existing" in sys.argv:
        existing = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        existing["analysis"] = build_analysis(existing["smoke"])
        RESULT_PATH.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(existing["analysis"], ensure_ascii=False))
        return
    prior = json.loads(R7_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "AUTO_REJECT_AWAITING_MANUAL_REVIEW":
        raise RuntimeError("R3-R7 rejected canary is required before R3-R8")
    if not REFERENCE.is_file() or digest(REFERENCE) != REFERENCE_SHA256:
        raise RuntimeError("Locked identity reference is missing or changed")
    if RESULT_PATH.exists():
        raise RuntimeError("R3-R8 already exists; refusing to repeat forensic")

    baseline_gpu = gpu_used_mib()
    env = os.environ.copy()
    env.update(
        {
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TRANSFORMERS_VERBOSITY": "error",
            "DIFFUSERS_VERBOSITY": "error",
            "PYTHONUNBUFFERED": "1",
        }
    )
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with WORKER_LOG.open("w+", encoding="utf-8") as worker_log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            stdout=worker_log,
            stderr=worker_log,
            text=True,
            env=env,
        )
        root = psutil.Process(process.pid)
        peak_rss = 0
        peak_gpu = baseline_gpu
        while process.poll() is None:
            try:
                tree = [root, *root.children(recursive=True)]
                peak_rss = max(
                    peak_rss,
                    sum(
                        item.memory_info().rss
                        for item in tree
                        if item.is_running()
                    ),
                )
                peak_gpu = max(peak_gpu, gpu_used_mib())
            except (psutil.NoSuchProcess, subprocess.CalledProcessError):
                pass
            time.sleep(0.5)
        worker_log.flush()
        worker_log.seek(0)
        stdout = worker_log.read()
    if process.returncode != 0:
        raise RuntimeError(f"R3-R8 forensic failed: {stdout[-12000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"R3-R8 worker returned no JSON: {stdout[-4000:]}")
    smoke = json.loads(lines[-1])
    smoke.update(
        {
            "peak_rss_gib": round(peak_rss / 1024**3, 2),
            "gpu_baseline_mib": baseline_gpu,
            "gpu_peak_mib": peak_gpu,
            "gpu_delta_mib": peak_gpu - baseline_gpu,
            "gpu_after_worker_exit_mib": gpu_used_mib(),
        }
    )
    expected_hash = prior["candidate_sha256"]
    reproduction_matches = smoke["in_memory_png_sha256"] == expected_hash
    records = [
        smoke["decoder_input"],
        *smoke["decoder_activations"],
        smoke["decoded_tensor"],
    ]
    passed = (
        reproduction_matches
        and smoke["latent_critic"]["blocked"] is False
        and smoke["vae_decode_calls"] == 1
        and smoke["images_persisted"] == 0
        and smoke["vae_tiling_enabled"] is False
        and smoke["vae_slicing_enabled"] is False
        and all(record["finite"] for record in records)
    )
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3-R8",
        "status": "PASS" if passed else "FAIL",
        "smoke": smoke,
        "analysis": build_analysis(smoke),
        "guards": {
            "reproduces_r7_in_memory": reproduction_matches,
            "bitmap_persisted": False,
            "single_vae_decode": smoke["vae_decode_calls"] == 1,
            "next_attempt_started": False,
            "climax_generated": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
        },
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
