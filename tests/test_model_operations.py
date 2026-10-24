from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_story.cli import parser
from ai_story.model_operations import BenchmarkEvaluator, apply_quality_preset
from ai_story.models import Profile
from ai_story.provider_config import load_provider_config
from ai_story.stage1 import Stage1Pipeline, Stage1Request
from ai_story.stage1.config import confirm_duration
from ai_story.workspace import RunWorkspace


class ModelOperationsTests(unittest.TestCase):
    def test_reject_or_repair_is_compliant_after_either_valid_outcome(self) -> None:
        evaluator = BenchmarkEvaluator()
        self.assertTrue(evaluator._outcome_is_compliant("REJECT_OR_REPAIR", True))
        self.assertTrue(evaluator._outcome_is_compliant("REJECT_OR_REPAIR", False))
        self.assertTrue(evaluator._outcome_is_compliant("PASS", True))
        self.assertTrue(evaluator._outcome_is_compliant("REJECT", False))

    def test_required_elements_accept_semantic_adherence_without_hiding_literal_recall(self) -> None:
        evaluator = BenchmarkEvaluator()
        compliant, basis = evaluator._required_elements_are_compliant(
            ["năm người", "radio"],
            ["radio"],
            [{"gate_id": "BRIEF_ADHERENCE_GATE", "status": "PASS"}],
        )
        self.assertTrue(compliant)
        self.assertEqual(basis, "BRIEF_ADHERENCE_GATE")

    def test_full_benchmark_suite_command_supports_safe_resume(self) -> None:
        args = parser().parse_args([
            "run-benchmark-suite", "--output", "benchmark-output",
            "--provider-mode", "deterministic", "--resume",
        ])
        self.assertEqual(args.command, "run-benchmark-suite")
        self.assertEqual(args.provider_mode, "deterministic")
        self.assertTrue(args.resume)

    def test_quality_preset_changes_retry_and_image_steps_without_mutating_base(self) -> None:
        base = load_provider_config("local")
        original = base["adapters"]["local_sd35"]["parameters"]["steps"]
        quality = apply_quality_preset(base, "quality")
        self.assertEqual(quality["policy"]["retry_attempts"], 3)
        self.assertEqual(quality["adapters"]["local_sd35"]["parameters"]["steps"], 40)
        self.assertEqual(quality["image_candidate_policy"]["cover"], 4)
        self.assertEqual(quality["image_candidate_policy"]["scene"], 3)
        self.assertEqual(base["adapters"]["local_sd35"]["parameters"]["steps"], original)

    def test_benchmark_only_promotes_strict_editorial_improvement(self) -> None:
        evaluator = BenchmarkEvaluator()
        baseline = {
            "case_count": 1, "case_set_digest": "a" * 64,
            "corpus_digest_sha256": evaluator.canonical_corpus_digest(),
            "expected_outcome_accuracy": 1.0, "forbidden_outcome_rate": 0.0,
            "assessed_editorial_rate": 1.0,
            "completion_rate": 1.0, "blocker_rate": 0.1, "p0_defect_rate": 0,
            "editorial_score": 80, "consistency_score": 0.8,
            "required_element_recall": 0.9, "retries_per_asset": 0.1,
            "duration_seconds": 10, "peak_memory_bytes": 100,
        }
        promoted = evaluator.evaluate(
            {**baseline, "blocker_rate": 0.05, "editorial_score": 82, "consistency_score": 0.81}, baseline
        )
        held = evaluator.evaluate(
            {**baseline, "blocker_rate": 0.05, "editorial_score": 80, "consistency_score": 0.9}, baseline
        )
        held_for_small_gain = evaluator.evaluate(
            {**baseline, "editorial_score": 81}, baseline
        )
        held_for_latency = evaluator.evaluate(
            {**baseline, "editorial_score": 82, "duration_seconds": 12}, baseline
        )
        held_for_memory = evaluator.evaluate(
            {**baseline, "editorial_score": 82, "peak_memory_bytes": 111}, baseline
        )
        self.assertEqual(promoted["promotion_verdict"], "PROMOTE")
        self.assertEqual(held["promotion_verdict"], "HOLD")
        self.assertFalse(held_for_small_gain["checks"]["editorial_score_improved"])
        self.assertFalse(held_for_latency["checks"]["latency_within_budget"])
        self.assertFalse(held_for_memory["checks"]["peak_memory_within_budget"])
        unassessed = evaluator.evaluate(
            {**baseline, "editorial_score": None},
            {**baseline, "editorial_score": None},
        )
        self.assertEqual(unassessed["promotion_verdict"], "HOLD")
        self.assertFalse(unassessed["checks"]["editorial_score_improved"])
        wrong_corpus = evaluator.evaluate(
            {**baseline, "editorial_score": 82, "corpus_digest_sha256": "f" * 64},
            baseline,
        )
        self.assertFalse(wrong_corpus["checks"]["same_corpus"])

    def test_benchmark_plan_covers_all_profiles(self) -> None:
        plan = BenchmarkEvaluator().plan()
        profiles = {item["profile"] for item in plan["cases"]}
        self.assertEqual(profiles, {"YOUTH_SAFE", "ADULT_STANDARD", "SERIAL_DETECTIVE"})
        self.assertGreaterEqual(len(plan["cases"]), 20)
        self.assertTrue(any(item["labels"]["expected_outcome"] != "PASS" for item in plan["cases"]))
        self.assertTrue(all(isinstance(item["seed"], int) for item in plan["cases"]))
        self.assertEqual(plan["suite_id"], "canonical-story-quality-v4")
        self.assertRegex(plan["corpus_digest_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(set(plan["golden_annotations"]), set(plan["golden_case_ids"]))
        self.assertEqual(
            next(item for item in plan["cases"] if item["id"] == "youth-negative-storm-template-hijack")["labels"]["expected_outcome"],
            "PASS",
        )
        modified = json.loads(json.dumps(plan))
        modified["cases"][0]["brief"] += " Nội dung đã bị sửa."
        self.assertNotEqual(
            BenchmarkEvaluator._corpus_digest(modified), plan["corpus_digest_sha256"]
        )

    def test_human_review_agreement_uses_complete_independent_golden_set(self) -> None:
        evaluator = BenchmarkEvaluator()
        golden_ids = evaluator.plan()["golden_case_ids"]
        reviews_a = [
            {
                "case_id": case_id,
                "package_digest_sha256": f"{index + 1:064x}",
                "blocker_decision": "PASS" if index % 2 == 0 else "BLOCK",
            }
            for index, case_id in enumerate(golden_ids)
        ]
        reviews_b = json.loads(json.dumps(reviews_a))
        reviews_b[0]["blocker_decision"] = "BLOCK"
        first = {"schema_version": "1.0", "reviewer_id": "reviewer-a", "reviews": reviews_a}
        second = {"schema_version": "1.0", "reviewer_id": "reviewer-b", "reviews": reviews_b}
        report = evaluator.evaluate_human_reviews(first, second)
        self.assertEqual(report["case_count"], 8)
        self.assertEqual(report["agreement_rate"], 0.875)
        self.assertEqual(report["cohen_kappa"], 0.75)
        self.assertEqual(report["agreement_status"], "PASS")
        self.assertEqual(len(report["disagreements"]), 1)
        self.assertRegex(report["report_digest_sha256"], r"^[0-9a-f]{64}$")
        with self.assertRaisesRegex(Exception, "different reviewers"):
            evaluator.evaluate_human_reviews(first, {**second, "reviewer_id": "reviewer-a"})
        with self.assertRaisesRegex(Exception, "complete canonical golden set"):
            evaluator.evaluate_human_reviews(first, {**second, "reviews": reviews_b[:-1]})
        mismatched = json.loads(json.dumps(second))
        mismatched["reviews"][0]["package_digest_sha256"] = "f" * 64
        with self.assertRaisesRegex(Exception, "same packages"):
            evaluator.evaluate_human_reviews(first, mismatched)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "human-agreement.json"
            evaluator.write_human_review_report(first, second, output)
            with self.assertRaises(FileExistsError):
                evaluator.write_human_review_report(first, second, output)
            plan = evaluator.plan()
            canonical_records = [
                {
                    "case_id": case["id"],
                    "seed": case["seed"],
                    "corpus_digest_sha256": plan["corpus_digest_sha256"],
                    "package_digest_sha256": f"{index + 1:064x}",
                }
                for index, case in enumerate(plan["cases"])
            ]
            template_path = Path(temporary) / "reviewer-template.json"
            template = evaluator.write_human_review_template(
                canonical_records, "reviewer-c", template_path
            )
            self.assertEqual(len(template["reviews"]), 8)
            self.assertTrue(all(
                item["blocker_decision"] == "UNREVIEWED"
                for item in template["reviews"]
            ))

    def test_benchmark_summary_aggregates_operational_and_quality_metrics(self) -> None:
        records = [
            {"case_id": "case-a", "seed": 1, "evidence_digest": "a" * 64,
             "editorial_basis": "MODEL_CRITIC_CORROBORATED", "outcome_compliant": True,
             "advancement_allowed": True, "forbidden_outcome_count": 0,
             "completed": True, "blocker_count": 0, "p0_defect_count": 0,
             "editorial_score": 82, "consistency_score": 0.9, "required_elements": 2,
             "matched_required_elements": 2, "retry_count": 1, "asset_count": 10,
             "duration_seconds": 12.5, "peak_memory_bytes": 100,
             "defect_codes": ["ROLE_AGE_CONTRADICTION"]},
            {"case_id": "case-b", "seed": 1, "evidence_digest": "b" * 64,
             "editorial_basis": "MODEL_CRITIC_CORROBORATED", "outcome_compliant": True,
             "advancement_allowed": True, "forbidden_outcome_count": 0,
             "completed": True, "blocker_count": 0, "p0_defect_count": 0,
             "editorial_score": 86, "consistency_score": 1.0, "required_elements": 3,
             "matched_required_elements": 2, "retry_count": 0, "asset_count": 10,
             "duration_seconds": 10, "peak_memory_bytes": 120,
             "defect_codes": ["ROLE_AGE_CONTRADICTION", "MISSING_REQUIRED_OUTCOME"]},
        ]
        summary = BenchmarkEvaluator().summarize(records)
        self.assertEqual(summary["completion_rate"], 1.0)
        self.assertEqual(summary["editorial_score"], 84)
        self.assertEqual(summary["editorial_score_median"], 84)
        self.assertEqual(summary["editorial_score_p10"], 82.4)
        self.assertEqual(summary["editorial_score_p90"], 85.6)
        self.assertEqual(summary["duration_seconds_median"], 11.25)
        self.assertEqual(summary["duration_seconds_p10"], 10.25)
        self.assertEqual(summary["duration_seconds_p90"], 12.25)
        self.assertEqual(summary["defect_taxonomy"], {
            "MISSING_REQUIRED_OUTCOME": 1,
            "ROLE_AGE_CONTRADICTION": 2,
        })
        self.assertEqual(summary["required_element_recall"], 0.8)
        self.assertEqual(summary["peak_memory_bytes"], 120)
        self.assertEqual(summary["expected_outcome_accuracy"], 1.0)
        self.assertEqual(summary["assessed_editorial_rate"], 1.0)
        self.assertEqual(
            summary["corpus_digest_sha256"], BenchmarkEvaluator().canonical_corpus_digest()
        )
        self.assertEqual(
            summary["confidence_intervals_95"]["required_element_recall"],
            {"lower": 0.3755, "upper": 0.9638},
        )

        evaluator = BenchmarkEvaluator()
        first = evaluator.baseline_report(records, require_canonical=False)
        second = evaluator.baseline_report(list(reversed(records)), require_canonical=False)
        self.assertEqual(first, second)
        self.assertRegex(first["report_digest_sha256"], r"^[0-9a-f]{64}$")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "baseline.json"
            with self.assertRaisesRegex(Exception, "records are incomplete"):
                evaluator.write_baseline_report(records, output)
            plan = evaluator.plan()
            canonical_records = []
            for index, case in enumerate(plan["cases"], start=1):
                record = dict(records[0])
                record.update({
                    "case_id": case["id"],
                    "seed": case["seed"],
                    "evidence_digest": f"{index:064x}",
                    "corpus_digest_sha256": plan["corpus_digest_sha256"],
                })
                canonical_records.append(record)
            evaluator.write_baseline_report(canonical_records, output)
            with self.assertRaises(FileExistsError):
                evaluator.write_baseline_report(canonical_records, output)
        evaluation = evaluator.evaluate(first, first)
        self.assertTrue(evaluation["checks"]["same_case_set"])
        tampered = json.loads(json.dumps(first))
        tampered["metrics"]["editorial_score"] = 100
        with self.assertRaisesRegex(Exception, "digest is invalid"):
            evaluator.evaluate(tampered, first)

    def test_golden_boat_fixture_fulfills_zone_bound_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        fixture = json.loads((root / "fixtures" / "regression" / "torn_paper_boat.json").read_text(encoding="utf-8"))
        case = next(item for item in BenchmarkEvaluator().plan()["cases"] if item["id"] == fixture["case_id"])
        with tempfile.TemporaryDirectory() as temporary:
            workspace = RunWorkspace.create(Path(temporary), Profile.YOUTH_SAFE, "run-benchmark-negative")
            result = Stage1Pipeline().run(
                Stage1Request(
                    Profile.YOUTH_SAFE,
                    fixture["brief"],
                    confirm_duration(Profile.YOUTH_SAFE, fixture["minutes"]),
                    benchmark_case_id=case["id"],
                    generation_seed=case["seed"],
                    benchmark_corpus_digest=BenchmarkEvaluator().canonical_corpus_digest(),
                ),
                workspace,
            )
            record = BenchmarkEvaluator().record_from_package(
                case, Path(result.package.archive_path), seed=fixture["seed"]
            )
        self.assertTrue(record["advancement_allowed"])
        self.assertTrue(record["outcome_compliant"])
        self.assertEqual(record["p0_defect_count"], 0)
        self.assertEqual(record["editorial_basis"], "DETERMINISTIC_PREFLIGHT_ONLY")
        self.assertEqual(record["matched_required_elements"], record["required_elements"])
        self.assertEqual(record["forbidden_outcome_count"], 0)
        self.assertTrue(record["contract_compliant"])
        self.assertEqual(
            record["matched_contract_requirements"],
            record["contract_requirement_count"],
        )
        self.assertRegex(record["quality_decision_digest_sha256"], r"^[0-9a-f]{64}$")
        self.assertGreater(record["duration_seconds"], 0)
        self.assertIn("peak_memory_bytes", record)

    def test_benchmark_record_uses_contract_and_outline_evidence(self) -> None:
        evaluator = BenchmarkEvaluator()
        case = next(
            item for item in evaluator.plan()["cases"]
            if item["id"] == "youth-negative-storm-template-hijack"
        )
        with tempfile.TemporaryDirectory() as temporary:
            workspace = RunWorkspace.create(
                Path(temporary), Profile.YOUTH_SAFE, "run-benchmark-contract-evidence"
            )
            result = Stage1Pipeline().run(
                Stage1Request(
                    Profile.YOUTH_SAFE,
                    case["brief"],
                    confirm_duration(Profile.YOUTH_SAFE, case["minutes"]),
                    benchmark_case_id=case["id"],
                    generation_seed=case["seed"],
                    benchmark_corpus_digest=evaluator.canonical_corpus_digest(),
                ),
                workspace,
            )
            package_path = Path(result.package.archive_path)
            record = evaluator.record_from_package(
                case, package_path, seed=case["seed"]
            )
            with self.assertRaisesRegex(Exception, "seed does not match"):
                evaluator.record_from_package(case, package_path, seed=case["seed"] + 1)
            adult_case = evaluator.case("adult-memory-choice")
            with self.assertRaisesRegex(Exception, "profile does not match"):
                evaluator.record_from_package(
                    adult_case, package_path, seed=adult_case["seed"]
                )
            record_dir = Path(temporary) / "records"
            record_path = record_dir / f"{case['id']}.json"
            evaluator.write_case_record(case["id"], package_path, record_path)
            self.assertEqual(evaluator.load_records(record_dir)[0]["case_id"], case["id"])
            with self.assertRaises(FileExistsError):
                evaluator.write_case_record(case["id"], package_path, record_path)
        self.assertEqual(record["contract_requirement_count"], 4)
        self.assertEqual(record["matched_contract_requirements"], 4)
        self.assertEqual(record["outline_bound_requirements"], 4)
        self.assertTrue(record["contract_compliant"])
        self.assertTrue(record["content_accepted"])
        self.assertTrue(record["outcome_compliant"])
        self.assertIsNone(record["editorial_score"])
        self.assertGreater(record["preflight_story_quality_score"], 0)

    def test_benchmark_rejects_missing_or_duplicate_evidence(self) -> None:
        evaluator = BenchmarkEvaluator()
        base = {
            "case_id": "duplicate", "seed": 7, "evidence_digest": "a" * 64,
            "editorial_basis": "MODEL_CRITIC_CORROBORATED", "outcome_compliant": True,
            "advancement_allowed": True, "forbidden_outcome_count": 0,
            "completed": True, "blocker_count": 0,
            "p0_defect_count": 0, "editorial_score": 90, "consistency_score": 1.0,
            "required_elements": 1, "matched_required_elements": 1, "retry_count": 0,
            "asset_count": 1, "duration_seconds": 1, "peak_memory_bytes": 1,
        }
        with self.assertRaisesRegex(Exception, "duplicate case ids"):
            evaluator.summarize([base, dict(base)])
        with self.assertRaisesRegex(Exception, "missing required evidence"):
            evaluator.summarize([{key: value for key, value in base.items() if key != "evidence_digest"}])

    def test_resumed_benchmark_record_must_match_canonical_identity(self) -> None:
        evaluator = BenchmarkEvaluator()
        case = evaluator.plan()["cases"][0]
        record = {
            "case_id": case["id"], "seed": case["seed"],
            "corpus_digest_sha256": evaluator.canonical_corpus_digest(),
            "evidence_digest": "a" * 64,
            "editorial_basis": "DETERMINISTIC_PREFLIGHT_ONLY",
            "outcome_compliant": True, "advancement_allowed": False,
            "forbidden_outcome_count": 0, "completed": True,
            "blocker_count": 1, "p0_defect_count": 0,
            "editorial_score": None, "consistency_score": 1.0,
            "required_elements": 1, "matched_required_elements": 1,
            "contract_requirement_count": 1, "matched_contract_requirements": 1,
            "retry_count": 0, "asset_count": 1,
            "duration_seconds": 1, "peak_memory_bytes": 1,
        }
        evaluator.validate_canonical_record(record)
        with self.assertRaisesRegex(Exception, "seed does not match"):
            evaluator.validate_canonical_record({**record, "seed": case["seed"] + 1})
        with self.assertRaisesRegex(Exception, "corpus digest does not match"):
            evaluator.validate_canonical_record({**record, "corpus_digest_sha256": "f" * 64})

    def test_release_promotion_evidence_requires_complete_canonical_corpus(self) -> None:
        evaluator = BenchmarkEvaluator()
        baseline = {
            "case_count": 1, "case_set_digest": "a" * 64,
            "expected_outcome_accuracy": 1.0, "forbidden_outcome_rate": 0.0,
            "assessed_editorial_rate": 1.0, "completion_rate": 1.0,
            "blocker_rate": 0.0, "p0_defect_rate": 0, "editorial_score": 80,
            "consistency_score": 1.0, "required_element_recall": 1.0,
            "contract_requirement_recall": 1.0,
            "retries_per_asset": 0.0, "duration_seconds": 1, "peak_memory_bytes": 1,
        }
        evidence = evaluator.evaluate({**baseline, "editorial_score": 81}, baseline)
        failures = evaluator.validate_promotion_evidence(evidence)
        self.assertIn("case_count", failures)
        self.assertIn("case_set_digest", failures)
        self.assertIn("corpus_digest_sha256", failures)

    def test_canonical_promotion_evidence_is_digest_bound(self) -> None:
        evaluator = BenchmarkEvaluator()
        plan = evaluator.plan()
        baseline = {
            "case_count": len(plan["cases"]),
            "case_set_digest": evaluator.canonical_case_set_digest(),
            "corpus_digest_sha256": evaluator.canonical_corpus_digest(),
            "expected_outcome_accuracy": 1.0, "forbidden_outcome_rate": 0.0,
            "assessed_editorial_rate": 1.0, "completion_rate": 1.0,
            "blocker_rate": 0.0, "p0_defect_rate": 0, "editorial_score": 85,
            "consistency_score": 1.0, "required_element_recall": 1.0,
            "contract_requirement_recall": 1.0,
            "retries_per_asset": 0.0, "duration_seconds": 1, "peak_memory_bytes": 1,
        }
        evidence = evaluator.evaluate({**baseline, "editorial_score": 87}, baseline)
        self.assertEqual(evaluator.validate_promotion_evidence(evidence), [])
        evidence["candidate"]["editorial_score"] = 99
        self.assertIn(
            "evaluation_digest_sha256",
            evaluator.validate_promotion_evidence(evidence),
        )
