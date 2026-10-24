from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

from .config import project_root
from .errors import ConfigurationError
from .image_baseline import ImageBaselineEvaluator
from .model_operations import BenchmarkEvaluator


def _digest(document: dict[str, Any]) -> str:
    projected = dict(document)
    projected["report_digest_sha256"] = None
    return hashlib.sha256(
        json.dumps(
            projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a JSON object")
    return value


class RealBaselineEvaluator:
    """Bind story, visual and independent human evidence into one frozen baseline."""

    def plan(self) -> dict[str, Any]:
        plan = _read_json(project_root() / "spec" / "real_baseline.json", "real baseline plan")
        story_plan = BenchmarkEvaluator().plan()
        image_plan = ImageBaselineEvaluator().plan()
        story_cases = story_plan.get("cases", [])
        image_cases = image_plan.get("cases", [])
        story_count = len(story_cases)
        image_count = len(image_cases)
        if not int(plan["minimum_story_cases"]) <= story_count <= int(plan["maximum_story_cases"]):
            raise ConfigurationError("Real baseline story corpus must contain 24 to 30 cases")
        if not int(plan["minimum_visual_cases"]) <= image_count <= int(plan["maximum_visual_cases"]):
            raise ConfigurationError("Real baseline visual corpus must contain 8 to 10 cases")
        profiles = {str(case.get("profile")) for case in story_cases}
        if profiles != set(plan["required_profiles"]):
            raise ConfigurationError("Real baseline story corpus does not cover all profiles")
        story_ids = {str(case.get("id")) for case in story_cases}
        image_ids = {str(case.get("id")) for case in image_cases}
        if not image_ids <= story_ids:
            raise ConfigurationError("Visual baseline cases must be a subset of the story corpus")
        if any(not isinstance(case.get("seed"), int) for case in story_cases):
            raise ConfigurationError("Every real baseline story case requires a frozen seed")
        result = dict(plan)
        result.update({
            "story_case_count": story_count,
            "visual_case_count": image_count,
            "story_corpus_digest_sha256": story_plan["corpus_digest_sha256"],
            "visual_plan_digest_sha256": image_plan["plan_digest_sha256"],
            "story_case_ids": sorted(story_ids),
            "visual_case_ids": sorted(image_ids),
        })
        result["plan_digest_sha256"] = hashlib.sha256(
            json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        return result

    @staticmethod
    def _validate_digest(document: dict[str, Any], label: str) -> None:
        digest = str(document.get("report_digest_sha256", ""))
        if digest != _digest(document):
            raise ConfigurationError(f"{label} report digest is invalid")

    def assemble(
        self,
        story_baseline: dict[str, Any],
        image_baseline: dict[str, Any],
        story_review: dict[str, Any],
        image_review: dict[str, Any],
        *,
        provider_mode: str,
        quality_preset: str,
        run_label: str,
    ) -> dict[str, Any]:
        plan = self.plan()
        if provider_mode not in plan["allowed_provider_modes"]:
            raise ConfigurationError("Real baseline requires a local image provider mode")
        if quality_preset != plan["quality_preset"]:
            raise ConfigurationError("Real baseline must use the frozen quality preset")
        if not run_label.strip():
            raise ConfigurationError("Real baseline run label is required")
        documents = {
            "story_baseline": story_baseline,
            "image_baseline": image_baseline,
            "story_human_review": story_review,
            "image_human_review": image_review,
        }
        for label, document in documents.items():
            self._validate_digest(document, label)

        checks: list[dict[str, Any]] = []

        def check(identifier: str, passed: bool, evidence: Any) -> None:
            checks.append({
                "id": identifier,
                "status": "PASS" if passed else "FAIL",
                "evidence": evidence,
            })

        story_metrics = story_baseline.get("metrics", {})
        image_metrics = image_baseline.get("metrics", {})
        check(
            "STORY_CORPUS_COMPLETE",
            story_baseline.get("report_kind") == "BENCHMARK_BASELINE"
            and story_baseline.get("suite_id") == plan["story_suite_id"]
            and story_baseline.get("canonical_complete") is True
            and int(story_metrics.get("case_count", 0)) == plan["story_case_count"]
            and story_baseline.get("corpus_digest_sha256")
            == plan["story_corpus_digest_sha256"],
            {"case_count": story_metrics.get("case_count")},
        )
        check(
            "VISUAL_CORPUS_COMPLETE",
            image_baseline.get("report_kind") == "IMAGE_QUALITY_BASELINE"
            and image_baseline.get("suite_id") == plan["image_suite_id"]
            and int(image_metrics.get("case_count", 0)) == plan["visual_case_count"]
            and image_baseline.get("plan_digest_sha256")
            == plan["visual_plan_digest_sha256"],
            {"case_count": image_metrics.get("case_count")},
        )
        minimum_kappa = float(plan["human_review"]["minimum_blocker_kappa"])
        check(
            "STORY_REVIEW_AGREEMENT",
            story_review.get("agreement_status") == "PASS"
            and float(story_review.get("cohen_kappa", -1)) >= minimum_kappa
            and int(story_review.get("case_count", 0))
            == len(BenchmarkEvaluator().plan()["golden_case_ids"]),
            {
                "cohen_kappa": story_review.get("cohen_kappa"),
                "reviewer_ids": story_review.get("reviewer_ids"),
            },
        )
        minimum_image_score = float(plan["human_review"]["minimum_image_score"])
        check(
            "IMAGE_REVIEW_AGREEMENT",
            image_review.get("agreement_status") == "PASS"
            and float(image_review.get("overall_score", 0)) >= minimum_image_score
            and int(image_review.get("case_count", 0)) == plan["visual_case_count"],
            {
                "overall_score": image_review.get("overall_score"),
                "reviewer_ids": image_review.get("reviewer_ids"),
            },
        )
        story_review_digests = set(story_review.get("reviewed_package_digests", {}).values())
        story_evidence_digests = {
            item.get("package_digest_sha256")
            for item in story_baseline.get("evidence_digests", [])
            if item.get("package_digest_sha256")
        }
        check(
            "STORY_REVIEW_BOUND_TO_BASELINE",
            bool(story_review_digests)
            and story_review_digests <= story_evidence_digests,
            {"reviewed_package_count": len(story_review_digests)},
        )
        reviewed_image_packages = set(image_review.get("reviewed_package_digests", []))
        baseline_image_packages = {
            item.get("package_digest_sha256")
            for item in image_baseline.get("evidence", [])
            if item.get("package_digest_sha256")
        }
        check(
            "IMAGE_REVIEW_BOUND_TO_BASELINE",
            bool(reviewed_image_packages)
            and reviewed_image_packages == baseline_image_packages,
            {"reviewed_package_count": len(reviewed_image_packages)},
        )
        blockers = [item["id"] for item in checks if item["status"] != "PASS"]
        report = {
            "schema_version": "1.0",
            "report_kind": "REAL_PACKAGE_BASELINE",
            "suite_id": plan["suite_id"],
            "run_label": run_label.strip(),
            "status": "READY" if not blockers else "INCOMPLETE",
            "provider_mode": provider_mode,
            "quality_preset": quality_preset,
            "environment": {"python": platform.python_version(), "platform": platform.platform()},
            "plan_digest_sha256": plan["plan_digest_sha256"],
            "source_reports": {
                label: document["report_digest_sha256"] for label, document in documents.items()
            },
            "checks": checks,
            "blockers": blockers,
            "metrics": {
                "story": story_metrics,
                "image": image_metrics,
                "human_story": {
                    "agreement_rate": story_review.get("agreement_rate"),
                    "cohen_kappa": story_review.get("cohen_kappa"),
                },
                "human_image": {
                    "overall_score": image_review.get("overall_score"),
                    "agreement_status": image_review.get("agreement_status"),
                },
            },
            "report_digest_sha256": None,
        }
        report["report_digest_sha256"] = _digest(report)
        return report

    def write_report(
        self,
        story_baseline_path: Path,
        image_baseline_path: Path,
        story_review_path: Path,
        image_review_path: Path,
        output_path: Path,
        *,
        provider_mode: str,
        quality_preset: str,
        run_label: str,
    ) -> dict[str, Any]:
        report = self.assemble(
            _read_json(story_baseline_path, "story baseline"),
            _read_json(image_baseline_path, "image baseline"),
            _read_json(story_review_path, "story human review"),
            _read_json(image_review_path, "image human review"),
            provider_mode=provider_mode,
            quality_preset=quality_preset,
            run_label=run_label,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return report
