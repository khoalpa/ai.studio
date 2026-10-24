from __future__ import annotations

import gc
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import torch
from PIL import Image, ImageStat

from ai_story.image_gate_profiles import (
    neutral_identity_portrait_gates,
    photorealistic_hand_prop_gates,
)
from ai_story.image_qa import LocalImageQualityAssessor
from ai_story.provider_config import configure_job

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LARGE_ROOT = Path("D:/project/ai.studio/models/stable-diffusion-3.5-large")
SIGLIP_ROOT = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384")
ADAPTER_ROOT = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter")
REFERENCE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1/youth-torn-paper-boat/work/characters/bo.png"
R2_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r2-identity-conditioning-dry-run-v1/phase4lr9r7r2-result.json"
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r3-isolated-identity-canary-v1"
CANDIDATE = OUTPUT_ROOT / "candidates/neutral-identity/attempt-1.png"
ASSESSMENT_PATH = OUTPUT_ROOT / "candidates/neutral-identity/attempt-1-assessment.json"
RESULT_PATH = OUTPUT_ROOT / "phase4lr9r7r3-result.json"
REFERENCE_CROP_BOX = (384, 0, 1152, 768)
REFERENCE_SHA256 = "5c253d4a48a1e72fa1632be78fdc2ab111a594b8714f4c39af911ab4b4fc3c29"
SEED = 420917
PROMPT = (
    "Photorealistic head-and-shoulders documentary portrait of one Vietnamese teenage boy, "
    "matching the reference identity, centered alone against a plain warm gray background, "
    "natural window daylight, neutral calm expression, realistic skin texture, realistic dark hair, "
    "simple plain shirt, camera photograph, 50mm lens, both hands and arms entirely outside the frame."
)
NEGATIVE_PROMPT = (
    "illustration, painting, anime, cartoon, CGI, 3D render, plastic skin, doll, extra person, twins, "
    "visible hands, fingers, props, objects, text, letters, caption, watermark, logo, deformed face, "
    "duplicated face, repeated eyes, repeated mouth, broken neck, extra limbs, malformed anatomy, blur"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gpu_used_mib() -> int:
    output = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return int(output.strip().splitlines()[0])


def worker() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from diffusers import StableDiffusion3Pipeline
    from transformers import SiglipImageProcessor, SiglipVisionModel

    if CANDIDATE.exists():
        raise RuntimeError("Attempt 1 already exists; refusing a second generation")
    pipe = StableDiffusion3Pipeline.from_pretrained(
        LARGE_ROOT,
        local_files_only=True,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    feature_extractor = SiglipImageProcessor.from_pretrained(SIGLIP_ROOT, local_files_only=True)
    image_encoder = SiglipVisionModel.from_pretrained(
        SIGLIP_ROOT,
        local_files_only=True,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    pipe.register_modules(feature_extractor=feature_extractor, image_encoder=image_encoder)
    pipe.load_ip_adapter(
        ADAPTER_ROOT,
        weight_name="ip-adapter.bin",
        image_encoder_folder=None,
        local_files_only=True,
        low_cpu_mem_usage=True,
    )
    pipe.set_ip_adapter_scale(0.5)
    pipe.enable_model_cpu_offload(device="cuda")
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
            num_inference_steps=24,
            guidance_scale=5.0,
            num_images_per_prompt=1,
            generator=generator,
        )
    image = output.images[0]
    CANDIDATE.parent.mkdir(parents=True, exist_ok=True)
    image.save(CANDIDATE, format="PNG")
    metrics = {
        "generation_seconds": round(time.perf_counter() - started, 2),
        "seed": SEED,
        "dimensions": list(image.size),
        "images_created": len(output.images),
        "candidate_sha256": digest(CANDIDATE),
        "pipeline_dtype": "torch.bfloat16",
        "ip_adapter_scale": 0.5,
        "steps": 24,
        "guidance_scale": 5.0,
        "identity_crop_box_in_memory": list(REFERENCE_CROP_BOX),
        "identity_crop_persisted": False,
        "cuda_max_allocated_mib": round(torch.cuda.max_memory_allocated() / 1024**2, 2),
    }
    pipe.maybe_free_model_hooks()
    del output, image, generator, identity_crop, feature_extractor, image_encoder, pipe
    gc.collect()
    torch.cuda.empty_cache()
    metrics["cuda_allocated_mib_after_cleanup"] = round(torch.cuda.memory_allocated() / 1024**2, 2)
    print(json.dumps(metrics), flush=True)


def assess_candidate() -> dict:
    data = CANDIDATE.read_bytes()
    settings = configure_job("local", None, "quality")["runtimes"]["diffusers"]["qa"]
    assessor = LocalImageQualityAssessor(settings)
    photorealism_gate = dict(photorealistic_hand_prop_gates()[0])
    anatomy_gate = {
        "probe_id": "portrait_anatomy_gate",
        "required": True,
        "expected": "one naturally proportioned human head, face, neck and two shoulders with realistic anatomy",
        "forbidden": [
            "a deformed face with asymmetric misplaced eyes or duplicated facial features",
            "extra limbs, visible malformed hands, or broken human anatomy",
        ],
        "minimum_expected_score": 0.24,
        "minimum_contrast_margin": 0.02,
    }
    regression_gates = neutral_identity_portrait_gates()
    try:
        primary = assessor.assess_fidelity_probes(
            data, fidelity_probes=[photorealism_gate, anatomy_gate]
        )
        regression = assessor.assess_fidelity_probes(data, fidelity_probes=regression_gates)
        candidate_image = Image.open(io.BytesIO(data)).convert("RGB")
        with Image.open(REFERENCE) as source:
            identity_reference = source.convert("RGB").crop(REFERENCE_CROP_BOX)
        identity_score = assessor._clip_similarity(candidate_image, reference=identity_reference)
        ocr = assessor._ocr(data)
        detected_text = "".join(character for character in ocr if character.isalnum())
        stat = ImageStat.Stat(candidate_image.resize((256, 256)))
        mean_luma = sum(stat.mean) / 3
        variance = sum(value * value for value in stat.stddev) / 3
    finally:
        assessor.unload()
    primary_by_id = {item["probe_id"]: item for item in primary["checks"]}
    regression_by_id = {item["probe_id"]: item for item in regression["checks"]}
    identity_threshold = float(settings.get("identity_threshold", 0.55))
    max_ocr = int(settings.get("maximum_ocr_characters", 0))
    gates = {
        "identity": {
            "status": "PASS" if identity_score is not None and identity_score >= identity_threshold else "FAIL",
            "method": "CLIP_IDENTITY_CROP_REFERENCE_SIMILARITY",
            "score": None if identity_score is None else round(identity_score, 4),
            "threshold": identity_threshold,
        },
        "photorealism": primary_by_id["photorealism_fidelity_gate"],
        "anatomy": primary_by_id["portrait_anatomy_gate"],
        "text_artifact": {
            "status": "PASS" if len(detected_text) <= max_ocr else "FAIL",
            "method": "OCR_ABSENCE",
            "detected_text": ocr[:120],
            "detected_character_count": len(detected_text),
            "maximum": max_ocr,
        },
        "localized_face_neck_anatomy": regression_by_id["localized_face_neck_anatomy_gate"],
        "single_subject": regression_by_id["single_subject_gate"],
        "portrait_framing": regression_by_id["head_shoulders_portrait_framing_gate"],
    }
    return {
        "status": "ASSESSED_PASS" if all(item["status"] == "PASS" for item in gates.values()) else "ASSESSED_FAIL",
        "gate_count": len(gates),
        "passed_gate_count": sum(item["status"] == "PASS" for item in gates.values()),
        "failed_gate_ids": [name for name, item in gates.items() if item["status"] != "PASS"],
        "gates": gates,
        "technical": {
            "dimensions": list(candidate_image.size),
            "mean_luma": round(mean_luma, 3),
            "variance": round(variance, 3),
        },
    }


def main() -> None:
    if "--worker" in sys.argv:
        worker()
        return
    prior = json.loads(R2_RESULT.read_text(encoding="utf-8"))
    if prior.get("status") != "PASS_READY_FOR_MANUAL_AUTHORIZATION":
        raise RuntimeError("Phase 4L-R9-R7-R2 must pass before R3 generation")
    if not REFERENCE.is_file() or digest(REFERENCE) != REFERENCE_SHA256:
        raise RuntimeError("Locked identity reference is missing or changed")
    if CANDIDATE.exists() or RESULT_PATH.exists():
        raise RuntimeError("R3 already has an attempt; refusing to generate again")

    baseline_gpu = gpu_used_mib()
    env = os.environ.copy()
    env.update({
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        "TRANSFORMERS_VERBOSITY": "error",
        "DIFFUSERS_VERBOSITY": "error",
        "PYTHONUNBUFFERED": "1",
    })
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    root = psutil.Process(process.pid)
    peak_rss = 0
    peak_gpu = baseline_gpu
    while process.poll() is None:
        try:
            tree = [root, *root.children(recursive=True)]
            peak_rss = max(peak_rss, sum(item.memory_info().rss for item in tree if item.is_running()))
            peak_gpu = max(peak_gpu, gpu_used_mib())
        except (psutil.NoSuchProcess, subprocess.CalledProcessError):
            pass
        time.sleep(0.5)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"R3 generation failed: {stderr[-8000:]}")
    lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"R3 worker returned no JSON: {stdout[-4000:]} {stderr[-4000:]}")
    generation = json.loads(lines[-1])
    generation.update({
        "peak_rss_gib": round(peak_rss / 1024**3, 2),
        "gpu_baseline_mib": baseline_gpu,
        "gpu_peak_mib": peak_gpu,
        "gpu_delta_mib": peak_gpu - baseline_gpu,
        "gpu_after_worker_exit_mib": gpu_used_mib(),
    })
    assessment = assess_candidate()
    ASSESSMENT_PATH.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    automatic_pass = assessment["status"] == "ASSESSED_PASS"
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R3",
        "status": "AWAITING_MANUAL_REVIEW" if automatic_pass else "AUTO_REJECT_AWAITING_MANUAL_REVIEW",
        "case_id": "youth-torn-paper-boat",
        "character_id": "bo",
        "attempt": 1,
        "attempt_count": 1,
        "seed": SEED,
        "candidate_path": str(CANDIDATE.resolve()),
        "candidate_sha256": digest(CANDIDATE),
        "assessment_path": str(ASSESSMENT_PATH.resolve()),
        "prompt": PROMPT,
        "negative_prompt": NEGATIVE_PROMPT,
        "automatic_qa": assessment,
        "generation": generation,
        "manual_review_required": True,
        "candidate_promotable": automatic_pass,
        "next_attempt_started": False,
        "climax_generated": False,
        "phase4n_opened": False,
        "production_profile_changed": False,
        "source_package_modified": False,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
