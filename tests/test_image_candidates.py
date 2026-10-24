from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from ai_story.hashing import sha256_bytes
from ai_story.image_candidates import candidate_score, select_best_candidate
from ai_story.stage2.transactions import LandscapeTransactionManager


def candidate_png(value: int) -> bytes:
    image = Image.new("RGB", (3840, 2160), (value, value, value))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class CandidateProvider:
    provider_id = "candidate-provider/1.0"

    class Registry:
        config = {"image_candidate_policy": {"scene": 3}}

    registry = Registry()

    def __init__(self):
        self.attempt = 0
        self.assessments = [
            {"status": "ASSESSED_PASS", "semantic_score": 0.3},
            {"status": "ASSESSED_PASS", "semantic_score": 0.9},
            {"status": "ASSESSED_PASS", "semantic_score": 0.5},
        ]
        self.images = [candidate_png(40), candidate_png(120), candidate_png(200)]

    def generate(self, **kwargs):
        self.attempt = int(kwargs["attempt"])
        return self.images[self.attempt - 1]

    def assessment(self, basename):
        return dict(self.assessments[self.attempt - 1])


class ImageCandidateTests(unittest.TestCase):
    def test_ranker_prefers_measured_semantic_identity_and_elements(self):
        weak = {
            "status": "ASSESSED_PASS", "semantic_score": 0.3,
            "identity_similarity_scores": [0.6],
            "structured_visual_qa": {"checks": [{"status": "FAIL"}]},
        }
        strong = {
            "status": "ASSESSED_PASS", "semantic_score": 0.8,
            "identity_similarity_scores": [0.9],
            "structured_visual_qa": {"checks": [{"status": "PASS"}]},
        }
        self.assertGreater(candidate_score(strong), candidate_score(weak))
        candidates = [
            {"attempt": 1, "assessment": weak},
            {"attempt": 2, "assessment": strong},
        ]
        self.assertEqual(select_best_candidate(candidates)["attempt"], 2)
        self.assertTrue(candidates[1]["selected"])

    def test_landscape_transaction_commits_best_of_three_with_evidence(self):
        provider = CandidateProvider()
        manager = LandscapeTransactionManager(provider)
        with tempfile.TemporaryDirectory() as temporary:
            commit = manager.execute(
                basename="opening.png",
                output_root=Path(temporary),
                story={"meta": {"title": "Story"}},
                visual_plan_asset={
                    "role": "ZONE", "focal_character_ids": [],
                    "shot_spec": {"required_elements": [], "forbidden_elements": []},
                },
                visual_bible={"character_identity_locks": []},
            )
            self.assertEqual(commit.call_count, 3)
            selection = commit.quality_assessment["candidate_selection"]
            self.assertEqual(selection["requested_count"], 3)
            self.assertEqual(selection["selected_attempt"], 2)
            self.assertEqual(len(selection["candidates"]), 3)
            self.assertEqual(commit.file_sha256, sha256_bytes(provider.images[1]))

