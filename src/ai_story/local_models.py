from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .hashing import sha256_file
from .model_cache import cached_model_path

MODEL_KINDS = {
    "text", "image", "vision", "voice", "upscaler", "preprocessor", "adapter",
    "controlnet",
}
MODEL_LIFECYCLES = {"production", "system", "experimental", "legacy"}
MODEL_ROLES = {"story", "safety", "character_image", "landscape", "portrait", "tts"}
IMAGE_MODEL_PROFILES = {"sd35_medium"}
STAGE_ROLES = {
    1: ("story", "character_image", "safety"),
    2: ("landscape",),
    3: ("portrait",),
    4: ("tts",),
}
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


class LocalModelManager:
    """Persistent, workspace-local catalog for operator-selected model assets.

    Removing a catalog item never removes its weights. This is intentional: model
    files are often shared by multiple applications and can be very expensive to
    download again.
    """

    def __init__(self, runtime_root: Path) -> None:
        self.root = runtime_root.resolve() / ".models"
        self.path = self.root / "catalog.json"

    def inventory(self) -> dict[str, Any]:
        document = self._read()
        active = document["active"]
        models = [self._inspect(item, active) for item in document["models"]]
        return {
            "models": models, "active": active, "count": len(models),
            "stage_roles": {str(stage): list(roles) for stage, roles in STAGE_ROLES.items()},
        }

    def resolve_stage_selection(
        self, stage: int, selection: dict[str, Any] | None
    ) -> dict[str, dict[str, Any]]:
        """Resolve catalog ids for one stage without changing global defaults."""
        if stage not in STAGE_ROLES:
            raise ConfigurationError(f"Unsupported stage: {stage}")
        if selection is None:
            return {}
        if not isinstance(selection, dict):
            raise ConfigurationError("model_selection must be an object")
        unexpected = sorted(set(selection) - set(STAGE_ROLES[stage]))
        if unexpected:
            raise ConfigurationError(
                f"Stage {stage} does not support model roles: {unexpected}"
            )
        document = self._read()
        resolved = {}
        for role, raw_id in selection.items():
            model_id = str(raw_id or "").strip()
            if not model_id:
                continue
            item = next((value for value in document["models"] if value["id"] == model_id), None)
            if item is None:
                raise ConfigurationError(f"Unknown model id: {model_id}")
            allowed = {
                "story": {"text"}, "safety": {"text"}, "character_image": {"image"},
                "landscape": {"image"}, "portrait": {"image"}, "tts": {"voice"},
            }
            if item["kind"] not in allowed[role]:
                raise ConfigurationError(
                    f"Model kind '{item['kind']}' cannot serve role '{role}'"
                )
            inspected = self._inspect(item, document["active"])
            if inspected["status"] != "READY":
                raise ConfigurationError(f"Selected model '{model_id}' is not ready")
            resolved[role] = dict(item)
        return resolved

    def active_model(self, role: str) -> dict[str, Any] | None:
        document = self._read()
        model_id = document.get("active", {}).get(role)
        item = next((value for value in document["models"] if value["id"] == model_id), None)
        return self._inspect(item, document["active"]) if item else None

    def register(self, value: dict[str, Any]) -> dict[str, Any]:
        model_id = str(value.get("id", "")).strip().lower()
        if not _ID_PATTERN.fullmatch(model_id):
            raise ConfigurationError(
                "Model id must use 1-80 lowercase letters, numbers, '.', '_' or '-'"
            )
        kind = str(value.get("kind", "")).strip()
        if kind not in MODEL_KINDS:
            raise ConfigurationError(f"Unsupported model kind: {kind}")
        path_value = str(value.get("path") or "").strip()
        remote_id = str(value.get("model_id") or "").strip()
        if bool(path_value) == bool(remote_id):
            raise ConfigurationError("Provide exactly one of path or model_id")
        model_profile = str(value.get("model_profile") or "").strip() or None
        if model_profile and (kind != "image" or model_profile not in IMAGE_MODEL_PROFILES):
            raise ConfigurationError(f"Unsupported image model profile: {model_profile}")

        lifecycle = str(value.get("lifecycle") or "production").strip()
        if lifecycle not in MODEL_LIFECYCLES:
            raise ConfigurationError(f"Unsupported model lifecycle: {lifecycle}")
        path = None
        size = None
        digest = None
        if path_value:
            candidate = Path(path_value).expanduser().resolve()
            if not candidate.exists():
                raise ConfigurationError(f"Model asset does not exist: {candidate}")
            path = str(candidate)
            if candidate.is_file():
                size = candidate.stat().st_size
                digest = sha256_file(candidate)

        document = self._read()
        if any(item["id"] == model_id for item in document["models"]):
            raise ConfigurationError(f"Model id already exists: {model_id}")
        item = {
            "id": model_id,
            "name": str(value.get("name") or model_id).strip(),
            "kind": kind,
            "path": path,
            "model_id": remote_id or None,
            "size_bytes": size,
            "sha256": digest,
            "quantization": str(value.get("quantization") or "").strip() or None,
            "model_profile": model_profile,
            "lifecycle": lifecycle,
            "usage": str(value.get("usage") or "").strip() or None,
            "selectable": bool(value.get("selectable", kind in {"text", "image", "voice"})),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        document["models"].append(item)
        self._write(document)
        return self._inspect(item, document["active"])

    def activate(self, model_id: str, role: str) -> dict[str, Any]:
        if role not in MODEL_ROLES:
            raise ConfigurationError(f"Unsupported model role: {role}")
        document = self._read()
        item = next((item for item in document["models"] if item["id"] == model_id), None)
        if item is None:
            raise ConfigurationError(f"Unknown model id: {model_id}")
        if not item.get("selectable", item.get("kind") in {"text", "image", "voice"}):
            raise ConfigurationError("This model component cannot be selected for a runtime role")
        allowed = {
            "story": {"text"}, "safety": {"text"}, "character_image": {"image"},
            "landscape": {"image"}, "portrait": {"image"}, "tts": {"voice"},
        }
        if item["kind"] not in allowed[role]:
            raise ConfigurationError(f"Model kind '{item['kind']}' cannot serve role '{role}'")
        inspected = self._inspect(item, document["active"])
        if inspected["status"] != "READY":
            raise ConfigurationError("Cannot activate a model whose local asset is unavailable")
        document["active"][role] = model_id
        self._write(document)
        return self._inspect(item, document["active"])

    def remove(self, model_id: str) -> dict[str, Any]:
        document = self._read()
        before = len(document["models"])
        document["models"] = [item for item in document["models"] if item["id"] != model_id]
        if len(document["models"]) == before:
            raise ConfigurationError(f"Unknown model id: {model_id}")
        document["active"] = {
            role: selected for role, selected in document["active"].items() if selected != model_id
        }
        self._write(document)
        return {"removed": model_id, "weights_deleted": False}

    def _inspect(self, item: dict[str, Any], active: dict[str, str]) -> dict[str, Any]:
        result = dict(item)
        path = Path(item["path"]) if item.get("path") else None
        if path is not None:
            result["status"] = "READY" if path.exists() else "MISSING"
        else:
            cached = cached_model_path(item.get("model_id"))
            result["cached_path"] = cached
            result["status"] = "READY" if cached else "DOWNLOAD_REQUIRED"
        result["active_roles"] = sorted(role for role, value in active.items() if value == item["id"])
        result.setdefault("lifecycle", "production")
        result.setdefault("usage", None)
        result.setdefault("selectable", result.get("kind") in {"text", "image", "voice"})
        return result

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"schema_version": "1.0", "models": [], "active": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Cannot read local model catalog: {exc}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("models"), list):
            raise ConfigurationError("Local model catalog is invalid")
        value.setdefault("active", {})
        return value

    def _write(self, value: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="catalog-", suffix=".json", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
