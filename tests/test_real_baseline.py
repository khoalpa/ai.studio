import json
import tempfile
import unittest
from pathlib import Path

from ai_story.model_operations import BenchmarkEvaluator
from ai_story.real_baseline import RealBaselineEvaluator, _digest


class RealBaselineTests(unittest.TestCase):
    @staticmethod
    def _signed(value):
        value["report_digest_sha256"] = None
        value["report_digest_sha256"] = _digest(value)
        return value

    def evidence(self):
        evaluator = RealBaselineEvaluator()
        plan = evaluator.plan()
        story_packages = [f"{index + 1:064x}" for index in range(plan["story_case_count"])]
        visual_packages = story_packages[: plan["visual_case_count"]]
        story_baseline = self._signed({
            "schema_version": "1.0",
            "report_kind": "BENCHMARK_BASELINE",
            "suite_id": plan["story_suite_id"],
            "canonical_complete": True,
            "corpus_digest_sha256": plan["story_corpus_digest_sha256"],
            "evidence_digests": [
                {
                    "case_id": case_id,
                    "seed": index,
                    "evidence_digest": f"{index + 100:064x}",
                    "package_digest_sha256": story_packages[index],
                }
                for index, case_id in enumerate(plan["story_case_ids"])
            ],
            "metrics": {"case_count": plan["story_case_count"], "completion_rate": 1.0},
        })
        image_baseline = self._signed({
            "schema_version": "1.0",
            "report_kind": "IMAGE_QUALITY_BASELINE",
            "suite_id": plan["image_suite_id"],
            "plan_digest_sha256": plan["visual_plan_digest_sha256"],
            "evidence": [
                {
                    "case_id": case_id,
                    "record_digest_sha256": f"{index + 200:064x}",
                    "package_digest_sha256": visual_packages[index],
                }
                for index, case_id in enumerate(plan["visual_case_ids"])
            ],
            "metrics": {"case_count": plan["visual_case_count"], "completion_rate": 1.0},
        })
        story_review = self._signed({
            "schema_version": "1.0",
            "reviewer_ids": ["reviewer-a", "reviewer-b"],
            "reviewed_package_digests": {
                case_id: story_packages[plan["story_case_ids"].index(case_id)]
                for case_id in BenchmarkEvaluator().plan()["golden_case_ids"]
            },
            "case_count": 8,
            "agreement_rate": 1.0,
            "cohen_kappa": 1.0,
            "agreement_status": "PASS",
        })
        image_review = self._signed({
            "schema_version": "1.0",
            "reviewer_ids": ["reviewer-a", "reviewer-b"],
            "reviewed_package_digests": visual_packages,
            "case_count": plan["visual_case_count"],
            "overall_score": 4.2,
            "agreement_status": "PASS",
        })
        return story_baseline, image_baseline, story_review, image_review

    def test_plan_freezes_realistic_baseline_scope(self):
        plan = RealBaselineEvaluator().plan()
        self.assertEqual(plan["story_case_count"], 27)
        self.assertEqual(plan["visual_case_count"], 8)
        self.assertEqual(plan["quality_preset"], "quality")
        self.assertRegex(plan["plan_digest_sha256"], r"^[0-9a-f]{64}$")

    def test_assemble_requires_complete_digest_bound_human_evidence(self):
        evaluator = RealBaselineEvaluator()
        report = evaluator.assemble(
            *self.evidence(),
            provider_mode="local",
            quality_preset="quality",
            run_label="baseline-2026-10-01",
        )
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["blockers"], [])
        self.assertTrue(all(check["status"] == "PASS" for check in report["checks"]))
        self.assertRegex(report["report_digest_sha256"], r"^[0-9a-f]{64}$")
        tampered = self.evidence()
        tampered[0]["metrics"]["case_count"] = 1
        with self.assertRaisesRegex(Exception, "digest is invalid"):
            evaluator.assemble(
                *tampered,
                provider_mode="local",
                quality_preset="quality",
                run_label="tampered",
            )

    def test_write_is_immutable(self):
        evaluator = RealBaselineEvaluator()
        story, image, story_review, image_review = self.evidence()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = []
            for index, value in enumerate((story, image, story_review, image_review)):
                path = root / f"source-{index}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                sources.append(path)
            output = root / "real-baseline.json"
            evaluator.write_report(
                *sources,
                output,
                provider_mode="local",
                quality_preset="quality",
                run_label="immutable",
            )
            with self.assertRaises(FileExistsError):
                evaluator.write_report(
                    *sources,
                    output,
                    provider_mode="local",
                    quality_preset="quality",
                    run_label="immutable",
                )


if __name__ == "__main__":
    unittest.main()
