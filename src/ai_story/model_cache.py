from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import RuntimeUnavailableError
from .image_models import resolve_image_model_profile


def _image_model_targets(config: dict[str, Any]) -> dict[str, tuple[str, list[str] | None]]:
    """Return every model required by the selected local image providers."""
    runtime = config["runtimes"]["diffusers"]
    bindings = {
        name: config["adapters"][name]
        for name in config["selected"].values()
        if config["adapters"][name].get("runtime") == "diffusers"
    }
    targets: dict[str, tuple[str, list[str] | None]] = {}
    reference_required = False
    for binding in bindings.values():
        profile = resolve_image_model_profile(config, binding)
        targets[f"diffusion:{profile.profile_id}"] = (profile.model_id, None)
        reference_required = reference_required or profile.capabilities.reference_images
        if profile.capabilities.controlnet:
            for control_type, model_id in sorted(profile.controlnets.items()):
                targets[f"controlnet:{profile.profile_id}:{control_type}"] = (model_id, None)
    if reference_required:
        targets["ip_adapter"] = (
            runtime["ip_adapter"]["model"],
            ["sdxl_models/ip-adapter_sdxl.bin", "models/image_encoder/*"],
        )
    targets["semantic"] = (runtime["qa"]["semantic_model"], None)
    for name, value in sorted(runtime.get("control_preprocessors", {}).items()):
        if isinstance(value, dict) and value.get("enabled") and value.get("model"):
            targets[f"control_preprocessor:{name}"] = (value["model"], None)
    upscaler = runtime.get("upscaler", {})
    if upscaler.get("enabled"):
        targets["upscaler"] = (upscaler["model"], None)
    return targets


def cached_model_path(
    model_id: str | None, allow_patterns: list[str] | None = None
) -> str | None:
    if not model_id:
        return None
    local = Path(model_id).expanduser()
    if local.exists():
        return str(local.resolve())
    try:
        from huggingface_hub import snapshot_download

        return snapshot_download(
            repo_id=model_id,
            local_files_only=True,
            allow_patterns=allow_patterns,
        )
    except Exception:
        return None


def image_model_status(config: dict[str, Any]) -> dict[str, Any]:
    models = {}
    for name, (model_id, patterns) in _image_model_targets(config).items():
        models[name] = {
            "model_id": model_id,
            "cached_path": cached_model_path(model_id, patterns),
        }
    return {
        "status": "READY" if all(item["cached_path"] for item in models.values()) else "DOWNLOAD_REQUIRED",
        "models": models,
    }


def download_image_models(config: dict[str, Any]) -> dict[str, Any]:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeUnavailableError(
            "Image model downloads require the local-image dependencies; install them with "
            "'uv sync --dev --extra local-image'"
        ) from exc

    downloaded = {}
    for name, (model_id, patterns) in _image_model_targets(config).items():
        try:
            cached_path = snapshot_download(repo_id=model_id, allow_patterns=patterns)
        except Exception as exc:
            raise RuntimeUnavailableError(
                f"Cannot download {name} model '{model_id}': {exc}"
            ) from exc
        downloaded[name] = {"model_id": model_id, "cached_path": cached_path}
    return {"status": "READY", "models": downloaded}
