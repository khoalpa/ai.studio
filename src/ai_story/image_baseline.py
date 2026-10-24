from __future__ import annotations

import hashlib
import json
import statistics
import zipfile
from pathlib import Path
from typing import Any

from .archive import PackageVerifier
from .config import project_root
from .errors import ConfigurationError
from .model_operations import BenchmarkEvaluator


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


class ImageBaselineEvaluator:
    """Immutable Stage 3 visual baseline evidence and human-review support."""

    def plan(self) -> dict[str, Any]:
        path = project_root() / "spec" / "image_baseline.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        cases = BenchmarkEvaluator().plan()["cases"]
        by_id = {str(case["id"]): case for case in cases}
        case_ids = [str(value) for value in plan.get("case_ids", [])]
        if not 8 <= len(case_ids) <= 10 or len(case_ids) != len(set(case_ids)):
            raise ConfigurationError("Image baseline must contain 8 to 10 unique cases")
        if any(case_id not in by_id for case_id in case_ids):
            raise ConfigurationError("Image baseline refers to an unknown story case")
        if any(by_id[case_id]["labels"]["expected_outcome"] != "PASS" for case_id in case_ids):
            raise ConfigurationError("Image baseline cases must be Stage 2 eligible PASS cases")
        review = plan.get("review", {})
        if not review.get("dimensions") or not review.get("blocker_codes"):
            raise ConfigurationError("Image baseline review rubric is incomplete")
        projected = dict(plan)
        projected["cases"] = [by_id[case_id] for case_id in case_ids]
        projected["plan_digest_sha256"] = _digest(plan)
        return projected

    def case(self, case_id: str) -> dict[str, Any]:
        match = next((case for case in self.plan()["cases"] if case["id"] == case_id), None)
        if match is None:
            raise ConfigurationError(f"Unknown image baseline case: {case_id}")
        return match

    @staticmethod
    def load_records(path: Path) -> list[dict[str, Any]]:
        sources = sorted(path.glob("*.json")) if path.is_dir() else [path]
        if not sources:
            raise ConfigurationError(f"No image baseline records found: {path}")
        records = [json.loads(source.read_text(encoding="utf-8")) for source in sources]
        if any(not isinstance(record, dict) or not record.get("case_id") for record in records):
            raise ConfigurationError("Invalid image baseline record")
        return records

    def record_from_package(
        self, case_id: str, package_path: Path, *,
        stage2_package: Path | None = None, source_package: Path | None = None,
    ) -> dict[str, Any]:
        case = self.case(case_id)
        verified = PackageVerifier().verify(package_path)
        if verified.package_stage != "STAGE3":
            raise ConfigurationError("Image baseline evidence requires a Stage 3 package")
        with zipfile.ZipFile(package_path) as archive:
            manifest = json.loads(archive.read("workflow_manifest.json"))
            plan = json.loads(archive.read("visual_plan.json"))
            report = json.loads(archive.read("package_quality_report.json"))
        generation = manifest.get("generation", {})
        context = generation.get("benchmark_context", {})
        if not context and stage2_package is not None and source_package is not None:
            stage2_verified = PackageVerifier().verify(stage2_package)
            source_verified = PackageVerifier().verify(source_package)
            with zipfile.ZipFile(stage2_package) as parent_archive:
                stage2_manifest = json.loads(parent_archive.read("workflow_manifest.json"))
            if (
                manifest.get("parent_package_digest_sha256") != stage2_verified.package_digest_sha256
                or stage2_manifest.get("parent_package_digest_sha256") != source_verified.package_digest_sha256
            ):
                raise ConfigurationError("Benchmark package ancestry is not bound to the source")
            with zipfile.ZipFile(source_package) as source_archive:
                source_manifest = json.loads(source_archive.read("workflow_manifest.json"))
            context = source_manifest.get("generation", {}).get("benchmark_context", {})
        expected_seed = int(case["seed"])
        if context.get("case_id") != case_id or int(context.get("seed", -1)) != expected_seed:
            raise ConfigurationError("Stage 3 package is not bound to the requested benchmark case")
        providers = [
            item for item in generation.get("providers", [])
            if item.get("role") in {"character_image", "landscape", "portrait"}
        ]
        configuration = {
            "provider_mode": generation.get("provider_mode"),
            "quality_preset": generation.get("quality_preset"),
            "providers": providers,
        }
        assets: list[dict[str, Any]] = []
        defect_taxonomy: dict[str, int] = {}
        semantic_scores: list[float] = []
        identity_scores: list[float] = []
        parity_scores: list[float] = []
        required_total = required_passed = required_unmeasured = 0
        ocr_defects = 0
        layered_qa_failures = repair_attempts = learned_upscale_count = 0
        upscale_fallback_count = web_assist_count = 0
        image_evidence = report.get("image_evidence", {})
        ordered_evidence = {
            item.get("basename"): item for item in image_evidence.get("ordered_assets", [])
        }
        portrait_assessments = image_evidence.get("portrait_assessments", [])
        for asset_index, item in enumerate(plan.get("assets", [])):
            entries = []
            sources = [
                ("landscape", item.get("landscape_image")),
                ("portrait", item.get("portrait_image")),
            ]
            if not isinstance(sources[1][1], dict):
                evidence = ordered_evidence.get(item.get("basename"), {})
                assessment = (
                    portrait_assessments[asset_index]
                    if asset_index < len(portrait_assessments) else {}
                )
                sources[1] = ("portrait", {
                    "path": f"portrait/{item.get('basename')}",
                    "file_sha256": evidence.get("portrait_sha256"),
                    "dimensions": image_evidence.get("portrait_dimensions"),
                    "provider_id": next(
                        (provider.get("provider_id") for provider in providers if provider.get("role") == "portrait"),
                        None,
                    ),
                    "quality_assessment": assessment,
                })
            for orientation, image in sources:
                if not isinstance(image, dict):
                    continue
                assessment = image.get("quality_assessment", {})
                layered_qa_failures += sum(
                    item.get("status") in {"FAIL", "ASSESSED_FAIL"}
                    for item in assessment.get("qa_layers", []) if isinstance(item, dict)
                )
                repair_attempts += len(assessment.get("repair_history", []))
                upscale_mode = assessment.get("upscale_postprocess", {}).get("mode")
                learned_upscale_count += upscale_mode == "LATENT_X2_PLUS_RESIDUAL"
                upscale_fallback_count += upscale_mode == "LANCZOS_FALLBACK"
                web_assist_count += bool(assessment.get("assist_provenance"))
                semantic = assessment.get("semantic_score")
                parity = assessment.get("parity_score")
                identities = assessment.get("identity_similarity_scores", [])
                if isinstance(semantic, (int, float)):
                    semantic_scores.append(float(semantic))
                if isinstance(parity, (int, float)):
                    parity_scores.append(float(parity))
                identity_scores.extend(float(value) for value in identities if isinstance(value, (int, float)))
                if int(assessment.get("ocr_character_count", 0)) > 0:
                    ocr_defects += 1
                    defect_taxonomy["UNCONTROLLED_TEXT"] = defect_taxonomy.get("UNCONTROLLED_TEXT", 0) + 1
                checks = assessment.get("structured_visual_qa", {}).get("checks", [])
                for check in checks:
                    required_total += 1
                    status = check.get("status")
                    if status == "PASS":
                        required_passed += 1
                    elif status == "NOT_MEASURED":
                        required_unmeasured += 1
                        defect_taxonomy["UNMEASURED_REQUIRED_ELEMENT"] = defect_taxonomy.get("UNMEASURED_REQUIRED_ELEMENT", 0) + 1
                    elif status == "FAIL":
                        defect_taxonomy["MISSING_REQUIRED_ELEMENT"] = defect_taxonomy.get("MISSING_REQUIRED_ELEMENT", 0) + 1
                if assessment.get("status") != "ASSESSED_PASS":
                    defect_taxonomy["TECHNICAL_FAILURE"] = defect_taxonomy.get("TECHNICAL_FAILURE", 0) + 1
                entries.append({
                    "orientation": orientation,
                    "path": image.get("path"),
                    "file_sha256": image.get("file_sha256"),
                    "dimensions": image.get("dimensions"),
                    "provider_id": image.get("provider_id"),
                    "assessment": assessment,
                })
            assets.append({
                "asset_id": item.get("asset_id"),
                "basename": item.get("basename"),
                "role": item.get("role"),
                "shot_spec": item.get("shot_spec"),
                "images": entries,
            })
        image_runtime = [
            item.get("metrics", {})
            for item in generation.get("runtime_metrics_lineage", [])
            if set(item.get("roles", [])) & {"character_image", "landscape", "portrait"}
        ]
        record = {
            "schema_version": "1.0",
            "suite_id": self.plan()["suite_id"],
            "plan_digest_sha256": self.plan()["plan_digest_sha256"],
            "case_id": case_id,
            "seed": expected_seed,
            "package_digest_sha256": verified.package_digest_sha256,
            "provider_mode": generation.get("provider_mode"),
            "quality_preset": generation.get("quality_preset"),
            "providers": providers,
            "configuration_digest_sha256": _digest(configuration),
            "asset_count": len(assets),
            "image_count": sum(len(item["images"]) for item in assets),
            "assets": assets,
            "metrics": {
                "completed": True,
                "semantic_scores": semantic_scores,
                "identity_scores": identity_scores,
                "parity_scores": parity_scores,
                "required_element_count": required_total,
                "required_element_pass_count": required_passed,
                "required_element_unmeasured_count": required_unmeasured,
                "ocr_defect_count": ocr_defects,
                "retry_count": sum(int(item.get("retry_count", 0)) for item in image_runtime),
                "duration_seconds": round(sum(
                    float(item.get("wall_clock_duration_ms", item.get("duration_ms", 0.0)))
                    for item in image_runtime
                ) / 1000, 4),
                "peak_memory_bytes": generation.get("peak_memory_bytes"),
                "defect_taxonomy": dict(sorted(defect_taxonomy.items())),
                "layered_qa_failure_count": layered_qa_failures,
                "repair_attempt_count": repair_attempts,
                "learned_upscale_count": learned_upscale_count,
                "upscale_fallback_count": upscale_fallback_count,
                "web_assist_count": web_assist_count,
            },
            "record_digest_sha256": None,
        }
        record["record_digest_sha256"] = _digest(record)
        return record

    def write_record(
        self, case_id: str, package_path: Path, output_path: Path, *,
        stage2_package: Path | None = None, source_package: Path | None = None,
    ) -> dict[str, Any]:
        record = self.record_from_package(
            case_id, package_path,
            stage2_package=stage2_package, source_package=source_package,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return record

    def summarize(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        expected = set(self.plan()["case_ids"])
        actual = [str(record.get("case_id")) for record in records]
        if set(actual) != expected or len(actual) != len(set(actual)):
            raise ConfigurationError("Image baseline records must contain the complete golden set")
        for record in records:
            digest = record.get("record_digest_sha256")
            projected = dict(record)
            projected["record_digest_sha256"] = None
            if digest != _digest(projected):
                raise ConfigurationError("Image baseline record digest is invalid")
            if record.get("plan_digest_sha256") != self.plan()["plan_digest_sha256"]:
                raise ConfigurationError("Image baseline record plan digest is invalid")
        configurations = {record.get("configuration_digest_sha256") for record in records}
        if len(configurations) != 1:
            raise ConfigurationError("Image baseline records must use one frozen model configuration")
        metrics = [record["metrics"] for record in records]
        semantic = [value for metric in metrics for value in metric["semantic_scores"]]
        identity = [value for metric in metrics for value in metric["identity_scores"]]
        parity = [value for metric in metrics for value in metric["parity_scores"]]
        durations = [float(metric["duration_seconds"]) for metric in metrics]
        defect_taxonomy: dict[str, int] = {}
        for metric in metrics:
            for code, count in metric["defect_taxonomy"].items():
                defect_taxonomy[code] = defect_taxonomy.get(code, 0) + int(count)
        total_required = sum(int(metric["required_element_count"]) for metric in metrics)
        total_passed = sum(int(metric["required_element_pass_count"]) for metric in metrics)

        def distribution(values: list[float]) -> dict[str, float | None]:
            return {
                "mean": round(statistics.mean(values), 4) if values else None,
                "median": round(statistics.median(values), 4) if values else None,
                "p10": round(_percentile(values, 0.1), 4) if values else None,
                "p90": round(_percentile(values, 0.9), 4) if values else None,
            }

        return {
            "case_count": len(records),
            "asset_count": sum(int(record["asset_count"]) for record in records),
            "image_count": sum(int(record["image_count"]) for record in records),
            "completion_rate": sum(bool(metric["completed"]) for metric in metrics) / len(metrics),
            "configuration_digest_sha256": next(iter(configurations)),
            "semantic_score": distribution(semantic),
            "identity_score": distribution(identity),
            "parity_score": distribution(parity),
            "required_element_recall": round(total_passed / total_required, 4) if total_required else 1.0,
            "unmeasured_required_element_count": sum(int(metric["required_element_unmeasured_count"]) for metric in metrics),
            "ocr_defect_count": sum(int(metric["ocr_defect_count"]) for metric in metrics),
            "retries_per_image": round(
                sum(int(metric["retry_count"]) for metric in metrics)
                / max(1, sum(int(record["image_count"]) for record in records)), 4
            ),
            "duration_seconds": {
                "total": round(sum(durations), 4),
                **distribution(durations),
            },
            "peak_memory_bytes": max(int(metric["peak_memory_bytes"] or 0) for metric in metrics),
            "defect_taxonomy": dict(sorted(defect_taxonomy.items())),
            "layered_qa_failure_count": sum(int(metric.get("layered_qa_failure_count", 0)) for metric in metrics),
            "repair_attempt_count": sum(int(metric.get("repair_attempt_count", 0)) for metric in metrics),
            "learned_upscale_count": sum(int(metric.get("learned_upscale_count", 0)) for metric in metrics),
            "upscale_fallback_count": sum(int(metric.get("upscale_fallback_count", 0)) for metric in metrics),
            "web_assist_count": sum(int(metric.get("web_assist_count", 0)) for metric in metrics),
        }

    def baseline_report(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        report = {
            "schema_version": "1.0",
            "report_kind": "IMAGE_QUALITY_BASELINE",
            "suite_id": self.plan()["suite_id"],
            "plan_digest_sha256": self.plan()["plan_digest_sha256"],
            "evidence": [
                {
                    "case_id": record["case_id"],
                    "record_digest_sha256": record["record_digest_sha256"],
                    "package_digest_sha256": record.get("package_digest_sha256"),
                }
                for record in sorted(records, key=lambda item: item["case_id"])
            ],
            "metrics": self.summarize(records),
            "report_digest_sha256": None,
        }
        report["report_digest_sha256"] = _digest(report)
        return report

    def write_baseline(self, records: list[dict[str, Any]], output_path: Path) -> dict[str, Any]:
        report = self.baseline_report(records)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return report

    def evaluate_candidate(
        self,
        baseline: dict[str, Any],
        candidate: dict[str, Any],
        human_review: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for label, report in (("baseline", baseline), ("candidate", candidate)):
            if report.get("report_kind") != "IMAGE_QUALITY_BASELINE":
                raise ConfigurationError(f"Invalid {label} image benchmark report kind")
            digest = report.get("report_digest_sha256")
            projected = dict(report)
            projected["report_digest_sha256"] = None
            if digest != _digest(projected):
                raise ConfigurationError(f"Invalid {label} image benchmark digest")
            if report.get("suite_id") != self.plan()["suite_id"]:
                raise ConfigurationError(f"Invalid {label} image benchmark suite")
        limits = self.plan()["promotion"]
        base = baseline["metrics"]
        current = candidate["metrics"]
        checks: list[dict[str, Any]] = []

        def check(identifier: str, passed: bool, actual: Any, required: Any) -> None:
            checks.append({
                "id": identifier, "status": "PASS" if passed else "FAIL",
                "actual": actual, "required": required,
            })

        check("COMPLETE_GOLDEN_SET", current["completion_rate"] == 1.0, current["completion_rate"], 1.0)
        recall_floor = max(float(base["required_element_recall"]), float(limits["minimum_required_element_recall"]))
        check("REQUIRED_ELEMENT_RECALL", current["required_element_recall"] >= recall_floor, current["required_element_recall"], recall_floor)
        identity_floor = max(
            float(limits["minimum_identity_median"]),
            float(base["identity_score"]["median"] or 0) - 0.01,
        )
        check("IDENTITY_CONSISTENCY", float(current["identity_score"]["median"] or 0) >= identity_floor, current["identity_score"]["median"], identity_floor)
        parity_floor = max(
            float(limits["minimum_parity_median"]),
            float(base["parity_score"]["median"] or 0) - 0.01,
        )
        check("CROSS_ORIENTATION_PARITY", float(current["parity_score"]["median"] or 0) >= parity_floor, current["parity_score"]["median"], parity_floor)
        semantic_floor = float(base["semantic_score"]["median"] or 0) - float(limits["maximum_semantic_regression"])
        check("SEMANTIC_NON_REGRESSION", float(current["semantic_score"]["median"] or 0) >= semantic_floor, current["semantic_score"]["median"], semantic_floor)
        check("OCR_DEFECTS", int(current["ocr_defect_count"]) <= int(limits["maximum_ocr_defects"]), current["ocr_defect_count"], limits["maximum_ocr_defects"])
        check(
            "MEASURED_REQUIRED_ELEMENTS",
            int(current["unmeasured_required_element_count"]) <= int(limits["maximum_unmeasured_required_elements"]),
            current["unmeasured_required_element_count"], limits["maximum_unmeasured_required_elements"],
        )
        blocker_count = sum(
            int(current.get("defect_taxonomy", {}).get(code, 0))
            for code in ("TECHNICAL_FAILURE", "MISSING_REQUIRED_ELEMENT", "UNCONTROLLED_TEXT")
        )
        check("ZERO_VISUAL_BLOCKERS", blocker_count == 0, blocker_count, 0)
        check(
            "LAYERED_QA_FAILURES", int(current.get("layered_qa_failure_count", 0)) == 0,
            current.get("layered_qa_failure_count", 0), 0,
        )
        check(
            "NO_UPSCALE_FALLBACK", int(current.get("upscale_fallback_count", 0)) == 0,
            current.get("upscale_fallback_count", 0), 0,
        )
        base_duration = float(base["duration_seconds"]["total"] or 0)
        latency_ratio = float(current["duration_seconds"]["total"] or 0) / max(base_duration, 1e-9)
        check("LATENCY_BUDGET", latency_ratio <= float(limits["maximum_latency_ratio"]), round(latency_ratio, 4), limits["maximum_latency_ratio"])
        memory_ratio = float(current["peak_memory_bytes"] or 0) / max(float(base["peak_memory_bytes"] or 0), 1)
        check("MEMORY_BUDGET", memory_ratio <= float(limits["maximum_peak_memory_ratio"]), round(memory_ratio, 4), limits["maximum_peak_memory_ratio"])
        human_valid = bool(
            human_review
            and human_review.get("agreement_status") == "PASS"
            and float(human_review.get("overall_score", 0)) >= float(limits["minimum_human_score"])
        )
        check("HUMAN_REVIEW", human_valid, None if not human_review else {
            "agreement_status": human_review.get("agreement_status"),
            "overall_score": human_review.get("overall_score"),
        }, {"agreement_status": "PASS", "minimum_score": limits["minimum_human_score"]})
        verdict = "PROMOTE" if all(item["status"] == "PASS" for item in checks) else "REJECT"
        report = {
            "schema_version": "1.0",
            "report_kind": "IMAGE_QUALITY_PROMOTION",
            "suite_id": self.plan()["suite_id"],
            "baseline_report_digest_sha256": baseline["report_digest_sha256"],
            "candidate_report_digest_sha256": candidate["report_digest_sha256"],
            "human_review_digest_sha256": human_review.get("report_digest_sha256") if human_review else None,
            "verdict": verdict,
            "checks": checks,
            "report_digest_sha256": None,
        }
        report["report_digest_sha256"] = _digest(report)
        return report

    def write_candidate_evaluation(
        self, baseline: dict[str, Any], candidate: dict[str, Any], output_path: Path,
        human_review: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        report = self.evaluate_candidate(baseline, candidate, human_review)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return report

    def human_review_template(
        self, records: list[dict[str, Any]], reviewer_id: str
    ) -> dict[str, Any]:
        if not reviewer_id.strip():
            raise ConfigurationError("Reviewer id is required")
        self.summarize(records)
        roles = set(self.plan()["keyframe_roles"])
        items = []
        for record in sorted(records, key=lambda value: value["case_id"]):
            for asset in record["assets"]:
                if asset["role"] not in roles:
                    continue
                for image in asset["images"]:
                    items.append({
                        "case_id": record["case_id"],
                        "package_digest_sha256": record["package_digest_sha256"],
                        "asset_id": asset["asset_id"],
                        "basename": asset["basename"],
                        "role": asset["role"],
                        "orientation": image["orientation"],
                        "image_path": image["path"],
                        "image_sha256": image["file_sha256"],
                        "scores": {name: None for name in self.plan()["review"]["dimensions"]},
                        "blockers": [],
                        "notes": "",
                    })
        template = {
            "schema_version": "1.0",
            "suite_id": self.plan()["suite_id"],
            "reviewer_id": reviewer_id,
            "rubric": self.plan()["review"],
            "items": items,
            "review_digest_sha256": None,
        }
        template["review_digest_sha256"] = _digest(template)
        return template

    def write_human_review_template(
        self, records: list[dict[str, Any]], reviewer_id: str, output_path: Path
    ) -> dict[str, Any]:
        value = self.human_review_template(records, reviewer_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return value

    def evaluate_human_reviews(self, review_a: dict[str, Any], review_b: dict[str, Any]) -> dict[str, Any]:
        if review_a.get("reviewer_id") == review_b.get("reviewer_id"):
            raise ConfigurationError("Image reviews require two independent reviewer ids")
        def key(item: dict[str, Any]) -> tuple[str, str, str]:
            return (item["case_id"], item["asset_id"], item["orientation"])

        left = {key(item): item for item in review_a.get("items", [])}
        right = {key(item): item for item in review_b.get("items", [])}
        if not left or set(left) != set(right):
            raise ConfigurationError("Image review item sets differ")
        dimensions = self.plan()["review"]["dimensions"]
        pairs = []
        for item_key in sorted(left):
            a, b = left[item_key], right[item_key]
            for value in [*a["scores"].values(), *b["scores"].values()]:
                if not isinstance(value, int) or not 1 <= value <= 5:
                    raise ConfigurationError("Every human image score must be an integer from 1 to 5")
            pairs.append((bool(a["blockers"]), bool(b["blockers"])))
        observed = sum(a == b for a, b in pairs) / len(pairs)
        pa = sum(a for a, _ in pairs) / len(pairs)
        pb = sum(b for _, b in pairs) / len(pairs)
        expected = pa * pb + (1 - pa) * (1 - pb)
        kappa = 1.0 if expected == 1.0 and observed == 1.0 else (observed - expected) / (1 - expected)
        dimension_scores = {
            name: round(statistics.mean([
                item["scores"][name] for review in (left, right) for item in review.values()
            ]), 4)
            for name in dimensions
        }
        result = {
            "schema_version": "1.0",
            "suite_id": self.plan()["suite_id"],
            "reviewer_ids": [review_a["reviewer_id"], review_b["reviewer_id"]],
            "reviewed_package_digests": sorted({
                str(item.get("package_digest_sha256"))
                for review in (left, right) for item in review.values()
            }),
            "reviewed_image_digests": sorted({
                str(item.get("image_sha256"))
                for review in (left, right) for item in review.values()
            }),
            "case_count": len({item["case_id"] for item in left.values()}),
            "item_count": len(left),
            "blocker_agreement": round(observed, 4),
            "blocker_cohen_kappa": round(kappa, 4),
            "minimum_required_kappa": self.plan()["review"]["minimum_blocker_kappa"],
            "agreement_status": "PASS" if kappa >= self.plan()["review"]["minimum_blocker_kappa"] else "FAIL",
            "dimension_scores": dimension_scores,
            "overall_score": round(statistics.mean(dimension_scores.values()), 4),
            "report_digest_sha256": None,
        }
        result["report_digest_sha256"] = _digest(result)
        return result

    def write_human_review_report(
        self, review_a: dict[str, Any], review_b: dict[str, Any], output_path: Path
    ) -> dict[str, Any]:
        value = self.evaluate_human_reviews(review_a, review_b)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return value
