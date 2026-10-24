from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from ..errors import ArtifactError
from ..hashing import sha256_bytes
from ..image_candidates import candidate_count, select_best_candidate
from ..image_qa import ImageQualityError
from ..image_repair import plan_image_repair
from ..stage1.png import png_dimensions
from .config import stage3_config
from .providers import PortraitProvider


@dataclass(frozen=True)
class PortraitCommit:
    basename: str
    transaction_id: str
    call_count: int
    path: str
    file_sha256: str
    source_landscape_sha256: str
    dimensions: list[int]
    provider_id: str
    quality_assessment: dict[str, Any]
    parity_status: str = "ASSESSED_PASS"

    def evidence(self) -> dict[str, Any]:
        return {
            "basename": self.basename,
            "path": self.path,
            "file_sha256": self.file_sha256,
            "source_landscape_sha256": self.source_landscape_sha256,
            "dimensions": self.dimensions,
            "transaction_id": self.transaction_id,
            "provider_id": self.provider_id,
            "quality_assessment": self.quality_assessment,
            "parity_status": self.parity_status,
            "validation_status": "PASS",
        }


class PortraitTransactionManager:
    def __init__(self, provider: PortraitProvider):
        self.provider = provider

    def execute(
        self,
        *,
        basename: str,
        landscape_path: Path,
        output_root: Path,
        visual_plan_asset: dict[str, Any],
        visual_bible: dict[str, Any],
    ) -> PortraitCommit:
        config = stage3_config()
        limit = config["cover_max_attempts"] if basename == "cover.png" else config["max_attempts_per_basename"]
        expected = [config["portrait"]["width"], config["portrait"]["height"]]
        transaction_id = f"stage3:portrait:{basename[:-4]}"
        landscape_bytes = landscape_path.read_bytes()
        source_hash = sha256_bytes(landscape_bytes)
        last_error = "unknown"
        role = str(visual_plan_asset.get("role", ""))
        asset_class = (
            "cover" if basename == "cover.png"
            else "keyframe" if role in {"CLIMAX", "ENDING"}
            else "portrait"
        )
        provider_config = getattr(getattr(self.provider, "registry", None), "config", {})
        desired = candidate_count(provider_config, asset_class)
        limit = max(limit, desired)
        candidates: list[dict[str, Any]] = []
        reference_inputs = _character_references(
            output_root, visual_plan_asset.get("focal_character_ids", []), visual_bible
        )
        call_count = 0
        failed_attempts: list[dict[str, Any]] = []
        for attempt in range(1, limit + 1):
            if len(candidates) >= desired:
                break
            call_count += 1
            try:
                data = self.provider.generate(
                    basename=basename,
                    landscape_bytes=landscape_bytes,
                    visual_plan_asset=visual_plan_asset,
                    visual_bible=visual_bible,
                    attempt=attempt,
                    reference_inputs=reference_inputs,
                )
                dimensions = list(png_dimensions(data))
                if dimensions != expected:
                    raise ArtifactError(f"Expected dimensions {expected}, got {dimensions}")
                assessment_method = getattr(self.provider, "assessment", None)
                assessment = (
                    assessment_method(basename)
                    if callable(assessment_method)
                    else {"status": "ASSESSED_PASS", "method": "PROVIDER_BINDING_HEURISTIC"}
                )
                assessment.setdefault("structured_visual_qa", {
                    "status": "NOT_ASSESSED",
                    "required_element_count": len(visual_plan_asset.get("shot_spec", {}).get("required_elements", [])),
                    "forbidden_element_count": len(visual_plan_asset.get("shot_spec", {}).get("forbidden_elements", [])),
                    "checks": [],
                })
                assessment.setdefault("portrait_transform", {
                    "mode": "FIXTURE_DIRECT",
                    "source_region": None,
                    "subject_focal_y": None,
                    "target_focal_y": None,
                    "title_safe_area_reserved": basename == "cover.png",
                    "mask_feather_pixels": 0,
                })
                assessment.setdefault("upscale_postprocess", {
                    "schema_version": "1.0", "mode": "FIXTURE_DIRECT",
                    "model_id": None, "source_size": expected, "learned_size": None,
                    "output_size": expected, "residual_resize": False, "postprocess": None,
                })
                assessment.setdefault("qa_layers", [{
                    "layer": "FIXTURE_TECHNICAL", "status": "NOT_ASSESSED", "checks": [],
                }])
                candidates.append({
                    "attempt": attempt,
                    "seed": assessment.get("generation_seed"),
                    "data": data,
                    "generated_sha256": sha256_bytes(data),
                    "dimensions": dimensions,
                    "assessment": assessment,
                })
            except (ArtifactError, OSError) as exc:
                last_error = str(exc)
                failure = (
                    exc.assessment if isinstance(exc, ImageQualityError)
                    else {"status": "FAILED", "findings": [{
                        "error": "GENERATION_OR_TECHNICAL_FAILURE", "layer": "RUNTIME",
                        "detail": str(exc),
                    }]}
                )
                repair = plan_image_repair(failure, attempt=attempt, asset_type=asset_class)
                failed_attempts.append({
                    "attempt": attempt, "failure": failure, "repair_plan": repair,
                })
                setter = getattr(self.provider, "set_repair_plan", None)
                if callable(setter):
                    setter(basename, repair)
                if not repair["retryable"]:
                    break
        if candidates:
            selected = select_best_candidate(candidates)
            data = selected["data"]
            relative = f"portrait/{basename}"
            target = output_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if sha256_bytes(target.read_bytes()) != sha256_bytes(data):
                raise ArtifactError("Post-write hash mismatch")
            evidence = [
                {key: value for key, value in candidate.items() if key != "data"}
                for candidate in candidates
            ]
            assessment = {
                **selected["assessment"],
                "candidate_selection": {
                    "policy": "BEST_OF_N_QA_V1",
                    "requested_count": desired,
                    "successful_count": len(candidates),
                    "selected_attempt": selected["attempt"],
                    "candidates": evidence,
                },
                "repair_history": failed_attempts,
            }
            return PortraitCommit(
                basename, transaction_id, call_count, relative, sha256_bytes(data),
                source_hash, list(png_dimensions(data)), self.provider.provider_id, assessment,
            )
        raise ArtifactError(f"Transaction {transaction_id} exhausted its budget: {last_error}")


def _character_references(
    root: Path, character_ids: list[str], bible: dict[str, Any]
) -> list[dict[str, Any]]:
    locks = {item["character_id"]: item for item in bible["character_identity_locks"]}
    references = []
    for character_id in character_ids:
        lock = locks.get(character_id)
        if not lock:
            continue
        path = root / lock["reference_image"]
        if not path.is_file():
            continue
        data = path.read_bytes()
        image = Image.open(io.BytesIO(data)).convert("RGB")
        for view in lock.get("master_reference_set", {}).get("views", []):
            if view.get("availability") == "DERIVATION_PENDING":
                continue
            left, top, right, bottom = view["crop_box_normalized"]
            crop = image.crop((
                round(left * image.width), round(top * image.height),
                round(right * image.width), round(bottom * image.height),
            ))
            encoded = io.BytesIO()
            crop.save(encoded, format="PNG", optimize=True)
            references.append({
                "reference_id": f"{character_id}:{view['view_id']}",
                "character_id": character_id,
                "view_id": view["view_id"],
                "weight": 1.0 if view["view_id"] == "face_closeup" else 0.8,
                "data": encoded.getvalue(),
            })
    return references
