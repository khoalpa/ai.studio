from __future__ import annotations

import io
import re
import shutil
import subprocess
import unicodedata
from typing import Any

from .errors import ArtifactError


class ImageQualityError(ArtifactError):
    def __init__(self, message: str, assessment: dict[str, Any]) -> None:
        super().__init__(message)
        self.assessment = assessment


class LocalImageQualityAssessor:
    """Technical, OCR and optional CLIP semantic/parity assessment."""

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self._clip_model = None
        self._clip_processor = None

    def assess(
        self,
        data: bytes,
        *,
        prompt: str,
        expected_dimensions: tuple[int, int],
        reference: bytes | None = None,
        asset_type: str = "default",
        identity_references: list[bytes] | None = None,
        required_elements: list[str] | None = None,
        forbidden_elements: list[str] | None = None,
        fidelity_probes: list[dict[str, Any]] | None = None,
        identity_regions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from PIL import Image, ImageStat

        layers: list[dict[str, Any]] = []
        deferred_findings: list[dict[str, Any]] = []

        def reject(layer: str, code: str, message: str, **evidence: Any) -> None:
            failed_layer = {"layer": layer, "status": "FAIL", "checks": evidence}
            raise ImageQualityError(message, {
                "status": "ASSESSED_FAIL",
                "method": "LAYERED_TECHNICAL_OCR_CLIP_V1",
                "qa_layers": [*layers, failed_layer],
                "findings": [{"error": code, "layer": layer, **evidence}],
            })

        try:
            image = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as exc:
            reject("TECHNICAL", "IMAGE_DECODE_FAILED", f"Generated image cannot be decoded: {exc}")
        if image.size != expected_dimensions:
            reject(
                "TECHNICAL", "DIMENSIONS_MISMATCH",
                f"QA dimensions mismatch: expected {expected_dimensions}, got {image.size}",
                expected=list(expected_dimensions), actual=list(image.size),
            )
        stat = ImageStat.Stat(image.resize((256, 256)))
        mean_luma = sum(stat.mean) / 3
        variance = sum(value * value for value in stat.stddev) / 3
        thresholds = self.settings.get("thresholds_by_asset", {}).get(asset_type, {})
        if variance < float(self.settings.get("minimum_variance", 18.0)) ** 2:
            reject(
                "TECHNICAL", "LOW_VISUAL_VARIANCE",
                "Image QA rejected a blank or near-uniform image", variance=round(variance, 3),
            )
        luma_band = thresholds.get("luma_band", self.settings.get("luma_band", [20, 235]))
        if not float(luma_band[0]) <= mean_luma <= float(luma_band[1]):
            reject(
                "TECHNICAL", "LUMINANCE_OUT_OF_BAND",
                "Image QA rejected out-of-band luminance", mean_luma=round(mean_luma, 3),
                expected_band=luma_band,
            )
        layers.append({
            "layer": "TECHNICAL", "status": "PASS",
            "checks": {"dimensions": list(image.size), "variance": round(variance, 3), "mean_luma": round(mean_luma, 3)},
        })
        ocr = self._ocr(data)
        detected_text = "".join(character for character in ocr if character.isalnum())
        max_chars = int(thresholds.get("maximum_ocr_characters", self.settings.get("maximum_ocr_characters", 0)))
        if len(detected_text) > max_chars:
            reject(
                "OCR_SAFETY", "UNWANTED_TEXT", f"Image QA detected unwanted text: {ocr[:80]}",
                detected_character_count=len(detected_text), maximum=max_chars,
            )
        layers.append({
            "layer": "OCR_SAFETY", "status": "PASS",
            "checks": {"detected_character_count": len(detected_text), "maximum": max_chars},
        })
        semantic_score = self._clip_similarity(image, prompt=prompt)
        semantic_threshold = float(thresholds.get("semantic_threshold", self.settings.get("semantic_threshold", 0.2)))
        # For image-to-image work, source parity is the authoritative semantic
        # signal.  English CLIP text similarity is unreliable for long
        # Vietnamese prompts and can reject an otherwise faithful derivative.
        semantic_failed = (
            reference is None and semantic_score is not None
            and semantic_score < semantic_threshold
        )
        if semantic_failed:
            deferred_findings.append({
                "error": "SEMANTIC_MISMATCH", "layer": "SEMANTIC",
                "score": round(semantic_score, 4), "threshold": semantic_threshold,
            })
        if semantic_score is None and self.settings.get("require_semantic", True):
            reject("SEMANTIC", "ASSESSOR_UNAVAILABLE", "Semantic image assessor is required but unavailable")
        layers.append({
            "layer": "SEMANTIC", "status": "FAIL" if semantic_failed else (
                "PASS" if semantic_score is not None else "NOT_APPLICABLE"
            ),
            "checks": {"score": None if semantic_score is None else round(semantic_score, 4), "threshold": semantic_threshold},
        })
        parity_score = None
        if reference is not None:
            from PIL import Image

            reference_image = Image.open(io.BytesIO(reference)).convert("RGB")
            parity_score = self._clip_similarity(image, reference=reference_image)
            threshold = float(thresholds.get("parity_threshold", self.settings.get("parity_threshold", 0.65)))
            if parity_score is not None and parity_score < threshold:
                reject(
                    "PARITY", "PARITY_MISMATCH",
                    f"Cross-orientation parity {parity_score:.3f} is below {threshold:.3f}",
                    score=round(parity_score, 4), threshold=threshold,
                )
            if parity_score is None and self.settings.get("require_semantic", True):
                reject("PARITY", "ASSESSOR_UNAVAILABLE", "Parity assessor is required but unavailable")
            layers.append({
                "layer": "PARITY", "status": "PASS",
                "checks": {"score": round(parity_score, 4), "threshold": threshold},
            })
        identity_scores = []
        identity_region_checks = []
        if identity_regions:
            for region in identity_regions:
                box = region["box_normalized"]
                crop = image.crop((
                    round(float(box[0]) * image.width), round(float(box[1]) * image.height),
                    round(float(box[2]) * image.width), round(float(box[3]) * image.height),
                ))
                scores = []
                for identity_data in region.get("references", []):
                    identity_image = Image.open(io.BytesIO(identity_data)).convert("RGB")
                    value = self._clip_similarity(crop, reference=identity_image)
                    if value is not None:
                        scores.append(round(value, 4))
                best = max(scores) if scores else None
                if best is not None:
                    identity_scores.append(best)
                identity_region_checks.append({
                    "character_id": str(region.get("character_id", "")),
                    "box_normalized": [float(value) for value in box],
                    "reference_scores": scores,
                    "best_score": best,
                })
        else:
            for identity_data in identity_references or []:
                identity_image = Image.open(io.BytesIO(identity_data)).convert("RGB")
                value = self._clip_similarity(image, reference=identity_image)
                if value is not None:
                    identity_scores.append(round(value, 4))
        identity_threshold = float(thresholds.get("identity_threshold", self.settings.get("identity_threshold", 0.55)))
        identity_failed = bool(identity_scores and min(identity_scores) < identity_threshold)
        if identity_failed:
            deferred_findings.append({
                "error": "IDENTITY_MISMATCH", "layer": "IDENTITY",
                "minimum_score": min(identity_scores), "threshold": identity_threshold,
            })
        layers.append({
            "layer": "IDENTITY", "status": "FAIL" if identity_failed else (
                "PASS" if identity_scores else "NOT_APPLICABLE"
            ),
            "checks": {"scores": identity_scores, "threshold": identity_threshold},
        })
        fidelity_checks = self._assess_fidelity_probes(image, fidelity_probes or [])
        failed_fidelity = [item for item in fidelity_checks if item["status"] == "FAIL"]
        if failed_fidelity:
            deferred_findings.append({
                "error": "VISUAL_FIDELITY_MISMATCH", "layer": "VISUAL_FIDELITY",
                "probes": [item["probe_id"] for item in failed_fidelity],
            })
        layers.append({
            "layer": "VISUAL_FIDELITY",
            "status": "FAIL" if failed_fidelity else (
                "PASS" if fidelity_checks else "NOT_APPLICABLE"
            ),
            "checks": fidelity_checks,
        })
        structured_checks = []
        element_threshold = float(thresholds.get("element_threshold", self.settings.get("element_threshold", 0.16)))
        character_probe_index = 0
        for element in required_elements or []:
            if element.startswith("character:"):
                value = identity_scores[character_probe_index] if character_probe_index < len(identity_scores) else None
                character_probe_index += 1
                status = "PASS" if value is not None and value >= identity_threshold else "FAIL"
                structured_checks.append({
                    "element": element, "status": status, "method": "IDENTITY_REFERENCE_SIMILARITY",
                    "score": value, "threshold": identity_threshold,
                })
                continue
            if element.startswith("composition:"):
                structured_checks.append({"element": element, "status": "DECLARED", "method": "SHOT_SPEC_BINDING", "score": None})
                continue
            label = element.split(":", 1)[-1].replace("_", " ")
            value = self._clip_similarity(image, prompt=label)
            status = "PASS" if value is not None and value >= element_threshold else "FAIL"
            structured_checks.append({
                "element": element, "status": status, "method": "CLIP_ELEMENT_PROBE",
                "score": None if value is None else round(value, 4), "threshold": element_threshold,
            })
        for element in forbidden_elements or []:
            if element in {"uncontrolled_text", "watermark"}:
                status = "PASS" if not detected_text else "FAIL"
                structured_checks.append({"element": element, "status": status, "method": "OCR_ABSENCE", "score": len(detected_text)})
            else:
                structured_checks.append({"element": element, "status": "NOT_MEASURED", "method": "REQUIRES_VLM", "score": None})
        failed_required = [item for item in structured_checks if item["status"] == "FAIL"]
        unmeasured = [item for item in structured_checks if item["status"] == "NOT_MEASURED"]
        if failed_required:
            deferred_findings.append({
                "error": "REQUIRED_ELEMENT_MISSING", "layer": "COMPOSITION_ELEMENTS",
                "elements": [item["element"] for item in failed_required],
            })
        layers.append({
            "layer": "COMPOSITION_ELEMENTS",
            "status": "FAIL" if failed_required else (
                "PARTIALLY_ASSESSED" if unmeasured else "PASS"
            ),
            "checks": {"required": len(required_elements or []), "unmeasured": len(unmeasured)},
        })
        structured_visual_qa = {
            "status": "FAIL" if failed_required else (
                "PARTIALLY_ASSESSED" if unmeasured else "ASSESSED_PASS"
            ),
            "required_element_count": len(required_elements or []),
            "forbidden_element_count": len(forbidden_elements or []),
            "element_threshold": element_threshold,
            "checks": structured_checks,
        }
        if deferred_findings:
            summary = "; ".join(
                finding["error"].replace("_", " ").lower() + (
                    ": " + ", ".join(finding.get("elements", [])[:4])
                    if finding.get("elements") else ""
                )
                for finding in deferred_findings
            )
            raise ImageQualityError("Layered image QA failed: " + summary, {
                "status": "ASSESSED_FAIL",
                "method": "LAYERED_TECHNICAL_OCR_CLIP_V2",
                "qa_layers": layers,
                "findings": deferred_findings,
                "semantic_score": None if semantic_score is None else round(semantic_score, 4),
                "identity_similarity_scores": identity_scores,
                "identity_region_checks": identity_region_checks,
                "structured_visual_qa": structured_visual_qa,
            })
        return {
            "status": "ASSESSED_PASS",
            "method": "TECHNICAL_OCR_CLIP",
            "qa_layers": layers,
            "mean_luma": round(mean_luma, 3),
            "variance": round(variance, 3),
            "ocr_character_count": len(detected_text),
            "ocr_text_detected": bool(detected_text),
            "asset_type": asset_type,
            "applied_thresholds": {
                "maximum_ocr_characters": max_chars,
                "semantic_threshold": semantic_threshold,
                "parity_threshold": None if reference is None else threshold,
            },
            "identity_similarity_scores": identity_scores,
            "identity_region_checks": identity_region_checks,
            "identity_consistency_status": "ASSESSED_PASS" if identity_scores else "NOT_APPLICABLE",
            "semantic_score": None if semantic_score is None else round(semantic_score, 4),
            "parity_score": None if parity_score is None else round(parity_score, 4),
            "structured_visual_qa": structured_visual_qa,
            "visual_fidelity": {
                "status": "ASSESSED_PASS" if fidelity_checks else "NOT_APPLICABLE",
                "checks": fidelity_checks,
            },
        }

    def assess_fidelity_probes(
        self, data: bytes, *, fidelity_probes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Run contrastive probes only, including optional localized crops."""
        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("RGB")
        checks = self._assess_fidelity_probes(image, fidelity_probes)
        failed = [item for item in checks if item["status"] == "FAIL"]
        return {
            "status": "ASSESSED_FAIL" if failed else "ASSESSED_PASS",
            "method": "LOCALIZED_CLIP_CONTRASTIVE_V1",
            "checks": checks,
            "failed_probes": [item["probe_id"] for item in failed],
        }

    def _assess_fidelity_probes(self, image, probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fidelity_checks = []
        tolerance = float(self.settings.get("fidelity_contrastive_tolerance", 0.015))
        for probe in probes:
            expected_label = str(probe["expected"])
            forbidden_labels = [str(value) for value in probe.get("forbidden", [])]
            probe_image = image
            crop_box = probe.get("crop_box_pixels")
            if crop_box is None and probe.get("crop_box_normalized") is not None:
                normalized = probe["crop_box_normalized"]
                crop_box = [
                    round(float(normalized[0]) * image.width),
                    round(float(normalized[1]) * image.height),
                    round(float(normalized[2]) * image.width),
                    round(float(normalized[3]) * image.height),
                ]
            applied_crop = None
            if crop_box is not None:
                left, top, right, bottom = [int(value) for value in crop_box]
                left = max(0, min(left, image.width - 1))
                top = max(0, min(top, image.height - 1))
                right = max(left + 1, min(right, image.width))
                bottom = max(top + 1, min(bottom, image.height))
                applied_crop = [left, top, right, bottom]
                probe_image = image.crop(tuple(applied_crop))
            expected_score = self._clip_similarity(probe_image, prompt=expected_label)
            forbidden_scores = [
                self._clip_similarity(probe_image, prompt=label) for label in forbidden_labels
            ]
            measured_forbidden = [value for value in forbidden_scores if value is not None]
            best_forbidden = max(measured_forbidden) if measured_forbidden else None
            required = bool(probe.get("required", False))
            minimum_expected_score = probe.get("minimum_expected_score")
            minimum_contrast_margin = probe.get("minimum_contrast_margin")
            contrast_margin = (
                None
                if expected_score is None or best_forbidden is None
                else float(expected_score) - float(best_forbidden)
            )
            failures = []
            if expected_score is None:
                failures.append("EXPECTED_SCORE_UNAVAILABLE")
            elif minimum_expected_score is not None and expected_score < float(minimum_expected_score):
                failures.append("EXPECTED_SCORE_BELOW_MINIMUM")
            if best_forbidden is not None:
                if minimum_contrast_margin is not None:
                    if contrast_margin is None or contrast_margin < float(minimum_contrast_margin):
                        failures.append("CONTRAST_MARGIN_BELOW_MINIMUM")
                elif expected_score is not None and expected_score + tolerance < best_forbidden:
                    failures.append("FORBIDDEN_LABEL_DOMINATES")
            if required and not forbidden_labels:
                failures.append("REQUIRED_GATE_HAS_NO_FORBIDDEN_LABEL")
            status = "FAIL" if failures else "PASS"
            fidelity_checks.append({
                "probe_id": str(probe.get("probe_id", expected_label)),
                "status": status,
                "required": required,
                "scope": "LOCAL_CROP" if applied_crop else "FULL_IMAGE",
                "crop_box_pixels": applied_crop,
                "expected": expected_label,
                "expected_score": None if expected_score is None else round(expected_score, 4),
                "forbidden": forbidden_labels,
                "best_forbidden_score": None if best_forbidden is None else round(best_forbidden, 4),
                "contrast_margin": None if contrast_margin is None else round(contrast_margin, 4),
                "minimum_expected_score": minimum_expected_score,
                "minimum_contrast_margin": minimum_contrast_margin,
                "ambiguity_tolerance": tolerance,
                "failure_reasons": failures,
            })
        return fidelity_checks

    def unload(self) -> None:
        self._clip_model = None
        self._clip_processor = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def assess_character_identity(
        self, data: bytes, *, character: dict[str, Any]
    ) -> dict[str, Any]:
        """Assess visible cast semantics instead of trusting generation metadata."""
        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("RGB")
        visual = character.get("visual_identity", {})
        age = int(character.get("canonical_age_min", 0))
        expected_age = "child" if age < 13 else "teenager" if age < 18 else "adult"
        expected_presentation = str(visual.get("presentation", "ANDROGYNOUS")).casefold()
        presentation_labels = {
            "child": ["a girl", "a boy", "an androgynous child"],
            "teenager": ["a teenage girl", "a teenage boy", "an androgynous teenager"],
            "adult": ["an adult woman", "an adult man", "an androgynous adult"],
        }[expected_age]
        presentation_label = {
            "feminine": presentation_labels[0],
            "masculine": presentation_labels[1],
            "androgynous": presentation_labels[2],
        }.get(expected_presentation, presentation_labels[2])
        probes = {
            "person_count": ["one person", "multiple people", "no person"],
            "age_band": ["child", "teenager", "adult"],
            "presentation": presentation_labels,
            "framing": [
                "one centered person visible from head to toe on a plain studio background",
                "a close-up or waist-up portrait with the body cropped",
                "an environmental story scene with scenery",
            ],
        }
        scores = {
            group: {
                label: self._clip_similarity(image, prompt=label)
                for label in labels
            }
            for group, labels in probes.items()
        }
        if any(value is None for group in scores.values() for value in group.values()):
            return {
                "status": "NOT_ASSESSED", "method": "CLIP_CONTRASTIVE_CHARACTER_QA",
                "findings": [{"error": "CHARACTER_SEMANTIC_ASSESSOR_UNAVAILABLE"}],
                "checks": scores,
            }
        expected = {
            "person_count": "one person",
            "age_band": expected_age,
            "presentation": presentation_label,
            "framing": "one centered person visible from head to toe on a plain studio background",
        }
        margin = float(self.settings.get("character_contrastive_margin", 0.0))
        tolerance = float(self.settings.get("character_contrastive_tolerance", 0.03))
        findings: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        for group, group_scores in scores.items():
            if group == "presentation" and expected_presentation == "unspecified":
                checks.append({
                    "check": group, "status": "NOT_APPLICABLE",
                    "expected": "unspecified", "observed": None,
                    "expected_score": None, "best_competing_score": None,
                })
                continue
            ranked = sorted(group_scores.items(), key=lambda item: float(item[1]), reverse=True)
            observed, observed_score = ranked[0]
            expected_label = expected[group]
            expected_score = float(group_scores[expected_label])
            competitor = max(float(value) for label, value in group_scores.items() if label != expected_label)
            passed = expected_score + tolerance >= competitor + margin
            checks.append({
                "check": group, "status": "PASS" if passed else "FAIL",
                "expected": expected_label, "observed": observed,
                "expected_score": round(expected_score, 4),
                "best_competing_score": round(competitor, 4),
                "ambiguity_tolerance": tolerance,
            })
            if not passed:
                findings.append({
                    "error": f"CHARACTER_{group.upper()}_MISMATCH",
                    "expected": expected_label, "observed": observed,
                })
        attribute_threshold = float(self.settings.get("character_attribute_threshold", 0.16))
        for field in ("hair", "wardrobe", "silhouette", "cultural_context"):
            expected_value = str(visual.get(field, "")).strip()
            if not expected_value:
                continue
            score = self._clip_similarity(
                image, prompt=self._character_attribute_prompt(field, expected_value)
            )
            passed = score is not None and score >= attribute_threshold
            checks.append({
                "check": field, "status": "PASS" if passed else "FAIL",
                "expected": expected_value, "score": None if score is None else round(score, 4),
                "threshold": attribute_threshold,
            })
            if not passed:
                findings.append({
                    "error": "CHARACTER_VISUAL_ATTRIBUTE_MISMATCH",
                    "attribute": field, "expected": expected_value,
                })
        return {
            "status": "ASSESSED_PASS" if not findings else "ASSESSED_FAIL",
            "method": "CLIP_CONTRASTIVE_CHARACTER_QA",
            "character_id": character.get("character_id"),
            "checks": checks,
            "findings": findings,
        }

    @staticmethod
    def _character_attribute_prompt(field: str, value: str) -> str:
        """Give English CLIP stable visual anchors while retaining the source value."""
        translated = unicodedata.normalize("NFC", value).casefold()
        replacements = {
            "tóc đen": "black hair", "tóc nâu": "brown hair", "tóc dài": "long hair",
            "tóc ngắn": "short hair", "áo sơ mi trắng": "white shirt",
            "áo trắng": "white shirt", "áo xanh": "blue shirt", "váy": "skirt",
            "bé gái": "young girl", "bé trai": "young boy",
            "nhỏ nhắn": "small child proportions", "trung niên": "middle-aged adult",
            "việt nam": "Vietnamese contemporary cultural context",
        }
        for source, target in replacements.items():
            translated = translated.replace(source, target)
        labels = {
            "hair": "visible hairstyle",
            "wardrobe": "visible clothing",
            "silhouette": "body silhouette and age proportions",
            "cultural_context": "cultural appearance",
        }
        return f"{labels.get(field, field)}: {translated}"

    def _ocr(self, data: bytes) -> str:
        if not self.settings.get("ocr_enabled", True):
            return ""
        executable = self.settings.get("tesseract_path") or shutil.which("tesseract")
        if not executable:
            if self.settings.get("require_ocr", True):
                raise ArtifactError("Tesseract OCR is required but unavailable")
            return ""
        from PIL import Image

        image = Image.open(io.BytesIO(data)).convert("RGB")
        if max(image.size) > 1600:
            scale = 1600 / max(image.size)
            image = image.resize(
                (round(image.width * scale), round(image.height * scale)),
                Image.Resampling.LANCZOS,
            )
        from PIL import ImageFilter, ImageOps

        variants = [image]
        gray = ImageOps.autocontrast(ImageOps.grayscale(image))
        variants.append(gray.resize((gray.width * 2, gray.height * 2)).filter(ImageFilter.SHARPEN))
        variants.append(gray.point(lambda value: 255 if value > 150 else 0))
        outputs = []
        for variant in variants:
            prepared = io.BytesIO()
            variant.save(prepared, format="PNG")
            try:
                result = subprocess.run(
                    [str(executable), "stdin", "stdout", "-l", self.settings.get("ocr_language", "eng"), "--psm", "11"],
                    input=prepared.getvalue(), capture_output=True,
                    timeout=float(self.settings.get("ocr_timeout_seconds", 20)), check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise ArtifactError(f"OCR assessment failed: {exc}") from exc
            if result.returncode != 0:
                raise ArtifactError("OCR assessment returned an error")
            value = result.stdout.decode("utf-8", errors="replace").strip()
            if value:
                outputs.append(value)
        if not outputs:
            return ""
        token_sets = []
        original_by_normalized = {}
        for output in outputs:
            current = set()
            for token in re.findall(r"[A-Za-z0-9]{3,}", output):
                normalized = token.casefold()
                current.add(normalized)
                original_by_normalized.setdefault(normalized, token)
            token_sets.append(current)
        consensus = sorted(
            token for token in set().union(*token_sets)
            if sum(token in values for values in token_sets) >= 2
        )
        return " ".join(original_by_normalized[token] for token in consensus)

    def _clip_similarity(self, image, *, prompt: str | None = None, reference=None) -> float | None:
        model_id = self.settings.get("semantic_model")
        if not model_id:
            return None
        try:
            self._load_clip(model_id)
            import torch

            if reference is not None:
                inputs = self._clip_processor(images=[image, reference], return_tensors="pt")
                inputs = {key: value.to(self._clip_model.device) for key, value in inputs.items()}
                with torch.inference_mode():
                    features = self._clip_model.get_image_features(**inputs)
                # transformers versions differ here: some return the feature
                # tensor directly, while newer releases may return a model
                # output wrapper.
                features = self._feature_tensor(features)
                features = features / features.norm(dim=-1, keepdim=True)
                return float((features[0] @ features[1]).item())
            inputs = self._clip_processor(
                text=[prompt or ""],
                images=[image],
                return_tensors="pt",
                padding=True,
                truncation=True,
            )
            inputs = {key: value.to(self._clip_model.device) for key, value in inputs.items()}
            with torch.inference_mode():
                outputs = self._clip_model(**inputs)
            image_features = outputs.image_embeds / outputs.image_embeds.norm(dim=-1, keepdim=True)
            text_features = outputs.text_embeds / outputs.text_embeds.norm(dim=-1, keepdim=True)
            return float((image_features[0] @ text_features[0]).item())
        except Exception as exc:
            if self.settings.get("require_semantic", True):
                raise ArtifactError(f"Semantic assessment failed: {exc}") from exc
            return None

    @staticmethod
    def _feature_tensor(value):
        for attribute in ("image_embeds", "pooler_output", "last_hidden_state"):
            tensor = getattr(value, attribute, None)
            if tensor is not None:
                if attribute == "last_hidden_state" and tensor.ndim == 3:
                    return tensor[:, 0]
                return tensor
        if isinstance(value, (tuple, list)) and value:
            return value[0]
        return value

    def _load_clip(self, model_id: str) -> None:
        if self._clip_model is not None:
            return
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self._clip_processor = CLIPProcessor.from_pretrained(
            model_id, local_files_only=bool(self.settings.get("local_files_only", False))
        )
        self._clip_model = CLIPModel.from_pretrained(
            model_id,
            local_files_only=bool(self.settings.get("local_files_only", False)),
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        )
        self._clip_model.to("cuda" if torch.cuda.is_available() else "cpu")
