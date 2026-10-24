from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr9-sd35-large-ipadapter-sandbox-v1"
PROFILE = OUTPUT_ROOT / "sandbox-profile.json"
PROVIDERS = PROJECT_ROOT / "spec/providers.json"
R8_RESULT = PROJECT_ROOT / "artifacts/baselines/real-v1/image/phase4lr8-identity-capability-v1/phase4lr8-result.json"
MODEL_ROOT = Path("D:/project/ai.studio/models")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gpu_snapshot() -> dict[str, object]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.free,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()
        name, total, free, utilization = [part.strip() for part in output.split(",")]
        return {
            "available": True,
            "name": name,
            "memory_total_mib": int(total),
            "memory_free_mib": int(free),
            "utilization_percent": int(utilization),
        }
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return {"available": False}


def main() -> None:
    r8 = json.loads(R8_RESULT.read_text(encoding="utf-8"))
    if r8.get("status") != "BLOCKED_NO_COMPATIBLE_REFERENCE_BACKEND":
        raise RuntimeError("Phase 4L-R8 checkpoint is not the expected blocked state")
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    providers = json.loads(PROVIDERS.read_text(encoding="utf-8"))
    medium = providers["image_models"]["sd35_medium"]
    adapter = providers["adapters"]["local_sd35"]
    production_unchanged = (
        adapter["model_profile"] == "sd35_medium"
        and medium["capabilities"]["reference_images"] is False
        and "sd35_large_ip_adapter_sandbox" not in providers["image_models"]
    )

    incomplete = list((MODEL_ROOT / "sd3.5-large-ip-adapter").glob("*.incomplete"))
    incomplete_evidence = [
        {"path": str(path), "size_bytes": path.stat().st_size} for path in incomplete
    ]
    c_usage = shutil.disk_usage("C:/")
    d_usage = shutil.disk_usage("D:/")
    result = {
        "schema_version": "1.0",
        "phase": "4L-R9",
        "status": "BLOCKED_ADAPTER_DOWNLOAD_STALLED",
        "case_id": "youth-torn-paper-boat",
        "role": "ISOLATED_SD35_LARGE_IP_ADAPTER_PROFILE",
        "sandbox_profile": {
            "status": "PASS",
            "path": str(PROFILE.resolve()),
            "sha256": sha256(PROFILE),
            "profile_id": profile["profile_id"],
            "active": False,
        },
        "production_guard": {
            "status": "PASS" if production_unchanged else "FAIL",
            "production_profile": adapter["model_profile"],
            "medium_reference_images": medium["capabilities"]["reference_images"],
            "providers_sha256": sha256(PROVIDERS),
        },
        "resource_preflight": {
            "status": "PASS_WITH_CPU_OFFLOAD_REQUIRED",
            "disk_free_gib": {
                "C": round(c_usage.free / 1024**3, 2),
                "D": round(d_usage.free / 1024**3, 2),
            },
            "gpu": gpu_snapshot(),
        },
        "weight_stages": {
            "identity_adapter": {
                "status": "BLOCKED_DOWNLOAD_STALLED",
                "expected_bytes": 1595970439,
                "incomplete_files": incomplete_evidence,
                "schema_validation": "NOT_RUN",
            },
            "siglip_image_encoder": {"status": "NOT_STARTED"},
            "filtered_sd35_large_snapshot": {"status": "NOT_STARTED"},
        },
        "neutral_identity_smoke": {"status": "NOT_RUN", "generation_performed": False},
        "new_image_generation_performed": False,
        "climax_generation_performed": False,
        "next_climax_attempt_authorized": False,
        "phase4n_opened": False,
        "source_package_modified": False,
    }
    if not production_unchanged:
        raise RuntimeError("Production SD3.5 Medium profile changed unexpectedly")
    output = OUTPUT_ROOT / "phase4lr9-result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
