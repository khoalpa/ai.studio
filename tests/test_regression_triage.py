from __future__ import annotations

import unittest

from ai_story.regression_triage import build_triage, classify_record


class RegressionTriageTests(unittest.TestCase):
    def test_classifies_positive_and_negative_outcomes(self) -> None:
        self.assertEqual(
            classify_record({"expected_decision": "PASS", "outcome_compliant": False}),
            "FALSE_BLOCKER",
        )
        self.assertEqual(
            classify_record(
                {
                    "expected_decision": "REJECT",
                    "outcome_compliant": True,
                    "content_accepted": False,
                }
            ),
            "CORRECT_REJECTION_OR_REPAIR",
        )

    def test_target_set_covers_false_blocker_gates_and_adds_control(self) -> None:
        plan = {
            "suite_id": "suite",
            "cases": [
                {"id": "bad", "profile": "YOUTH_SAFE", "labels": {"scenario": "x"}},
                {"id": "control", "profile": "ADULT_STANDARD", "labels": {"scenario": "y"}},
                {"id": "negative", "profile": "YOUTH_SAFE", "labels": {"scenario": "z"}},
            ],
        }
        records = [
            {
                "case_id": "bad", "expected_decision": "PASS",
                "outcome_compliant": False, "content_accepted": False,
                "advancement_allowed": False, "blocker_count": 2,
                "failed_gate_ids": ["STORY_QUALITY_GATE", "WORD_DURATION_GATE"],
            },
            {
                "case_id": "control", "expected_decision": "PASS",
                "outcome_compliant": True, "content_accepted": True,
                "advancement_allowed": True, "blocker_count": 0, "failed_gate_ids": [],
            },
            {
                "case_id": "negative", "expected_decision": "REJECT",
                "outcome_compliant": True, "content_accepted": False,
                "advancement_allowed": False, "blocker_count": 1,
                "failed_gate_ids": ["BRIEF_POLICY_GATE"],
            },
        ]

        triage, target = build_triage(
            plan, records, {"report_digest_sha256": "abc", "metrics": {}}
        )

        selected = {item["case_id"] for item in target["cases"]}
        self.assertIn("bad", selected)
        self.assertIn("control", selected)
        self.assertIn("negative", selected)
        self.assertEqual(triage["summary"]["false_blocker_count"], 1)
        self.assertEqual(
            triage["summary"]["false_blocker_gate_counts"]["STORY_QUALITY_GATE"], 1
        )


if __name__ == "__main__":
    unittest.main()
