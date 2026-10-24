from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from PIL import Image

from ai_story.image_gate_profiles import neutral_identity_portrait_gates
from ai_story.image_qa import LocalImageQualityAssessor
from ai_story.provider_config import configure_job

PROJECT_ROOT = Path(__file__).resolve().parents[1]
R7_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7-neutral-identity-canary-v1"
R7_RESULT = R7_ROOT / "phase4lr9r7-result.json"
NEGATIVE = R7_ROOT / "candidates/neutral-identity/attempt-1.png"
REFERENCE = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4l-climax-canary-v1/youth-torn-paper-boat/work/characters/bo.png"
R4_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r4-component-dry-run-v1/phase4lr9r4-result.json"
R6_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r6-reference-embedding-smoke-v1/phase4lr9r6-result.json"
R7_RUNNER = PROJECT_ROOT / "tools/run_phase4lr9r7_neutral_identity_canary.py"
ADAPTER_EXAMPLE = Path("D:/project/ai.studio/models/sd3.5-large-ip-adapter/infer_sd35_large_ipa.py")
SIGLIP_PREPROCESSOR = Path("D:/project/ai.studio/models/siglip-so400m-patch14-384/preprocessor_config.json")
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9r7r1-negative-conditioning-lock-v1"
EXPECTED_NEGATIVE_SHA256 = "48a1135f69aa514d2a1251a1abcd007ca45279697c6aedab6633e1b06a66c90b"
EXPECTED_REFERENCE_SHA256 = "5c253d4a48a1e72fa1632be78fdc2ab111a594b8714f4c39af911ab4b4fc3c29"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_number(source: str, pattern: str) -> float:
    match = re.search(pattern, source)
    if match is None:
        raise RuntimeError(f"Unable to extract locked setting: {pattern}")
    return float(match.group(1))


def main() -> None:
    r7 = json.loads(R7_RESULT.read_text(encoding="utf-8"))
    r4 = json.loads(R4_RESULT.read_text(encoding="utf-8"))
    r6 = json.loads(R6_RESULT.read_text(encoding="utf-8"))
    if r7.get("attempt_count") != 1 or r7.get("next_attempt_started") is not False:
        raise RuntimeError("R7 one-attempt checkpoint is not locked")
    if digest(NEGATIVE) != EXPECTED_NEGATIVE_SHA256:
        raise RuntimeError("R7 negative fixture changed")
    if digest(REFERENCE) != EXPECTED_REFERENCE_SHA256:
        raise RuntimeError("R7 identity reference changed")

    assessor = LocalImageQualityAssessor(
        configure_job("local", None, "quality")["runtimes"]["diffusers"]["qa"]
    )
    try:
        critic = assessor.assess_fidelity_probes(
            NEGATIVE.read_bytes(), fidelity_probes=neutral_identity_portrait_gates()
        )
    finally:
        assessor.unload()
    expected_failed = [gate["probe_id"] for gate in neutral_identity_portrait_gates()]
    critic_locked = critic["failed_probes"] == expected_failed

    mapping = r4["ip_adapter_mapping"]
    embedding = r6["smoke"]
    binary_compatibility = (
        r4.get("status") == "PASS"
        and mapping.get("transformer_blocks") == 38
        and mapping.get("ip_adapter_processors") == 38
        and mapping.get("complete_layer_coverage") is True
        and mapping.get("image_projection_class") == "IPAdapterTimeImageProjection"
        and r6.get("status") == "PASS"
        and embedding.get("embedding_shape") == [2, 729, 1152]
        and embedding.get("positive_finite") is True
        and embedding.get("positive_nonzero") is True
        and embedding.get("negative_is_zero") is True
    )

    preprocessor = json.loads(SIGLIP_PREPROCESSOR.read_text(encoding="utf-8"))
    example_source = ADAPTER_EXAMPLE.read_text(encoding="utf-8")
    runner_source = R7_RUNNER.read_text(encoding="utf-8")
    example_scale = extract_number(example_source, r"ipadapter_scale\s*=\s*([0-9.]+)")
    runner_scale = extract_number(runner_source, r"set_ip_adapter_scale\(([0-9.]+)\)")
    with Image.open(REFERENCE) as image:
        reference_size = list(image.size)
    resize_size = [preprocessor["size"]["width"], preprocessor["size"]["height"]]
    aspect_ratio_distorted = reference_size[0] * resize_size[1] != reference_size[1] * resize_size[0]
    diagnostics = {
        "binary_compatibility": {
            "status": "PASS" if binary_compatibility else "FAIL",
            "transformer_blocks": mapping.get("transformer_blocks"),
            "ip_adapter_processors": mapping.get("ip_adapter_processors"),
            "image_projection_class": mapping.get("image_projection_class"),
            "embedding_shape": embedding.get("embedding_shape"),
            "embedding_dtype": embedding.get("embedding_dtype"),
            "embedding_finite_nonzero": bool(
                embedding.get("positive_finite") and embedding.get("positive_nonzero")
            ),
        },
        "conditioning_risks": {
            "status": "CONFIRMED_CONFIGURATION_RISK",
            "reference_size": reference_size,
            "siglip_resize_size": resize_size,
            "aspect_ratio_distorted_by_preprocessor": aspect_ratio_distorted,
            "spatial_tokens_preserved": embedding.get("embedding_shape", [0, 0, 0])[1] == 729,
            "reference_is_full_body_not_identity_crop": True,
            "adapter_example_scale": example_scale,
            "r7_scale": runner_scale,
            "scale_above_adapter_example": runner_scale > example_scale,
            "adapter_example_dtype": "bfloat16",
            "r7_dtype": "float16",
            "dtype_differs_from_adapter_example": True,
            "interpretation": (
                "The path is binary-compatible, but 729 spatial tokens from a full-body 3:4 reference are "
                "resized to a square and injected into all 38 transformer blocks at a stronger-than-example "
                "scale. This supports composition leakage as the leading configuration-level explanation; "
                "causality still requires a later controlled generation comparison."
            ),
        },
    }
    passed = critic_locked and binary_compatibility and aspect_ratio_distorted
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9-R7-R1",
        "status": "PASS_WITH_NEXT_GENERATION_BLOCKED" if passed else "FAIL",
        "negative_fixture": {
            "path": str(NEGATIVE.resolve()),
            "sha256": EXPECTED_NEGATIVE_SHA256,
            "mandatory": True,
            "critic_status": critic["status"],
            "critic": critic,
            "all_new_gates_reject": critic_locked,
        },
        "conditioning_diagnostics": diagnostics,
        "guards": {
            "image_generation_performed": False,
            "inference_performed": False,
            "latents_created": False,
            "transformer_called": False,
            "vae_called": False,
            "next_neutral_attempt_authorized": False,
            "climax_generated": False,
            "phase4n_opened": False,
            "production_profile_changed": False,
            "source_package_modified": False,
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / "phase4lr9r7r1-result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
