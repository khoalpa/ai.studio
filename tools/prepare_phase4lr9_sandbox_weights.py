from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import torch

LARGE_REPO = "stabilityai/stable-diffusion-3.5-large"
LARGE_REVISION = "ceddf0a7fdf2064ea28e2213e3b84e4afa170a0f"
ADAPTER_REPO = "InstantX/SD3.5-Large-IP-Adapter"
ADAPTER_REVISION = "1f5bb12aad717097f1d0ae884ec6c9394f775045"
SIGLIP_REPO = "google/siglip-so400m-patch14-384"
SIGLIP_REVISION = "9fdffc58afc957d1a03a25b10dba0329ab15c2a3"

LARGE_COMPONENT_PATTERNS = {
    "large-metadata": [
        "model_index.json",
        "scheduler/scheduler_config.json",
        "tokenizer/*",
        "tokenizer_2/*",
        "tokenizer_3/*",
        "vae/config.json",
        "transformer/config.json",
        "text_encoder/config.json",
        "text_encoder_2/config.json",
        "text_encoder_3/config.json",
    ],
    "large-vae": ["vae/config.json", "vae/diffusion_pytorch_model.safetensors"],
    "large-transformer": [
        "transformer/config.json",
        "transformer/diffusion_pytorch_model.safetensors.index.json",
        "transformer/diffusion_pytorch_model-00001-of-00002.safetensors",
        "transformer/diffusion_pytorch_model-00002-of-00002.safetensors",
    ],
    "large-text-encoders": [
        "text_encoder/config.json",
        "text_encoder/model.safetensors",
        "text_encoder_2/config.json",
        "text_encoder_2/model.safetensors",
        "text_encoder_3/config.json",
        "text_encoder_3/model.safetensors.index.json",
        "text_encoder_3/model-00001-of-00002.safetensors",
        "text_encoder_3/model-00002-of-00002.safetensors",
    ],
}


def download_adapter() -> Path:
    from huggingface_hub import hf_hub_download

    path = Path(
        hf_hub_download(
            ADAPTER_REPO,
            "ip-adapter.bin",
            revision=ADAPTER_REVISION,
            force_download=False,
        )
    )
    state = torch.load(path, map_location="cpu", weights_only=True)
    required = {"image_proj", "ip_adapter"}
    missing = required.difference(state)
    if missing:
        raise RuntimeError(f"IP-Adapter checkpoint missing keys: {sorted(missing)}")
    return path


def download_siglip() -> Path:
    from huggingface_hub import snapshot_download

    return Path(
        snapshot_download(
            SIGLIP_REPO,
            revision=SIGLIP_REVISION,
            allow_patterns=["config.json", "model.safetensors", "preprocessor_config.json"],
        )
    )


def download_large() -> Path:
    from huggingface_hub import snapshot_download

    patterns = [
        "model_index.json",
        "scheduler/*",
        "tokenizer*/*",
        "text_encoder*/config.json",
        "text_encoder*/model*.safetensors*",
        "transformer/config.json",
        "transformer/diffusion_pytorch_model*.safetensors*",
        "vae/config.json",
        "vae/diffusion_pytorch_model*.safetensors*",
    ]
    return Path(snapshot_download(LARGE_REPO, revision=LARGE_REVISION, allow_patterns=patterns))


def download_large_component(stage: str) -> Path:
    from huggingface_hub import snapshot_download

    root = Path(
        snapshot_download(
            LARGE_REPO,
            revision=LARGE_REVISION,
            allow_patterns=LARGE_COMPONENT_PATTERNS[stage],
        )
    )
    missing = [pattern for pattern in LARGE_COMPONENT_PATTERNS[stage] if "*" not in pattern and not (root / pattern).is_file()]
    if missing:
        raise RuntimeError(f"Large component {stage} missing files: {missing}")
    index_files = [
        root / pattern
        for pattern in LARGE_COMPONENT_PATTERNS[stage]
        if pattern.endswith(".safetensors.index.json")
    ]
    for index_file in index_files:
        index = json.loads(index_file.read_text(encoding="utf-8"))
        shards = sorted(set(index["weight_map"].values()))
        absent_shards = [shard for shard in shards if not (index_file.parent / shard).is_file()]
        if absent_shards:
            raise RuntimeError(f"Index {index_file} has missing shards: {absent_shards}")
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare isolated Phase 4L-R9 weights one stage at a time")
    parser.add_argument(
        "--stage",
        required=True,
        choices=("adapter", "siglip", "large", *LARGE_COMPONENT_PATTERNS),
    )
    parser.add_argument("--disable-xet", action="store_true", help="Use resumable HTTP instead of Xet transport")
    args = parser.parse_args()
    if args.disable_xet:
        os.environ["HF_HUB_DISABLE_XET"] = "1"
    action = {
        "adapter": download_adapter,
        "siglip": download_siglip,
        "large": download_large,
        **{stage: (lambda selected=stage: download_large_component(selected)) for stage in LARGE_COMPONENT_PATTERNS},
    }[args.stage]
    print(action())


if __name__ == "__main__":
    main()
