from __future__ import annotations

import copy
import hashlib
import json
import unittest

from ai_story.cli import parser
from ai_story.image_baseline import ImageBaselineEvaluator


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ImageBaselineTests(unittest.TestCase):
    def records(self):
        evaluator = ImageBaselineEvaluator()
        records = []
        for index, case_id in enumerate(evaluator.plan()["case_ids"]):
            assets = []
            for role in ("COVER", "CLIMAX", "ENDING"):
                basename = role.casefold() + ".png"
                assets.append({
                    "asset_id": f"asset-{role.casefold()}",
                    "basename": basename,
                    "role": role,
                    "shot_spec": {},
                    "images": [
                        {
                            "orientation": orientation,
                            "path": f"{orientation}/{basename}",
                            "file_sha256": f"{index + offset:064x}",
                            "dimensions": [1, 1],
                            "provider_id": "test-provider",
                            "assessment": {},
                        }
                        for offset, orientation in enumerate(("landscape", "portrait"), 1)
                    ],
                })
            record = {
                "schema_version": "1.0",
                "suite_id": evaluator.plan()["suite_id"],
                "plan_digest_sha256": evaluator.plan()["plan_digest_sha256"],
                "case_id": case_id,
                "seed": index,
                "package_digest_sha256": f"{index + 20:064x}",
                "provider_mode": "local",
                "quality_preset": "balanced",
                "providers": [],
                "configuration_digest_sha256": "c" * 64,
                "asset_count": 3,
                "image_count": 6,
                "assets": assets,
                "metrics": {
                    "completed": True,
                    "semantic_scores": [0.2 + index / 100],
                    "identity_scores": [0.7],
                    "parity_scores": [0.8],
                    "required_element_count": 2,
                    "required_element_pass_count": 1,
                    "required_element_unmeasured_count": 1,
                    "ocr_defect_count": 0,
                    "retry_count": 1,
                    "duration_seconds": 10 + index,
                    "peak_memory_bytes": 100 + index,
                    "defect_taxonomy": {"UNMEASURED_REQUIRED_ELEMENT": 1},
                },
                "record_digest_sha256": None,
            }
            record["record_digest_sha256"] = digest(record)
            records.append(record)
        return records

    def test_plan_locks_eight_visual_cases(self):
        plan = ImageBaselineEvaluator().plan()
        self.assertEqual(len(plan["case_ids"]), 8)
        self.assertEqual(plan["quality_preset"], "quality")
        self.assertRegex(plan["plan_digest_sha256"], r"^[0-9a-f]{64}$")

    def test_summary_has_distributions_and_taxonomy(self):
        report = ImageBaselineEvaluator().baseline_report(self.records())
        self.assertEqual(report["metrics"]["completion_rate"], 1.0)
        self.assertEqual(report["metrics"]["required_element_recall"], 0.5)
        self.assertIsNotNone(report["metrics"]["semantic_score"]["p10"])
        self.assertEqual(
            report["metrics"]["defect_taxonomy"]["UNMEASURED_REQUIRED_ELEMENT"], 8
        )
        self.assertRegex(report["report_digest_sha256"], r"^[0-9a-f]{64}$")

    def test_two_reviewer_template_and_kappa(self):
        evaluator = ImageBaselineEvaluator()
        review_a = evaluator.human_review_template(self.records(), "reviewer-a")
        review_b = evaluator.human_review_template(self.records(), "reviewer-b")
        for review in (review_a, review_b):
            for item in review["items"]:
                item["scores"] = {name: 4 for name in item["scores"]}
                item["blockers"] = []
        result = evaluator.evaluate_human_reviews(review_a, review_b)
        self.assertEqual(result["blocker_cohen_kappa"], 1.0)
        self.assertEqual(result["agreement_status"], "PASS")
        self.assertEqual(result["overall_score"], 4.0)

        duplicate = copy.deepcopy(review_b)
        duplicate["reviewer_id"] = "reviewer-a"
        with self.assertRaisesRegex(Exception, "independent"):
            evaluator.evaluate_human_reviews(review_a, duplicate)

    def test_cli_exposes_resumable_image_suite(self):
        args = parser().parse_args([
            "run-image-baseline-suite",
            "--source-packages", "stage1-packages",
            "--output", "image-baseline",
            "--provider-mode", "deterministic",
            "--resume",
        ])
        self.assertEqual(args.command, "run-image-baseline-suite")
        self.assertTrue(args.resume)

    def test_candidate_promotion_requires_machine_and_human_gates(self):
        evaluator = ImageBaselineEvaluator()
        baseline = evaluator.baseline_report(self.records())
        candidate = copy.deepcopy(baseline)
        metrics = candidate["metrics"]
        metrics["required_element_recall"] = 1.0
        metrics["unmeasured_required_element_count"] = 0
        metrics["ocr_defect_count"] = 0
        metrics["identity_score"]["median"] = 0.72
        metrics["parity_score"]["median"] = 0.82
        metrics["semantic_score"]["median"] = baseline["metrics"]["semantic_score"]["median"]
        metrics["defect_taxonomy"] = {}
        metrics["duration_seconds"]["total"] = baseline["metrics"]["duration_seconds"]["total"]
        metrics["peak_memory_bytes"] = baseline["metrics"]["peak_memory_bytes"]
        candidate["report_digest_sha256"] = None
        candidate["report_digest_sha256"] = digest(candidate)
        human = {
            "agreement_status": "PASS", "overall_score": 4.25,
            "report_digest_sha256": "a" * 64,
        }
        promoted = evaluator.evaluate_candidate(baseline, candidate, human)
        self.assertEqual(promoted["verdict"], "PROMOTE")
        self.assertTrue(all(item["status"] == "PASS" for item in promoted["checks"]))
        rejected = evaluator.evaluate_candidate(baseline, candidate, None)
        self.assertEqual(rejected["verdict"], "REJECT")
        self.assertEqual(
            next(item for item in rejected["checks"] if item["id"] == "HUMAN_REVIEW")["status"],
            "FAIL",
        )

    def test_cli_exposes_image_candidate_evaluation(self):
        args = parser().parse_args([
            "evaluate-image-benchmark", "--baseline", "base.json",
            "--candidate", "candidate.json", "--human-review", "human.json",
            "--output", "promotion.json",
        ])
        self.assertEqual(args.command, "evaluate-image-benchmark")
        self.assertEqual(args.output.name, "promotion.json")
