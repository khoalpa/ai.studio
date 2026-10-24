from __future__ import annotations

import io
import json
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
from .config import stage2_config
from .cover import render_cover_typography
from .providers import LandscapeProvider


@dataclass(frozen=True)
class LandscapeCommit:
    basename: str
    transaction_id: str
    call_count: int
    path: str
    file_sha256: str
    dimensions: list[int]
    provider_id: str
    quality_assessment: dict[str, Any]
    status: str = "COMMITTED"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LandscapeCommit":
        return cls(**value)

    def plan_binding(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "file_sha256": self.file_sha256,
            "dimensions": self.dimensions,
            "transaction_id": self.transaction_id,
            "provider_id": self.provider_id,
            "quality_assessment": self.quality_assessment,
            "validation_status": "PASS",
        }


class LandscapeTransactionManager:
    def __init__(self, provider: LandscapeProvider):
        self.provider = provider

    def execute(
        self,
        *,
        basename: str,
        output_root: Path,
        story: dict[str, Any],
        visual_plan_asset: dict[str, Any],
        visual_bible: dict[str, Any],
    ) -> LandscapeCommit:
        config = stage2_config()
        limit = config["cover_max_attempts"] if basename == "cover.png" else config["max_attempts_per_basename"]
        expected = [config["landscape"]["width"], config["landscape"]["height"]]
        transaction_id = f"stage2:landscape:{basename[:-4]}"
        last_error = "unknown"
        role = str(visual_plan_asset.get("role", ""))
        asset_class = (
            "cover" if basename == "cover.png"
            else "keyframe" if role in {"CLIMAX", "ENDING"}
            else "scene"
        )
        provider_config = getattr(getattr(self.provider, "registry", None), "config", {})
        desired = candidate_count(provider_config, asset_class)
        limit = max(limit, desired)
        candidates: list[dict[str, Any]] = []
        call_count = 0
        failed_attempts: list[dict[str, Any]] = []
        for attempt in range(1, limit + 1):
            if len(candidates) >= desired:
                break
            call_count += 1
            try:
                reference_inputs = []
                for character_id in visual_plan_asset["focal_character_ids"]:
                    lock = next(
                        (
                            item
                            for item in visual_bible["character_identity_locks"]
                            if item["character_id"] == character_id
                        ),
                        None,
                    )
                    if lock:
                        path = output_root / lock["reference_image"]
                        if path.is_file():
                            source = path.read_bytes()
                            for view in lock.get("master_reference_set", {}).get("views", []):
                                if view.get("availability") == "DERIVATION_PENDING":
                                    continue
                                reference_inputs.append({
                                    "reference_id": f"{character_id}:{view['view_id']}",
                                    "character_id": character_id,
                                    "view_id": view["view_id"],
                                    "weight": 1.0 if view["view_id"] == "face_closeup" else 0.8,
                                    "data": _crop_reference(source, view["crop_box_normalized"]),
                                })
                data = self.provider.generate(
                    basename=basename,
                    story=story,
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
                    else {"status": "PASS", "method": "TECHNICAL_DIMENSIONS_HASH"}
                )
                assessment.setdefault("structured_visual_qa", {
                    "status": "NOT_ASSESSED",
                    "required_element_count": len(visual_plan_asset.get("shot_spec", {}).get("required_elements", [])),
                    "forbidden_element_count": len(visual_plan_asset.get("shot_spec", {}).get("forbidden_elements", [])),
                    "checks": [],
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
                if visual_plan_asset.get("shot_spec", {}).get("persist_candidates"):
                    _persist_candidate(
                        output_root, basename, attempt, "pass", data, assessment
                    )
                    _persist_intermediates(self.provider, output_root, basename, attempt)
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
                failed = {
                    "attempt": attempt, "failure": failure, "repair_plan": repair,
                }
                output_getter = getattr(self.provider, "attempt_output", None)
                rejected = output_getter(basename, attempt) if callable(output_getter) else None
                if rejected:
                    rejected_relative = (
                        f"candidates/{Path(basename).stem}/attempt-{attempt}-rejected.png"
                    )
                    rejected_path = output_root.parent / "logs" / rejected_relative
                    rejected_path.parent.mkdir(parents=True, exist_ok=True)
                    rejected_path.write_bytes(rejected)
                    failed["candidate_path"] = f"logs/{rejected_relative}"
                    failed["candidate_sha256"] = sha256_bytes(rejected)
                    if visual_plan_asset.get("shot_spec", {}).get("persist_candidates"):
                        _write_assessment_sidecar(rejected_path, failure)
                if visual_plan_asset.get("shot_spec", {}).get("persist_candidates"):
                    _persist_intermediates(self.provider, output_root, basename, attempt)
                failed_attempts.append(failed)
                setter = getattr(self.provider, "set_repair_plan", None)
                if callable(setter):
                    setter(basename, repair)
                if not repair["retryable"]:
                    break
        if candidates:
            selected = select_best_candidate(candidates)
            data = selected["data"]
            typography = None
            if basename == "cover.png":
                data, typography = render_cover_typography(data, str(story["meta"]["title"]))
            relative = f"landscape/{basename}"
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
            if typography is not None:
                assessment["controlled_typography"] = typography
            return LandscapeCommit(
                basename, transaction_id, call_count, relative, sha256_bytes(data),
                list(png_dimensions(data)), self.provider.provider_id, assessment,
            )
        raise ArtifactError(f"Transaction {transaction_id} exhausted its budget: {last_error}")


def _crop_reference(data: bytes, box: list[float]) -> bytes:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    left, top, right, bottom = (
        round(box[0] * image.width), round(box[1] * image.height),
        round(box[2] * image.width), round(box[3] * image.height),
    )
    cropped = image.crop((left, top, right, bottom))
    output = io.BytesIO()
    cropped.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _persist_candidate(
    output_root: Path,
    basename: str,
    attempt: int,
    disposition: str,
    data: bytes,
    assessment: dict[str, Any],
) -> None:
    target = (
        output_root.parent / "logs" / "candidates" / Path(basename).stem
        / f"attempt-{attempt}-{disposition}.png"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    _write_assessment_sidecar(target, assessment)


def _write_assessment_sidecar(image_path: Path, assessment: dict[str, Any]) -> None:
    image_path.with_suffix(".assessment.json").write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _persist_intermediates(
    provider: LandscapeProvider, output_root: Path, basename: str, attempt: int
) -> None:
    getter = getattr(provider, "intermediate_outputs", None)
    if not callable(getter):
        return
    assets = getter(basename, attempt)
    target_dir = output_root.parent / "logs" / "candidates" / Path(basename).stem
    target_dir.mkdir(parents=True, exist_ok=True)
    for label, data in assets.items():
        (target_dir / f"attempt-{attempt}-{label}.png").write_bytes(data)
