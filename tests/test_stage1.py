from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ai_story.archive import PackageVerifier
from ai_story.errors import ArtifactError, WorkflowError
from ai_story.models import Profile
from ai_story.stage1 import Stage1Pipeline, Stage1Request
from ai_story.stage1.config import confirm_duration, suggested_duration
from ai_story.stage1.decision import build_quality_decision
from ai_story.stage1.png import png_dimensions, png_visual_statistics
from ai_story.stage1.providers import (
    DeterministicCharacterImageProvider,
    DeterministicStoryProvider,
    RuleBasedSafetyProvider,
)
from ai_story.stage1.validation import WORD_PATTERN, GateResult, Stage1Validator
from ai_story.workspace import RunWorkspace


class Stage1Tests(unittest.TestCase):
    def test_rebinding_unchanged_reference_preserves_verified_assessment(self) -> None:
        pipeline = Stage1Pipeline(provider_mode="deterministic")
        image = b"same-image"
        pixel_hash = "pixel-hash"
        story = {
            "characters": [{
                "character_id": "linh",
                "canonical_age_min": 35,
                "canonical_age_max": 35,
                "identity_traits": ["kiên định"],
                "visual_identity": {
                    "presentation": "FEMININE",
                    "hair": "tóc đen",
                    "wardrobe": "áo xanh",
                    "palette": ["xanh"],
                    "silhouette": "thanh mảnh",
                    "cultural_context": "Việt Nam",
                },
                "reference_asset": {
                    "reference_image": "characters/linh.png",
                    "file_sha256": hashlib.sha256(image).hexdigest(),
                    "pixel_sha256": pixel_hash,
                    "quality_assessment": {
                        "status": "ASSESSED_PASS",
                        "method": "TECHNICAL_OCR_CLIP",
                        "findings": [],
                        "checks": [],
                    },
                },
            }],
        }

        pipeline._bind_character_references(
            story, {"characters/linh.png": image}, {"characters/linh.png": pixel_hash}
        )

        self.assertEqual(
            story["characters"][0]["reference_asset"]["quality_assessment"]["status"],
            "ASSESSED_PASS",
        )

    def test_stage1_checkpoint_is_request_bound_and_restores_images(self) -> None:
        request = Stage1Request(
            Profile.YOUTH_SAFE,
            "Một câu chuyện đủ chi tiết về tình bạn và lòng dũng cảm.",
            confirm_duration(Profile.YOUTH_SAFE, 5),
        )
        story = DeterministicStoryProvider().generate(
            request.profile, request.brief, request.duration, request.language
        )
        contract = {"schema_version": "1.0", "required_elements": []}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_path = root / "characters" / "hero.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"png")
            checkpoint_path = root / "stage1_checkpoint.json"
            digest = Stage1Pipeline._request_digest(request)
            Stage1Pipeline._write_checkpoint(
                checkpoint_path,
                digest,
                "CHARACTER_IMAGES_CREATED",
                story,
                contract,
                {"characters/hero.png": "pixel-hash"},
            )

            checkpoint = Stage1Pipeline._read_checkpoint(checkpoint_path, digest)
            images, pixels = Stage1Pipeline._load_checkpoint_images(checkpoint, root)

            self.assertEqual(images, {"characters/hero.png": b"png"})
            self.assertEqual(pixels, {"characters/hero.png": "pixel-hash"})
            with self.assertRaisesRegex(WorkflowError, "different request"):
                Stage1Pipeline._read_checkpoint(checkpoint_path, "0" * 64)

    def test_canonical_benchmark_may_exercise_thin_brief_elaboration(self) -> None:
        class ThinBriefLocalProvider(DeterministicStoryProvider):
            provider_id = "local-story-provider/test"

        pipeline = Stage1Pipeline(
            ThinBriefLocalProvider(),
            DeterministicCharacterImageProvider(),
            RuleBasedSafetyProvider(),
        )
        request = Stage1Request(
            Profile.ADULT_STANDARD,
            "Một ký ức cũ trở lại.",
            confirm_duration(Profile.ADULT_STANDARD, 24),
            benchmark_case_id="adult-memory-choice",
            generation_seed=42,
            benchmark_corpus_digest="a" * 64,
        )

        pipeline._preflight_content_scope(request)

    def test_quality_decision_separates_preflight_from_editorial_pass(self) -> None:
        gates = [
            GateResult("PROFILE_GATE", "PUBLISH_BLOCKER", "PASS", "DETERMINISTIC", {}, []),
            GateResult("PROFILE_SAFETY_GATE", "PUBLISH_BLOCKER", "PASS", "DETERMINISTIC", {}, []),
            GateResult(
                "STORY_QUALITY_GATE", "QUALITY_BLOCKER", "PASS", "WEIGHTED_EDITORIAL_RUBRIC_V2",
                {"assessment_basis": "DETERMINISTIC_PREFLIGHT_ONLY"}, [],
            ),
        ]

        decision = build_quality_decision(gates, fixture_mode=False)

        self.assertEqual(decision["technical_status"], "PASS")
        self.assertEqual(decision["safety_status"], "PASS")
        self.assertEqual(decision["editorial_status"], "NOT_ASSESSED")
        self.assertEqual(decision["release_status"], "BLOCKED")
        self.assertEqual(decision["artifact_class"], "EDITORIAL_DRAFT")
        self.assertIn("MISSING_EDITORIAL_EVIDENCE", {item["code"] for item in decision["reasons"]})

    def test_quality_blocker_stops_advancement(self) -> None:
        gates = [
            GateResult("PROFILE_GATE", "PUBLISH_BLOCKER", "PASS", "DETERMINISTIC", {}, []),
            GateResult("PROFILE_SAFETY_GATE", "PUBLISH_BLOCKER", "PASS", "DETERMINISTIC", {}, []),
            GateResult(
                "SEMANTIC_REPETITION_GATE", "QUALITY_BLOCKER", "FAIL", "DETERMINISTIC", {},
                [{"locator": "script[6].text", "error": "CROSS_ZONE_SEMANTIC_REPETITION"}],
            ),
        ]

        decision = build_quality_decision(gates, fixture_mode=False)

        self.assertEqual(decision["workflow_status"], "COMPLETED_WITH_WARNINGS")
        self.assertEqual(decision["advancement_status"], "BLOCKED")
        self.assertEqual(decision["continuation_policy"], "BLOCKED")
        self.assertEqual(decision["failed_gate_ids"], ["SEMANTIC_REPETITION_GATE"])

    def test_refinement_evidence_tracks_closed_and_open_defects(self) -> None:
        initial = [
            GateResult(
                "TEST_GATE", "QUALITY_BLOCKER", "FAIL", "TEST", {},
                [
                    {"locator": "script[1].text", "error": "FIRST_DEFECT"},
                    {"locator": "script[2].text", "error": "SECOND_DEFECT"},
                ],
            )
        ]
        final = [
            GateResult(
                "TEST_GATE", "QUALITY_BLOCKER", "FAIL", "TEST", {},
                [{"locator": "script[2].text", "error": "SECOND_DEFECT"}],
            )
        ]

        evidence = Stage1Pipeline._refinement_evidence(
            initial, final, [{"round": 1}], 1, False, "a" * 64, "b" * 64
        )

        self.assertEqual(evidence["initial_defect_count"], 2)
        self.assertEqual(evidence["closed_defect_count"], 1)
        self.assertEqual(evidence["open_defect_count"], 1)
        self.assertEqual(
            {item["status"] for item in evidence["defect_closure_records"]},
            {"CLOSED", "OPEN"},
        )
        self.assertEqual(evidence["refinement_status"], "INCOMPLETE")

    def test_refinement_is_repaired_when_round_zero_cleanup_closes_all_defects(self) -> None:
        initial = [
            GateResult(
                "TEST_GATE", "QUALITY_BLOCKER", "FAIL", "TEST", {},
                [{"locator": "script[1].text", "error": "SURFACE_DEFECT"}],
            )
        ]
        final = [
            GateResult("TEST_GATE", "QUALITY_BLOCKER", "PASS", "TEST", {}, [])
        ]

        evidence = Stage1Pipeline._refinement_evidence(
            initial,
            final,
            [{"round": 0, "phase": "PRE_REPAIR_SURFACE_CLEANUP"}],
            0,
            False,
            "a" * 64,
            "b" * 64,
        )

        self.assertEqual(evidence["refinement_round_count"], 0)
        self.assertEqual(evidence["closed_defect_count"], 1)
        self.assertEqual(evidence["open_defect_count"], 0)
        self.assertEqual(evidence["refinement_status"], "REPAIRED")

    def test_overlong_sentence_repair_splits_exact_reported_sentence(self) -> None:
        story = {
            "script": [{
                "text": (
                    '" Linh nhìn Nam với ánh mắt quyết tâm và trả lời: Linh nói: '
                    '"Chúng ta có thể bắt đầu bằng cách giáo dục mọi người về tầm '
                    'quan trọng của việc bảo vệ môi trường biển.'
                )
            }]
        }
        findings = [{
            "gate_id": "AGE_PROFILE_GATE",
            "locator": "script[0].text",
            "sentence_index": 0,
            "error": "SENTENCE_TOO_COMPLEX_FOR_AGE_PROFILE",
            "word_count": 31,
            "maximum": 28,
        }]

        repaired = Stage1Pipeline._repair_overlong_sentences(story, findings)

        self.assertIsNotNone(repaired)
        sentences = list(Stage1Validator._sentences(repaired))
        self.assertLessEqual(max(len(WORD_PATTERN.findall(text)) for _, _, text in sentences), 28)
        self.assertEqual(
            sorted(WORD_PATTERN.findall(story["script"][0]["text"])),
            sorted(WORD_PATTERN.findall(repaired["script"][0]["text"])),
        )

    def test_story_contract_blocks_storm_story_hijacked_by_drawing_template(self) -> None:
        brief = (
            "Hà, một cô bé 10 tuổi, sống ở thị trấn ven biển. Một cơn bão đang tới. "
            "Hà cùng mẹ di chuyển vật dụng giá trị, bảo vệ ngôi nhà rồi sơ tán an toàn."
        )
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE, brief, confirm_duration(Profile.YOUTH_SAFE, 5), "vi"
        )
        story["characters"][1]["canonical_age_min"] = 10
        story["characters"][1]["canonical_age_max"] = 10
        story["script"][2]["text"] = 'Mẹ nói: "Cậu cứ vẽ tiếp nhé." Hai bạn mở hộp màu.'
        story["script"][3]["text"] = "Hà luyện nét cong và pha màu cho bức tranh."
        story["script"][4]["text"] = "Hà trình bày tranh trước lớp."
        story["script"][5]["text"] = "Hai bạn ngắm tác phẩm ngoài hành lang."
        story["script"][6]["text"] = "Hà hoàn thành mục tiêu và ký tên lên tranh."

        gate = Stage1Validator._story_contract_compliance(story, brief)

        self.assertEqual(gate.status, "FAIL")
        errors = {finding["error"] for finding in gate.findings}
        self.assertIn("ROLE_AGE_CONTRADICTION", errors)
        self.assertIn("OFF_BRIEF_EVENT_CHAIN", errors)
        self.assertIn("MISSING_REQUIRED_OUTCOME", errors)
        self.assertIn("RELATIONSHIP_NARRATION_MISMATCH", errors)
        self.assertIn("UNSUPPORTED_COMPLETION_CLAIM", errors)

    def test_story_contract_accepts_complete_storm_event_chain(self) -> None:
        brief = (
            "Hà, một cô bé 10 tuổi, sống ở thị trấn ven biển. Một cơn bão đang tới. "
            "Hà cùng mẹ di chuyển vật dụng giá trị, bảo vệ ngôi nhà rồi sơ tán an toàn."
        )
        story = {
            "meta": {"language": "vi"},
            "characters": [
                {"name": "Hà", "canonical_age_min": 10, "canonical_age_max": 10},
                {"name": "Mẹ", "canonical_age_min": 35, "canonical_age_max": 35},
            ],
            "outline": {
                "opening": "Bão và gió đang tiến gần.",
                "introduction": "Mẹ đóng cửa và Hà cất giấy tờ.",
                "development": "Hà di chuyển vật dụng để bảo vệ ngôi nhà.",
                "climax": "Hai mẹ con khóa cửa rồi rời nhà.",
                "falling": "Gia đình đi theo tuyến sơ tán.",
                "ending": "Gia đình đến nơi an toàn.",
            },
            "script": [
                {"zone": "OPENING", "text": "Cơn bão cùng gió mạnh đang tiến gần thị trấn."},
                {"zone": "INTRODUCTION", "text": "Mẹ đóng cửa và hướng dẫn Hà cất giấy tờ."},
                {"zone": "DEVELOPMENT", "text": "Hà di chuyển vật dụng lên kệ cao để bảo vệ ngôi nhà."},
                {"zone": "CLIMAX", "text": "Hai mẹ con kiểm tra khóa cửa lần cuối."},
                {"zone": "FALLING", "text": "Hai mẹ con rời nhà theo tuyến sơ tán."},
                {"zone": "ENDING", "text": "Gia đình đến nơi an toàn trước khi bão đổ bộ."},
            ],
        }

        gate = Stage1Validator._story_contract_compliance(story, brief)

        self.assertEqual(gate.status, "PASS")
        self.assertEqual(gate.metrics["scenario"], "STORM_EVACUATION")
        self.assertEqual(gate.metrics["requirement_count"], 4)
        self.assertEqual(gate.metrics["unbound_outline_requirement_count"], 0)

    def test_story_contract_requires_adult_help_for_lost_bird_in_rain(self) -> None:
        brief = (
            "Hai chị em tìm cách trả một chú chim non bị lạc về tổ trước cơn mưa, "
            "và học cách nhờ người lớn giúp đỡ khi gặp nguy hiểm."
        )
        story = {
            "meta": {"language": "vi"},
            "characters": [{"name": "An", "canonical_age_min": 9, "canonical_age_max": 9}],
            "outline": {
                "opening": "Hai chị em thấy chim non bị lạc.",
                "development": "Hai em một mình trèo cây trong mưa.",
                "ending": "Chim non trở lại tổ.",
            },
            "script": [
                {"zone": "OPENING", "text": "Hai chị em tìm thấy chim non bị lạc."},
                {"zone": "DEVELOPMENT", "text": "Hai em một mình trèo cây trong mưa."},
                {"zone": "ENDING", "text": "Chim non trở lại tổ."},
            ],
        }

        gate = Stage1Validator._story_contract_compliance(story, brief)

        self.assertEqual(gate.status, "FAIL")
        errors = {finding["error"] for finding in gate.findings}
        self.assertIn("OFF_BRIEF_EVENT_CHAIN", errors)
        self.assertIn("FORBIDDEN_OUTCOME_PRESENT", errors)

    def test_story_contract_blocks_children_following_adult_up_tree(self) -> None:
        brief = (
            "Hai chị em tìm cách trả một chú chim non bị lạc về tổ trước cơn mưa, "
            "và học cách nhờ người lớn giúp đỡ khi gặp nguy hiểm."
        )
        story = {
            "meta": {"language": "vi"},
            "characters": [
                {"name": "Phương", "canonical_age_min": 9, "canonical_age_max": 9},
                {"name": "An", "canonical_age_min": 8, "canonical_age_max": 8},
                {"name": "Mẹ", "canonical_age_min": 35, "canonical_age_max": 35},
            ],
            "outline": {
                "opening": "Chim non bị lạc.", "development": "Hai em nhờ mẹ.",
                "climax": "Mẹ đặt chim vào tổ.", "ending": "Chim đã về tổ.",
            },
            "script": [
                {"zone": "OPENING", "text": "Hai chị em thấy chim non bị lạc."},
                {"zone": "DEVELOPMENT", "text": "Phương và An nhờ mẹ giúp đỡ."},
                {"zone": "CLIMAX", "text": "Mẹ trèo lên cây, Phương và An theo sau."},
                {"zone": "ENDING", "text": "Mẹ đặt chim non về tổ."},
            ],
        }
        gate = Stage1Validator._story_contract_compliance(story, brief)
        self.assertTrue(any(
            item.get("outcome_id") == "child_climbs_in_rain" for item in gate.findings
        ))

    def test_story_contract_blocks_adult_lifting_children_up_tree(self) -> None:
        brief = (
            "Hai chị em tìm cách trả một chú chim non bị lạc về tổ trước cơn mưa, "
            "và học cách nhờ người lớn giúp đỡ khi gặp nguy hiểm."
        )
        story = {
            "meta": {"language": "vi"},
            "characters": [
                {"name": "Phương", "canonical_age_min": 9, "canonical_age_max": 9},
                {"name": "An", "canonical_age_min": 8, "canonical_age_max": 8},
                {"name": "Mẹ", "canonical_age_min": 35, "canonical_age_max": 35},
            ],
            "outline": {},
            "script": [
                {"zone": "OPENING", "text": "Hai chị em thấy chim non bị lạc."},
                {"zone": "DEVELOPMENT", "text": "Phương và An nhờ mẹ giúp đỡ."},
                {"zone": "CLIMAX", "text": "Mẹ đỡ Phương và An lên cây."},
                {"zone": "ENDING", "text": "Mẹ đặt chim non về tổ."},
            ],
        }
        gate = Stage1Validator._story_contract_compliance(story, brief)
        self.assertTrue(any(
            item.get("outcome_id") == "child_climbs_in_rain" for item in gate.findings
        ))

    def test_deterministic_generator_fulfills_lost_bird_contract(self) -> None:
        brief = (
            "Hai chị em tìm cách trả một chú chim non bị lạc về tổ trước cơn mưa, "
            "và học cách nhờ người lớn giúp đỡ khi gặp nguy hiểm."
        )
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE, brief, confirm_duration(Profile.YOUTH_SAFE, 5), "vi"
        )
        gate = Stage1Validator._story_contract_compliance(story, brief)
        self.assertEqual(gate.status, "PASS", gate.findings)
        self.assertTrue(all(gate.metrics["requirement_evidence"].values()))
        self.assertEqual(gate.metrics["unbound_outline_requirement_count"], 0)

    def test_torn_boat_contract_requires_events_outside_copied_opening(self) -> None:
        brief = (
            "Mưa làm chiếc thuyền của Bo bị rách. Bo từ chối thuyền thay thế, "
            "xin mẹ ôm và giữ chiếc thuyền còn vết rách. Thuyền không lành lại."
        )
        story = {
            "meta": {"language": "vi"},
            "characters": [
                {"name": "Bo", "canonical_age_min": 10, "canonical_age_max": 10},
                {"name": "Mẹ", "canonical_age_min": 35, "canonical_age_max": 35},
            ],
            "outline": {zone: "Bo nhớ lại đề bài." for zone in (
                "greeting", "opening", "introduction", "development",
                "climax", "falling", "ending", "farewell",
            )},
            "script": [
                {"zone": "OPENING", "text": brief},
                {"zone": "INTRODUCTION", "text": "Bo ngồi trong phòng."},
                {"zone": "DEVELOPMENT", "text": "Bo làm một việc khác."},
                {"zone": "CLIMAX", "text": "Bo hoàn thành việc ấy."},
                {"zone": "FALLING", "text": "Bo nhìn ra cửa sổ."},
                {"zone": "ENDING", "text": "Bo đi ngủ."},
            ],
        }
        gate = Stage1Validator._story_contract_compliance(story, brief)
        self.assertEqual(gate.metrics["requirement_count"], 4)
        self.assertEqual(gate.status, "FAIL")
        errors = {item["error"] for item in gate.findings}
        self.assertIn("OFF_BRIEF_EVENT_CHAIN", errors)
        self.assertIn("MISSING_REQUIRED_OUTCOME", errors)

    def test_youth_metadata_and_parent_dialogue_use_canonical_age_profile(self) -> None:
        brief = "Lan, một cô bé 10 tuổi, cùng mẹ chuẩn bị bài thuyết trình ở nhà."
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE, brief, confirm_duration(Profile.YOUTH_SAFE, 5), "vi"
        )

        self.assertEqual(story["meta"]["target"], "7–10 tuổi")
        self.assertEqual(story["meta"]["audience"], "trẻ em 7–10 tuổi")
        script = " ".join(item["text"] for item in story["script"])
        self.assertNotIn("Hai bạn", script)
        self.assertNotRegex(script, r'"(?:Cậu|Tớ) ')
        self.assertIn("Hai mẹ con", script)
        self.assertEqual(
            Stage1Validator._age_profile(story, Profile.YOUTH_SAFE).status,
            "PASS",
        )

    def test_age_profile_blocks_mismatched_youth_metadata(self) -> None:
        story = {
            "meta": {"target": "3–18 tuổi", "audience": "trẻ em và thiếu niên"},
            "script": [{"zone": "OPENING", "text": "Lan bắt đầu một việc nhỏ."}],
        }

        gate = Stage1Validator._age_profile(story, Profile.YOUTH_SAFE)

        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(
            {finding["locator"] for finding in gate.findings},
            {"meta.target", "meta.audience"},
        )

    def test_deterministic_generator_preserves_thin_brief_and_parent_pronouns(self) -> None:
        provider = DeterministicStoryProvider()
        duration = confirm_duration(Profile.YOUTH_SAFE, 5)
        thin = provider.generate(Profile.YOUTH_SAFE, "Chiếc chuông gió", duration, "vi")
        thin_script = " ".join(item["text"] for item in thin["script"])
        self.assertIn("Chiếc chuông gió", thin_script)
        boat = provider.generate(
            Profile.YOUTH_SAFE,
            "Bo buồn vì chiếc thuyền bị rách và xin mẹ ngồi bên.",
            duration,
            "vi",
        )
        boat_script = " ".join(item["text"] for item in boat["script"]).casefold()
        self.assertNotIn("lựa chọn là của cậu", boat_script)
        self.assertNotRegex(boat_script, r'"(?:cậu|tớ) ')
        self.assertIn('"con ', boat_script)
        self.assertIn('"mẹ ', boat_script)

    def test_deterministic_character_cards_are_informative_and_distinct(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE,
            "Hoa, học sinh lớp 5 ở Hà Nội, quyết tâm tham gia cuộc thi vẽ tranh.",
            confirm_duration(Profile.YOUTH_SAFE, 5),
            "vi",
        )
        provider = DeterministicCharacterImageProvider()
        rendered = [provider.generate(character) for character in story["characters"]]
        self.assertEqual(len({pixel_hash for _, pixel_hash in rendered}), 2)
        for data, _ in rendered:
            self.assertEqual(png_dimensions(data), (1536, 2048))
            statistics = png_visual_statistics(data)
            self.assertGreaterEqual(statistics["sampled_unique_colors"], 16)
            self.assertGreaterEqual(statistics["sampled_channel_range"], 12)

    def test_character_gate_blocks_failed_semantic_identity_evidence(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE, "Hoa cùng bạn chăm sóc khu vườn.",
            confirm_duration(Profile.YOUTH_SAFE, 5), "vi",
        )
        image_provider = DeterministicCharacterImageProvider()
        pipeline = Stage1Pipeline(
            story_provider=DeterministicStoryProvider(), image_provider=image_provider,
            safety_provider=RuleBasedSafetyProvider(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            images, pixels = pipeline._create_character_references(story, Path(temporary))
        pipeline._bind_character_references(story, images, pixels)
        story["characters"][0]["reference_asset"]["quality_assessment"] = {
            "status": "ASSESSED_FAIL", "method": "CLIP_CONTRASTIVE_CHARACTER_QA",
            "checks": [],
            "findings": [{
                "error": "CHARACTER_PERSON_COUNT_MISMATCH",
                "expected": "one person", "observed": "multiple people",
            }],
        }

        gate = Stage1Validator._characters(story, Profile.YOUTH_SAFE, images)

        self.assertEqual(gate.status, "FAIL")
        self.assertIn(
            "CHARACTER_PERSON_COUNT_MISMATCH",
            {item["error"] for item in gate.findings},
        )

    def test_deterministic_generator_follows_vietnamese_drawing_brief(self) -> None:
        brief = (
            "Hoa, một học sinh lớp 5 ở thành phố Hồ Chí Minh, quyết tâm chuẩn bị cho "
            "cuộc thi vẽ tranh của trường. Nhưng cô phải học cách vượt qua nỗi sợ vẽ "
            "trước một đám đông. Nếu không vượt qua nỗi sợ, Hoa có thể bỏ cuộc và "
            "không thể thể hiện tài năng của mình."
        )
        duration = confirm_duration(Profile.YOUTH_SAFE, 5)
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE, brief, duration, "vi"
        )
        self.assertEqual(story["characters"][0]["name"], "Hoa")
        self.assertEqual(story["characters"][0]["canonical_age_min"], 10)
        self.assertIn("Bức Tranh", story["meta"]["title"])
        script = " ".join(item["text"] for item in story["script"])
        for phrase in ("thành phố Hồ Chí Minh", "cuộc thi vẽ tranh", "đám đông", "tài năng"):
            self.assertIn(phrase, script)
        self.assertNotRegex(
            script,
            r"(?:Hình ảnh|Dấu vết|Ở bước|Thử thách|Hành động|Hậu quả|Chi tiết)\s+\d+",
        )
        gates = [
            Stage1Validator._word_duration(story, duration),
            Stage1Validator._zone_budget(story),
            Stage1Validator._brief_adherence(story, brief),
            Stage1Validator._intra_zone_repetition(story),
            Stage1Validator._semantic_repetition(story),
            Stage1Validator._age_profile(story, Profile.YOUTH_SAFE, duration),
            Stage1Validator._dialogue_structure(story, Profile.YOUTH_SAFE),
            Stage1Validator._quality(story, Profile.YOUTH_SAFE, brief),
        ]
        self.assertTrue(all(gate.status == "PASS" for gate in gates))
        dialogue = next(gate for gate in gates if gate.gate_id == "DIALOGUE_STRUCTURE_GATE")
        self.assertGreaterEqual(dialogue.metrics["direct_dialogue_turn_count"], 6)
        quality = next(gate for gate in gates if gate.gate_id == "STORY_QUALITY_GATE")
        self.assertGreaterEqual(quality.metrics["editorial_score"], 80)

    def test_structure_accepts_punctuation_before_closing_quote(self) -> None:
        provider = DeterministicStoryProvider()
        story = provider.generate(
            Profile.YOUTH_SAFE,
            "Hai người bạn bảo vệ khu vườn sau mưa.",
            confirm_duration(Profile.YOUTH_SAFE, 5),
            "vi",
        )
        story["script"][0]["text"] = 'Thanh nói: "Chúng ta bắt đầu nhé!"'
        gate = Stage1Validator._structure(story)
        self.assertFalse(any(
            item["error"] == "INCOMPLETE_TEXT" and item["locator"] == "script[0].text"
            for item in gate.findings
        ))

    def test_vietnamese_language_gate_blocks_embedded_english_sentence(self) -> None:
        story = {
            "meta": {"language": "vi"},
            "script": [{
                "text": 'Phương cầm chuông gió. She handed the wind chime to Thanh. Look, it fits perfectly here.',
            }],
        }
        gate = Stage1Validator._language_integrity(story)
        self.assertEqual(gate.status, "FAIL")
        self.assertTrue(any(
            item["error"] == "UNEXPECTED_LANGUAGE_TOKENS" for item in gate.findings
        ))

    def test_character_set_uses_one_cast_configuration_and_complete_identity_lock(self) -> None:
        class CastAwareProvider(DeterministicCharacterImageProvider):
            art_direction_id = "vietnamese-storybook-test-v1"

            def __init__(self):
                self.configured = []

            def configure_cast(self, story):
                self.configured.append([item["character_id"] for item in story["characters"]])

        character = {
            "character_id": "an", "name": "An", "role": "chị gái",
            "canonical_age_min": 8, "canonical_age_max": 8,
            "adult_visual_eligibility": "NOT_ADULT", "visual_story_importance": "PRIMARY",
            "identity_traits": ["tốt bụng", "cẩn thận"],
            "visual_identity": {
                "presentation": "FEMININE", "hair": "tóc đen buộc hai bên",
                "wardrobe": "áo mưa xanh lá", "palette": ["green", "cream"],
                "silhouette": "bé gái nhỏ nhắn", "cultural_context": "Việt Nam đương đại",
            },
        }
        story = {"characters": [character]}
        provider = CastAwareProvider()
        pipeline = Stage1Pipeline(
            story_provider=DeterministicStoryProvider(), image_provider=provider,
            safety_provider=RuleBasedSafetyProvider(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            images, pixels = pipeline._create_character_references(story, Path(temporary))
            pipeline._bind_character_references(story, images, pixels)
        locks = story["characters"][0]["reference_asset"]["identity_lock"]
        self.assertEqual(provider.configured, [["an"]])
        self.assertIn("style:vietnamese-storybook-test-v1", locks)
        self.assertIn("age:8-8", locks)
        self.assertIn("wardrobe:áo mưa xanh lá", locks)
        self.assertIn("palette:green,cream", locks)

    def test_repair_findings_preserve_gate_provenance_and_localize_global_issue(self) -> None:
        story = {"script": [
            {"zone": "OPENING", "text": "Mở đầu."},
            {"zone": "DEVELOPMENT", "text": "Phát triển."},
        ]}
        gates = [
            GateResult(
                "LANGUAGE_INTEGRITY_GATE", "PUBLISH_BLOCKER", "FAIL", "TEST", {},
                [{"locator": "script[1].text", "error": "UNEXPECTED_UNICODE_SCRIPT"}],
            ),
            GateResult(
                "WORD_DURATION_GATE", "PUBLISH_BLOCKER", "FAIL", "TEST", {},
                [{"locator": "script", "error": "WORD_BUDGET_INVALID"}],
            ),
            GateResult(
                "PROFILE_SAFETY_GATE", "PUBLISH_BLOCKER", "FAIL", "TEST", {},
                [{"locator": "$", "category": "INVALID_ASSESSMENT", "reason": "bad status"}],
            ),
        ]
        findings = Stage1Pipeline._repair_findings(story, gates)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["gate_id"], "LANGUAGE_INTEGRITY_GATE")
        self.assertEqual(findings[1]["related_zones"], ["DEVELOPMENT"])
        self.assertEqual(findings[1]["scope"], "GLOBAL_CONTEXT_ONLY")

    def test_repair_findings_include_semantic_repetition_sentence_text(self) -> None:
        source = "Hà quyết tâm tham gia cuộc thi sáng tác truyện ngắn của trường."
        target = "Hà quyết tâm tham gia cuộc thi sáng tác truyện ngắn của trường."
        story = {"script": [
            {"zone": "OPENING", "text": source},
            {"zone": "INTRODUCTION", "text": target},
        ]}
        gate = Stage1Validator._semantic_repetition(story)

        findings = Stage1Pipeline._repair_findings(story, [gate])

        self.assertEqual(findings[0]["source_sentence_text"], source)
        self.assertEqual(findings[0]["target_sentence_text"], target)
        self.assertEqual(findings[0]["gate_id"], "SEMANTIC_REPETITION_GATE")

    def test_repair_findings_expand_model_critic_details_to_zone(self) -> None:
        story = {"script": [
            {"zone": "OPENING", "text": "Mở đầu."},
            {"zone": "ENDING", "text": "Kết thúc."},
        ]}
        gate = GateResult(
            "STORY_QUALITY_GATE", "PUBLISH_BLOCKER", "FAIL", "TEST",
            {"model_critic": {
                "status": "FAIL",
                "findings": [{
                    "zone": "ENDING", "issue": "Payoff còn yếu",
                    "instruction": "Cho thấy lựa chọn tạo ra thay đổi cụ thể.",
                }],
                "evidence_locators": ["script[1].text"],
            }},
            [{"locator": "script[1].text", "error": "MODEL_CRITIC_FINDINGS_REMAIN"}],
        )

        findings = Stage1Pipeline._repair_findings(story, [gate])

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["locator"], "script[1].text")
        self.assertEqual(findings[0]["issue"], "Payoff còn yếu")
        self.assertEqual(findings[0]["gate_id"], "STORY_QUALITY_GATE")

    def test_ordered_repair_findings_selects_one_dependency_layer(self) -> None:
        findings = [
            {"gate_id": "STORY_QUALITY_GATE", "error": "MODEL_CRITIC_FINDING"},
            {"gate_id": "SEMANTIC_REPETITION_GATE", "error": "REPEAT"},
            {"gate_id": "SCENE_STATE_CONTINUITY_GATE", "error": "STATE"},
        ]

        selected = Stage1Pipeline._ordered_repair_findings(findings)

        self.assertEqual(selected, [findings[2]])

    def test_ordered_repair_findings_prefers_root_defect_over_quality_score(self) -> None:
        findings = [
            {"gate_id": "STORY_QUALITY_GATE", "error": "EDITORIAL_SCORE_BELOW_THRESHOLD"},
            {
                "gate_id": "AGE_PROFILE_GATE",
                "error": "SENTENCE_TOO_COMPLEX_FOR_AGE_PROFILE",
                "locator": "script[1].text",
                "sentence_index": 2,
            },
            {
                "gate_id": "EDITORIAL_INTEGRITY_GATE",
                "error": "EXCESSIVE_TOLD_EMOTION",
                "locator": "script[5].text#sentence[4]",
            },
        ]

        selected = Stage1Pipeline._ordered_repair_findings(findings)

        self.assertEqual(selected, [findings[1]])

    def test_repair_snapshot_records_story_and_blocker_evidence(self) -> None:
        story = {"script": [{"zone": "OPENING", "text": "An quan sát."}]}
        gate = GateResult(
            "TEST_GATE", "PUBLISH_BLOCKER", "FAIL", "TEST", {},
            [{"locator": "script[0].text", "error": "TEST_ERROR"}],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Stage1Pipeline._write_repair_snapshot(
                root, 1, "before", story, [gate], gate.findings
            )
            payload = json.loads((root / "repairs" / "repair-01-before.json").read_text("utf-8"))
        self.assertEqual(payload["round"], 1)
        self.assertEqual(payload["blockers"][0]["gate_id"], "TEST_GATE")
        self.assertTrue(payload["story_digest_sha256"])

    def test_repair_score_prioritizes_publish_safety_over_quality_count(self) -> None:
        publish_failure = GateResult(
            "SAFETY", "PUBLISH_BLOCKER", "FAIL", "TEST", {},
            [{"locator": "script[1].text", "error": "UNSAFE"}],
        )
        quality_failures = [
            GateResult(
                f"QUALITY_{index}", "QUALITY_BLOCKER", "FAIL", "TEST", {},
                [{"locator": "script[1].text", "error": "QUALITY"}],
            )
            for index in range(3)
        ]

        self.assertGreater(
            Stage1Pipeline._repair_score([publish_failure]),
            Stage1Pipeline._repair_score(quality_failures),
        )

    def test_repair_immutable_digest_locks_facts_but_allows_prose_patch(self) -> None:
        story = {
            "schema_version": "2.3",
            "meta": {"title": "Hà", "story_quality_commitment": {"score": 1}},
            "characters": [{"name": "Hà", "canonical_age_min": 10, "reference_asset": {"hash": "a"}}],
            "outline": {"opening": "Hà tới đảo."},
            "script": [{"zone": "OPENING", "environment": "sea_wind_soft", "voice": "NARRATOR", "speed": "NORMAL", "lang": "VI", "text": "Hà tới đảo."}],
        }
        prose_patch = copy.deepcopy(story)
        prose_patch["script"][0]["text"] = "Hà đặt chân lên đảo."
        prose_patch["meta"]["story_quality_commitment"] = {"score": 2}
        fact_change = copy.deepcopy(story)
        fact_change["characters"][0]["canonical_age_min"] = 18

        self.assertEqual(
            Stage1Pipeline._immutable_story_digest(story),
            Stage1Pipeline._immutable_story_digest(prose_patch),
        )
        self.assertNotEqual(
            Stage1Pipeline._immutable_story_digest(story),
            Stage1Pipeline._immutable_story_digest(fact_change),
        )

    def test_warning_diagnostic_is_not_written_to_package_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = RunWorkspace.create(
                Path(temporary), Profile.YOUTH_SAFE, "run-stage1-warning-diagnostic"
            )
            legacy_diagnostic = workspace.work_dir / "stage1_failed_validation.json"
            legacy_diagnostic.write_text("{}", encoding="utf-8")
            diagnostic = Stage1Pipeline._write_gate_warning_diagnostic(
                workspace, {"status": "COMPLETED_WITH_WARNINGS"}
            )

            self.assertTrue(diagnostic.is_file())
            self.assertEqual(diagnostic.parent, workspace.logs_dir)
            self.assertEqual(
                json.loads(diagnostic.read_text(encoding="utf-8"))["status"],
                "COMPLETED_WITH_WARNINGS",
            )
            self.assertFalse(legacy_diagnostic.exists())
    def test_character_image_qa_retries_with_new_attempt(self) -> None:
        class RetryProvider(DeterministicCharacterImageProvider):
            def __init__(self): self.attempts = []
            def generate_attempt(self, character, attempt):
                self.attempts.append(attempt)
                if attempt < 3:
                    raise ArtifactError("pseudo text")
                return self.generate(character)
        provider = RetryProvider()
        pipeline = Stage1Pipeline(
            story_provider=DeterministicStoryProvider(), image_provider=provider,
            safety_provider=RuleBasedSafetyProvider(),
        )
        story = {"characters": [{"character_id": "an"}]}
        with tempfile.TemporaryDirectory() as temporary:
            images, _ = pipeline._create_character_references(story, Path(temporary))
        self.assertEqual(provider.attempts, [1, 2, 3])
        self.assertIn("characters/an.png", images)
    def test_language_integrity_blocks_foreign_script_and_dangling_sentence(self) -> None:
        story = {
            "meta": {"language": "vi"},
            "script": [
                {"text": "Bo luôn cảm thấy hào hứng mỗi."},
                {"text": "第二天，Bo đi ra công viên。"},
            ],
        }
        gate = Stage1Validator._language_integrity(story)
        self.assertEqual(gate.status, "FAIL")
        errors = {finding["error"] for finding in gate.findings}
        self.assertIn("UNEXPECTED_UNICODE_SCRIPT", errors)
        self.assertIn("UNEXPECTED_SENTENCE_PUNCTUATION", errors)
        self.assertIn("DANGLING_SENTENCE_END", errors)

    def test_sentence_completeness_blocks_fragments_and_unclosed_quotes(self) -> None:
        story = {
            "meta": {"language": "vi"},
            "script": [
                {"text": "Bo đặt thuyền lên bàn. Mẹ bảo: \"Con hãy giữ nó."},
                {"text": "Bo muốn đi cùng mẹ để."},
            ],
        }
        gate = Stage1Validator._sentence_completeness(story)
        self.assertEqual(gate.status, "FAIL")
        errors = {finding["error"] for finding in gate.findings}
        self.assertIn("UNCLOSED_QUOTE", errors)
        self.assertIn("DANGLING_CLAUSE_END", errors)

    def test_sentence_completeness_accepts_vietnamese_compound_ending(self) -> None:
        story = {
            "meta": {"language": "vi"},
            "script": [{"text": "Hai bạn xem lại kết quả thật công bằng."}],
        }
        self.assertEqual(Stage1Validator._sentence_completeness(story).status, "PASS")

    def test_sentence_completeness_checks_fragments_inside_zone(self) -> None:
        story = {"meta": {"language": "vi"}, "script": [{
            "text": "Hà bước vào rừng. Cô bé. Tôi gật đầu, cố gắng không để. Hà quay về nhà."
        }]}

        gate = Stage1Validator._sentence_completeness(story)

        self.assertEqual(gate.status, "FAIL")
        self.assertIn("SUBJECT_ONLY_FRAGMENT", {item["error"] for item in gate.findings})
        self.assertIn("DANGLING_CLAUSE_END", {item["error"] for item in gate.findings})

    def test_prose_hygiene_detects_name_fragment_empty_quote_and_generic_filler(self) -> None:
        story = {
            "characters": [{"name": "Hoa"}, {"name": "Nam"}],
            "script": [{
                "zone": "DEVELOPMENT",
                "text": (
                    'Hoa. Nam nhìn chiếc cốc rồi nói: "." '
                    "Nhân vật kiểm tra chi tiết trước mắt rồi tiếp tục."
                ),
            }],
        }

        gate = Stage1Validator._prose_hygiene(story)

        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(
            {finding["error"] for finding in gate.findings},
            {"NAME_ONLY_FRAGMENT", "MALFORMED_EMPTY_QUOTE", "GENERIC_REPAIR_FILLER"},
        )

    def test_narrative_voice_blocks_person_and_address_shift(self) -> None:
        story = {
            "characters": [{
                "name": "Hà", "role": "Protagonist",
                "visual_identity": {"presentation": "FEMININE"},
            }],
            "script": [{"voice": "NARRATOR", "text": "Hà nhìn cha. Tôi gật đầu. Cha gọi Hà là con trai."}],
        }

        gate = Stage1Validator._narrative_voice_consistency(story)

        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(
            {item["error"] for item in gate.findings},
            {"NARRATIVE_PERSON_SHIFT", "CHARACTER_GENDER_ADDRESS_MISMATCH"},
        )

    def test_narrative_voice_ignores_first_person_inside_unclosed_dialogue(self) -> None:
        story = {
            "characters": [{"name": "Lan", "role": "Protagonist", "visual_identity": {}}],
            "script": [{
                "voice": "NARRATOR",
                "text": 'Lan nhìn ra cửa sổ. Lan nói: "Tôi sẽ quay lại vào sáng mai.',
            }],
        }

        gate = Stage1Validator._narrative_voice_consistency(story)

        self.assertEqual(gate.status, "PASS")

    def test_scene_state_continuity_blocks_broken_chain_and_premature_outcome(self) -> None:
        story = {
            "outline": {
                "greeting": {"entry_state": "Hà ở nhà", "exit_state": "Hà đến bến thuyền"},
                "opening": {"entry_state": "Hà đang trong rừng", "exit_state": "Hà tìm thấy bản đồ"},
                "introduction": "", "development": "",
                "climax": "trạng thái đổi từ Hà có bản đồ thành Hà đã chuẩn bị hành lý.",
                "falling": "trạng thái đổi từ Hà đã chuẩn bị hành lý thành Hà đã lên thuyền.",
                "ending": "", "farewell": "",
            },
            "script": [
                {"zone": "GREETING", "text": "Hà đến bến thuyền."},
                {"zone": "OPENING", "text": "Hà tìm thấy bản đồ và đã chuẩn bị hành lý."},
                {"zone": "INTRODUCTION", "text": ""}, {"zone": "DEVELOPMENT", "text": ""},
                {"zone": "CLIMAX", "text": "Hà xem bản đồ."},
                {"zone": "FALLING", "text": "Hà đã lên thuyền."},
                {"zone": "ENDING", "text": ""}, {"zone": "FAREWELL", "text": ""},
            ],
        }

        gate = Stage1Validator._scene_state_continuity(story)

        self.assertEqual(gate.status, "FAIL")
        errors = {item["error"] for item in gate.findings}
        self.assertIn("SCENE_ENTRY_STATE_MISMATCH", errors)
        self.assertIn("PREMATURE_SCENE_OUTCOME", errors)

    def test_youth_context_safety_blocks_minor_operating_boat_alone(self) -> None:
        story = {
            "characters": [
                {"name": "Hà", "canonical_age_min": 10, "canonical_age_max": 10},
                {"name": "Cha Hà", "canonical_age_min": 40, "canonical_age_max": 40},
            ],
            "script": [{"text": "Hà bước lên thuyền nhỏ. Hà điều khiển thuyền về phía đảo trong đêm tối."}],
        }

        gate = Stage1Validator._youth_context_safety(story, Profile.YOUTH_SAFE)

        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(gate.findings[0]["error"], "UNSUPERVISED_MINOR_HIGH_RISK_ACTIVITY")
        self.assertEqual(Stage1Validator._language_integrity(story).status, "PASS")

    def test_brief_policy_rejects_unsafe_and_deliberately_incoherent_requests(self) -> None:
        cases = {
            "Mô tả chi tiết một cuộc đánh nhau đẫm máu giữa trẻ em":
                "UNSAFE_GRAPHIC_CHILD_VIOLENCE_REQUEST",
            "Hung thủ được chọn ở đoạn cuối dù trước đó không có manh mối nào":
                "UNSUPPORTED_CULPRIT_REVEAL_REQUEST",
            "Tang vật bị niêm phong nhưng liên tục đổi vị trí mà không có lời giải":
                "UNEXPLAINED_EVIDENCE_STATE_CHANGE_REQUEST",
            "Nhân vật chính chết giữa truyện nhưng xuất hiện bình thường ở kết thúc mà không giải thích":
                "UNEXPLAINED_RETURN_AFTER_DEATH_REQUEST",
            "Một cuộc tranh luận dài giữa bốn người nhưng không ghi dấu người nói":
                "UNATTRIBUTED_MULTI_SPEAKER_DIALOGUE_REQUEST",
            "Viết toàn câu cụt. Mưa. Chạy. Sợ.":
                "DELIBERATE_FRAGMENT_STYLE_REQUEST",
        }
        for brief, error in cases.items():
            with self.subTest(error=error):
                gate = Stage1Validator._brief_policy(brief, Profile.YOUTH_SAFE)
                self.assertEqual(gate.status, "FAIL")
                self.assertEqual(gate.findings[0]["error"], error)
                self.assertEqual(gate.findings[0]["locator"], "request.brief")
        accepted = Stage1Validator._brief_policy(
            "Điều tra hung thủ bằng chuỗi manh mối rõ ràng.", Profile.SERIAL_DETECTIVE
        )
        self.assertEqual(accepted.status, "PASS")

    def test_deterministic_generator_does_not_echo_fragment_instruction(self) -> None:
        brief = "Viết toàn câu cụt. Mưa. Chạy. Sợ."
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE, brief, confirm_duration(Profile.YOUTH_SAFE, 5), "vi"
        )
        script = " ".join(item["text"] for item in story["script"]).casefold()
        self.assertNotIn("câu cụt", script)

    def test_brief_invariant_blocks_repaired_boat_and_repeated_lesson(self) -> None:
        story = {
            "script": [
                {"text": "Bo dùng keo và đã vá xong chiếc thuyền."},
                {"text": "Bài học của câu chuyện là luôn hy vọng."},
            ]
        }
        gate = Stage1Validator._narrative_invariants(
            story, "Thuyền không lành lại. Chào ngắn, không nhắc lại bài học."
        )
        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(gate.metrics["invariant_count"], 2)
        self.assertEqual(
            {finding["invariant_id"] for finding in gate.findings},
            {"DAMAGED_OBJECT_REMAINS_DAMAGED", "NO_RESTATED_LESSON"},
        )

    def test_brief_invariant_accepts_natural_negated_repair_phrase(self) -> None:
        story = {
            "script": [{
                "text": (
                    "Chiếc thuyền rách, không còn lành lại được. "
                    "Bo hiểu rằng nó chẳng thể sửa xong như trước."
                )
            }]
        }
        gate = Stage1Validator._narrative_invariants(
            story, "Chiếc thuyền không lành lại và vẫn còn rách."
        )
        self.assertEqual(gate.status, "PASS")

    def test_narrative_coherence_blocks_cross_zone_repetition(self) -> None:
        repeated = " ".join(["An tìm thấy dấu vết rồi đưa ra lựa chọn rõ ràng giữa cơn mưa"] * 20)
        story = {
            "outline": {"opening": "An tìm thấy dấu vết", "climax": "An đưa ra lựa chọn"},
            "script": [
                {"zone": "OPENING", "text": repeated},
                {"zone": "CLIMAX", "text": repeated},
            ],
        }
        gate = Stage1Validator._narrative_coherence(story)
        self.assertEqual(gate.status, "FAIL")
        self.assertTrue(any(item["error"] == "CROSS_ZONE_REPETITION" for item in gate.findings))

    def test_semantic_repetition_detects_near_duplicate_sentences(self) -> None:
        story = {
            "script": [
                {"zone": "OPENING", "text": "Bo đặt chiếc thuyền giấy cũ cạnh chiếc gối xanh rồi ngồi chờ mẹ trở về."},
                {"zone": "ENDING", "text": "Bo đặt chiếc thuyền giấy cũ bên chiếc gối xanh và ngồi đợi mẹ trở về."},
            ]
        }
        gate = Stage1Validator._semantic_repetition(story)
        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(gate.metrics["semantic_repetition_pair_count"], 1)
        self.assertIn("source_locator", gate.findings[0])

    def test_semantic_repetition_detects_duplicates_inside_one_zone(self) -> None:
        story = {"script": [{
            "zone": "OPENING",
            "text": (
                "Hào quyết định lập tức đi tìm người lớn để cứu con chim. "
                "Cậu che đôi cánh ướt bằng chiếc khăn sạch. "
                "Hào quyết định lập tức đi tìm người lớn để cứu con chim."
            ),
        }]}

        gate = Stage1Validator._semantic_repetition(story)

        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(gate.findings[0]["error"], "INTRA_ZONE_SEMANTIC_REPETITION")

    def test_dialogue_gate_rejects_conflicting_speaker_labels(self) -> None:
        story = {
            "characters": [{"name": "Hào"}, {"name": "Bác Tư"}],
            "script": [{
                "zone": "FALLING",
                "text": 'Bác Tư nói: "Bác Tư ơi, bác giúp con được không?" Hào hỏi.',
            }],
        }

        gate = Stage1Validator._dialogue_structure(story)

        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(gate.findings[0]["error"], "CONFLICTING_DIALOGUE_ATTRIBUTION")

    def test_scene_state_continuity_rejects_conflicting_destination(self) -> None:
        story = {
            "outline": {
                "greeting": "Mở đầu.",
                "opening": (
                    "trạng thái đổi từ Hào thấy con chim bị thương "
                    "thành Hào bắt đầu di chuyển về nhà."
                ),
                "introduction": (
                    "trạng thái đổi từ Hào bắt đầu di chuyển về nhà "
                    "thành Hào đã về nhà."
                ),
                "development": "", "climax": "", "falling": "",
                "ending": "", "farewell": "",
            },
            "script": [
                {"zone": "GREETING", "text": "Hào nhìn thấy con chim."},
                {
                    "zone": "OPENING",
                    "text": "Hào quyết định đi đến phòng khám thú y để tìm trợ giúp.",
                },
                {"zone": "INTRODUCTION", "text": "Hào bắt đầu di chuyển về nhà."},
            ],
        }

        gate = Stage1Validator._scene_state_continuity(story)

        self.assertTrue(any(
            finding["error"] == "SCENE_DESTINATION_CONFLICT"
            for finding in gate.findings
        ))
    def test_intra_zone_repetition_normalizes_sequence_numbers_and_placeholders(self) -> None:
        story = {
            "script": [{
                "zone": "OPENING",
                "text": "Dấu vết 3 buộc An quan sát kỹ hơn. Dấu vết 4 buộc An quan sát kỹ hơn. Dấu vết 5 buộc An quan sát kỹ hơn.",
            }]
        }
        gate = Stage1Validator._intra_zone_repetition(story)
        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(
            {finding["error"] for finding in gate.findings},
            {"INTRA_ZONE_TEMPLATE_REPETITION", "PLACEHOLDER_PROSE_DETECTED"},
        )

    def test_brief_adherence_blocks_unrelated_story(self) -> None:
        story = {
            "meta": {"title": "Bí mật khu vườn"},
            "characters": [{"name": "An"}, {"name": "Minh"}],
            "outline": {"opening": "Hai bạn tìm dấu vết."},
            "script": [{"text": "An và Minh bảo vệ một bí mật trong khu vườn."}],
        }
        gate = Stage1Validator._brief_adherence(
            story,
            "Bo cùng mẹ giữ chiếc thuyền giấy còn rách cạnh gối xanh và trang sách.",
        )
        self.assertEqual(gate.status, "FAIL")
        self.assertLess(gate.metrics["coverage"], 0.35)

    def test_brief_adherence_rejects_wrong_primary_character_even_with_copied_terms(self) -> None:
        brief = (
            "Hoa, học sinh lớp 5 ở Hà Nội, quyết tâm tham gia cuộc thi vẽ tranh. "
            "Nếu bỏ cuộc, Hoa không thể thể hiện tài năng."
        )
        story = {
            "meta": {"title": "Cuộc thi vẽ tranh của Hoa"},
            "characters": [{"name": "An"}, {"name": "Hoa"}],
            "outline": {"opening": brief},
            "script": [{"text": brief}],
        }
        gate = Stage1Validator._brief_adherence(story, brief)
        self.assertEqual(gate.status, "FAIL")
        self.assertTrue(any(
            finding["error"] == "BRIEF_PROTAGONIST_MISMATCH"
            for finding in gate.findings
        ))

    def test_youth_age_profile_reports_long_sentence_with_locator(self) -> None:
        long_sentence = " ".join(["Bo quan sát khu vườn"] * 12) + "."
        story = {"script": [{"zone": "OPENING", "text": long_sentence}]}
        gate = Stage1Validator._age_profile(story, Profile.YOUTH_SAFE)
        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(gate.metrics["age_profile"], "KIDS_7_10")
        self.assertEqual(gate.findings[0]["locator"], "script[0].text")

    def test_bookend_budget_blocks_padded_greeting_and_farewell(self) -> None:
        padded = " ".join(["Lời chào dài"] * 20) + "."
        story = {"script": [
            {"zone": "GREETING", "text": padded},
            {"zone": "OPENING", "text": "Bo nhìn chiếc thuyền."},
            {"zone": "FAREWELL", "text": padded},
        ]}
        gate = Stage1Validator._zone_budget(story)
        self.assertEqual(gate.status, "FAIL")
        self.assertEqual(len(gate.findings), 2)
        self.assertTrue(all(item["error"] == "BOOKEND_TOO_LONG" for item in gate.findings))

    def test_weighted_rubric_requires_model_corroboration_for_assessed_basis(self) -> None:
        texts = {
            "GREETING": "Chào bạn đến với câu chuyện của Bo.",
            "OPENING": "Bo buồn vì mưa làm chiếc thuyền giấy rách trên bàn trong phòng.",
            "INTRODUCTION": "Bo cầm chiếc thuyền bằng hai tay nên mẹ ngồi xuống cạnh gối xanh.",
            "DEVELOPMENT": "Bo từ chối thuyền mới vì em thương ô cửa nhỏ mình đã gấp trên giấy.",
            "CLIMAX": "Bo chọn giữ vết rách và nói với mẹ rằng em sợ kỷ niệm sẽ biến mất.",
            "FALLING": "Mẹ ôm Bo khiến đôi vai em nhẹ xuống, rồi đặt sách cạnh chiếc thuyền.",
            "ENDING": "Bo nhẹ nhõm đặt thuyền trên bến khô cạnh gối và mở trang sách thành dòng sông.",
            "FAREWELL": "Tạm biệt Bo và mẹ bên chiếc thuyền giấy.",
        }
        story = {
            "meta": {"tone": ["ấm áp"]},
            "characters": [{"name": "Bo"}, {"name": "Mẹ"}],
            "outline": {zone.lower(): text for zone, text in texts.items()},
            "script": [
                {"zone": zone, "environment": "none" if zone in {"GREETING", "FAREWELL"} else "bedroom_warm", "text": text}
                for zone, text in texts.items()
            ],
        }
        brief = (
            "Mưa làm chiếc thuyền giấy của Bo rách. Bo từ chối thuyền mới, nói mình buồn và sợ. "
            "Mẹ ôm Bo. Bo giữ vết rách, đặt thuyền cạnh gối xanh và mở trang sách thành dòng sông."
        )
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE, brief, confirm_duration(Profile.YOUTH_SAFE, 5), "vi"
        )
        preflight = Stage1Validator._quality(story, Profile.YOUTH_SAFE, brief)
        assessed = Stage1Validator._quality(
            story,
            Profile.YOUTH_SAFE,
            brief,
            {
                "status": "PASS", "method": "MODEL_STORY_CRITIC_V2", "finding_count": 0,
                "evidence_locators": ["script[1].text", "script[4].text", "script[6].text"],
            },
        )
        self.assertEqual(preflight.status, "PASS")
        self.assertGreaterEqual(preflight.metrics["editorial_score"], 80)
        self.assertEqual(preflight.metrics["assessment_basis"], "DETERMINISTIC_PREFLIGHT_ONLY")
        self.assertEqual(assessed.metrics["assessment_basis"], "MODEL_CRITIC_CORROBORATED")

    def test_model_critic_without_evidence_cannot_corroborate(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE,
            "Hoa, học sinh lớp 5 ở Hà Nội, quyết tâm tham gia cuộc thi vẽ tranh.",
            confirm_duration(Profile.YOUTH_SAFE, 5),
            "vi",
        )
        result = Stage1Validator._quality(
            story,
            Profile.YOUTH_SAFE,
            "Hoa, học sinh lớp 5 ở Hà Nội, quyết tâm tham gia cuộc thi vẽ tranh.",
            {"status": "PASS", "method": "MODEL_STORY_CRITIC_V2", "findings": []},
        )
        self.assertEqual(result.metrics["assessment_basis"], "DETERMINISTIC_PREFLIGHT_ONLY")
        self.assertFalse(result.metrics["critic_evidence_valid"])

    def test_model_critic_failure_without_per_finding_evidence_is_not_blocking(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE,
            "Hoa tìm lại chiếc chuông gió trong khu vườn.",
            confirm_duration(Profile.YOUTH_SAFE, 5),
            "vi",
        )
        result = Stage1Validator._quality(
            story,
            Profile.YOUTH_SAFE,
            "Hoa tìm lại chiếc chuông gió trong khu vườn.",
            {
                "status": "FAIL", "method": "MODEL_STORY_CRITIC_V2",
                "finding_count": 1, "findings": [{"issue": "Cảnh kết yếu"}],
                "evidence_locators": ["script[6].text"],
            },
        )

        self.assertEqual(result.metrics["assessment_basis"], "MODEL_CRITIC_CORROBORATED")
        self.assertEqual(result.status, "PASS")
        self.assertFalse(any(
            item.get("error") == "MODEL_CRITIC_FINDINGS_REMAIN"
            for item in result.findings
        ))

    def test_model_critic_structural_finding_with_locator_remains_blocking(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE,
            "Hoa tìm lại chiếc chuông gió trong khu vườn.",
            confirm_duration(Profile.YOUTH_SAFE, 5),
            "vi",
        )
        result = Stage1Validator._quality(
            story,
            Profile.YOUTH_SAFE,
            "Hoa tìm lại chiếc chuông gió trong khu vườn.",
            {
                "status": "FAIL", "method": "MODEL_STORY_CRITIC_V2",
                "finding_count": 1,
                "findings": [{
                    "zone": "ENDING", "locator": "script[6].text",
                    "category": "STRUCTURE", "blocking": True,
                    "issue": "Payoff không thể hiện kết quả hành động.",
                    "instruction": "Cho thấy thay đổi cụ thể sau lựa chọn ở cao trào.",
                }],
                "evidence_locators": ["script[6].text"],
            },
        )

        self.assertEqual(result.metrics["assessment_basis"], "MODEL_CRITIC_ASSESSED")
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(
            result.metrics["model_critic"]["evidence_locators"], ["script[6].text"]
        )

    def test_model_critic_style_observation_is_not_blocking(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE, "Hoa chăm sóc khu vườn.",
            confirm_duration(Profile.YOUTH_SAFE, 5), "vi",
        )
        result = Stage1Validator._quality(
            story, Profile.YOUTH_SAFE, "Hoa chăm sóc khu vườn.",
            {
                "status": "FAIL", "method": "MODEL_STORY_CRITIC_V2",
                "findings": [{
                    "zone": "OPENING", "locator": "script[1].text",
                    "category": "STYLE", "blocking": False,
                    "issue": "Câu văn có thể sinh động hơn.",
                    "instruction": "Thêm một chi tiết cảm giác.",
                }],
                "evidence_locators": ["script[1].text"],
            },
        )
        self.assertFalse(any(
            finding.get("error") == "MODEL_CRITIC_FINDINGS_REMAIN"
            for finding in result.findings
        ))

    def test_model_critic_unrelated_subplot_label_is_advisory(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.ADULT_STANDARD, "Linh chọn rời căn nhà cũ.",
            confirm_duration(Profile.ADULT_STANDARD, 20), "vi",
        )
        result = Stage1Validator._quality(
            story, Profile.ADULT_STANDARD, "Linh chọn rời căn nhà cũ.",
            {
                "status": "FAIL", "method": "MODEL_STORY_CRITIC_V2",
                "findings": [{
                    "zone": "FALLING", "locator": "script[5].text",
                    "category": "STRUCTURE", "blocking": True,
                    "issue": "Unrelated subplot about flowers.",
                    "instruction": "Remove the flowers.",
                }],
                "evidence_locators": ["script[5].text"],
            },
        )
        self.assertFalse(any(
            finding.get("error") == "MODEL_CRITIC_FINDINGS_REMAIN"
            for finding in result.findings
        ))

    def test_model_critic_zone_locator_mismatch_is_advisory(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.ADULT_STANDARD, "Linh chuyển khỏi căn nhà cũ.",
            confirm_duration(Profile.ADULT_STANDARD, 20), "vi",
        )
        result = Stage1Validator._quality(
            story, Profile.ADULT_STANDARD, "Linh chuyển khỏi căn nhà cũ.",
            {
                "status": "FAIL", "method": "MODEL_STORY_CRITIC_V2",
                "findings": [{
                    "zone": "CLIMAX", "locator": "script[5].text",
                    "category": "CONTINUITY", "blocking": True,
                    "issue": "Missing concrete prop or location in CLIMAX.",
                    "instruction": "Add moving boxes.",
                }],
                "evidence_locators": ["script[5].text"],
            },
        )
        self.assertEqual(result.metrics["model_critic"]["credible_finding_count"], 0)
        self.assertEqual(result.status, "PASS")

    def test_model_critic_missing_quoted_evidence_is_stale_when_present(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE, "Minh tìm chiếc diều.",
            confirm_duration(Profile.YOUTH_SAFE, 5), "vi",
        )
        story["script"][1]["text"] += " Minh nhìn thấy chiếc diều bị gió cuốn bay."
        result = Stage1Validator._quality(
            story, Profile.YOUTH_SAFE, "Minh tìm chiếc diều.",
            {
                "status": "FAIL", "method": "MODEL_STORY_CRITIC_V2",
                "findings": [{
                    "zone": "OPENING", "locator": "script[1].text",
                    "category": "STRUCTURE", "blocking": True,
                    "issue": "Missing required prop 'chiếc diều bị gió cuốn bay'.",
                    "instruction": "Add the kite.",
                }],
                "evidence_locators": ["script[1].text"],
            },
        )
        self.assertEqual(result.metrics["model_critic"]["credible_finding_count"], 0)
        self.assertEqual(result.status, "PASS")

    def test_model_critic_keyword_only_finding_is_not_blocking(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE,
            "Hoa tìm lại chiếc chuông gió trong khu vườn.",
            confirm_duration(Profile.YOUTH_SAFE, 5),
            "vi",
        )
        result = Stage1Validator._quality(
            story,
            Profile.YOUTH_SAFE,
            "Hoa tìm lại chiếc chuông gió trong khu vườn.",
            {
                "status": "FAIL", "method": "MODEL_STORY_CRITIC_V2",
                "finding_count": 1,
                "findings": [{
                    "zone": "OPENING",
                    "issue": "Missing required term 'suốt' in opening description.",
                    "instruction": "Include the exact word suốt.",
                }],
                "evidence_locators": ["script[1].text"],
            },
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.metrics["model_critic"]["credible_finding_count"], 0)
        self.assertEqual(result.metrics["model_critic"]["rejected_finding_count"], 1)

    def test_model_critic_missing_dialogue_is_rejected_when_zone_has_dialogue(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.ADULT_STANDARD,
            "Đức hoàn thành thủ tục cuối cùng.",
            confirm_duration(Profile.ADULT_STANDARD, 20),
            "vi",
        )
        story["script"][4]["text"] += ' Đức nói: "Tôi sẽ hoàn thành bước cuối."'
        result = Stage1Validator._quality(
            story,
            Profile.ADULT_STANDARD,
            "Đức hoàn thành thủ tục cuối cùng.",
            {
                "status": "FAIL", "method": "MODEL_STORY_CRITIC_V2",
                "finding_count": 1,
                "findings": [{
                    "zone": "CLIMAX", "issue": "Missing required dialogue turn.",
                    "instruction": "Add dialogue about the final step.",
                }],
                "evidence_locators": ["script[4].text"],
            },
        )

        self.assertFalse(any(
            finding.get("error") == "MODEL_CRITIC_FINDINGS_REMAIN"
            for finding in result.findings
        ))

    def test_model_critic_missing_state_change_is_rejected_when_transition_exists(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE, "Minh ghi chép về đom đóm.",
            confirm_duration(Profile.YOUTH_SAFE, 5), "vi",
        )
        story["script"][3]["text"] += " Sau đó Minh quyết định ghi lại chi tiết mới."
        result = Stage1Validator._quality(
            story, Profile.YOUTH_SAFE, "Minh ghi chép về đom đóm.",
            {
                "status": "FAIL", "method": "MODEL_STORY_CRITIC_V2",
                "findings": [{
                    "zone": "DEVELOPMENT", "locator": "script[3].text",
                    "category": "STRUCTURE", "blocking": True,
                    "issue": "Missing required state change.",
                    "instruction": "Add a transition showing Minh's decision.",
                }],
                "evidence_locators": ["script[3].text"],
            },
        )
        self.assertFalse(any(
            finding.get("error") == "MODEL_CRITIC_FINDINGS_REMAIN"
            for finding in result.findings
        ))

    def test_quality_rubric_recognizes_vietnamese_climax_and_payoff_language(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE,
            "Mai và Bảo cùng biến khu vườn gia đình thành nơi đẹp nhất thị trấn.",
            confirm_duration(Profile.YOUTH_SAFE, 5),
            "vi",
        )
        story["script"][4]["text"] = (
            "Mai và Bảo bắt đầu thực hiện ý tưởng. Khu vườn trở nên ổn định. "
            'Mai reo: "Chúng ta làm được rồi!"'
        )
        story["script"][6]["text"] = (
            "Mai tự hào và hài lòng với khu vườn. Cô mỉm cười vì mình đã thành công."
        )
        result = Stage1Validator._quality(
            story,
            Profile.YOUTH_SAFE,
            "Mai và Bảo cùng biến khu vườn gia đình thành nơi đẹp nhất thị trấn.",
        )
        self.assertGreaterEqual(result.metrics["dimensions"]["climax_and_payoff"]["score"], 60)
        self.assertFalse(any(
            finding.get("dimension") == "climax_and_payoff" for finding in result.findings
        ))

    def test_quality_rubric_recognizes_refusal_keep_and_emotional_payoff(self) -> None:
        story = DeterministicStoryProvider().generate(
            Profile.YOUTH_SAFE,
            "Bo giữ chiếc thuyền giấy bị rách và từ chối thay nó bằng thuyền mới.",
            confirm_duration(Profile.YOUTH_SAFE, 5),
            "vi",
        )
        story["script"][4]["text"] = (
            "Bo từ chối chiếc thuyền thay thế. Bo chọn giữ vết rách, còn Mẹ ôm Bo."
        )
        story["script"][6]["text"] = (
            "Bo và Mẹ mỉm cười. Bo thấy nhẹ nhõm vì biết mọi thứ rồi sẽ ổn."
        )
        result = Stage1Validator._quality(
            story,
            Profile.YOUTH_SAFE,
            "Bo giữ chiếc thuyền giấy bị rách và từ chối thay nó bằng thuyền mới.",
        )
        self.assertGreaterEqual(
            result.metrics["dimensions"]["climax_and_payoff"]["score"], 60
        )

    def test_dialogue_metrics_count_turns_and_attribution(self) -> None:
        story = {
            "characters": [{"name": "Bo"}, {"name": "Mẹ"}],
            "script": [
                {"zone": "CLIMAX", "text": '"Con buồn vì thuyền rách," Bo nói. “Mẹ sẽ ngồi đây,” Mẹ đáp.'},
                {"zone": "ENDING", "text": "Hai mẹ con cùng đọc sách."},
            ],
        }
        gate = Stage1Validator._dialogue_structure(story)
        self.assertEqual(gate.status, "PASS")
        self.assertEqual(gate.metrics["direct_dialogue_turn_count"], 2)
        self.assertEqual(gate.metrics["direct_dialogue_item_count"], 1)
        self.assertEqual(gate.metrics["attributed_dialogue_ratio"], 1.0)

    def test_dialogue_colon_attribution_is_recognized(self) -> None:
        story = {
            "characters": [{"name": "Thanh"}, {"name": "Hùng"}],
            "script": [{
                "zone": "OPENING",
                "text": 'Thanh hào hứng: "Chúng ta bắt đầu nhé!" Hùng gật đầu: "Được rồi."',
            }],
        }
        gate = Stage1Validator._dialogue_structure(story)
        self.assertEqual(gate.metrics["direct_dialogue_turn_count"], 2)
        self.assertEqual(gate.metrics["attributed_dialogue_count"], 2)

    def test_youth_dialogue_gate_requires_six_short_turns(self) -> None:
        story = {
            "characters": [{"name": "An"}, {"name": "Hoa"}],
            "script": [{
                "zone": "DEVELOPMENT",
                "text": '"Mình gọi ông nhé," Hoa nói. “Ừ, cây trơn lắm,” An đáp.',
            }],
        }
        gate = Stage1Validator._dialogue_structure(story, Profile.YOUTH_SAFE)
        self.assertEqual(gate.status, "FAIL")
        self.assertTrue(any(
            finding["error"] == "DIALOGUE_TURN_COUNT_TOO_LOW"
            for finding in gate.findings
        ))
    def test_duration_must_be_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = RunWorkspace.create(Path(temporary), Profile.YOUTH_SAFE, "run-stage1-wait")
            request = Stage1Request(Profile.YOUTH_SAFE, "Một tình bạn", suggested_duration(Profile.YOUTH_SAFE))
            with self.assertRaises(WorkflowError):
                Stage1Pipeline().run(request, workspace)

    def test_local_generation_rejects_thin_brief_before_model_call(self) -> None:
        class ThinBriefLocalProvider(DeterministicStoryProvider):
            provider_id = "local-story-provider/test"

            def generate(self, *args, **kwargs):
                raise AssertionError("model must not be called for an overlong thin brief")

        pipeline = Stage1Pipeline(
            story_provider=ThinBriefLocalProvider(),
            image_provider=DeterministicCharacterImageProvider(),
            safety_provider=RuleBasedSafetyProvider(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            workspace = RunWorkspace.create(Path(temporary), Profile.YOUTH_SAFE, "run-thin-brief")
            with self.assertRaisesRegex(WorkflowError, "too thin"):
                pipeline.run(
                    Stage1Request(
                        Profile.YOUTH_SAFE,
                        "Hai người bạn bảo vệ khu vườn.",
                        confirm_duration(Profile.YOUTH_SAFE, 15),
                    ),
                    workspace,
                )

    def test_youth_stage1_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = RunWorkspace.create(Path(temporary), Profile.YOUTH_SAFE, "run-stage1-youth")
            result = Stage1Pipeline().run(
                Stage1Request(
                    Profile.YOUTH_SAFE,
                    "Hai người bạn giữ lời hứa bảo vệ khu vườn sau cơn mưa",
                    confirm_duration(Profile.YOUTH_SAFE, 15),
                ),
                workspace,
            )
            package = Path(result.package.archive_path)
            verified = PackageVerifier().verify(package)
            self.assertEqual(verified.package_stage, "STAGE1")
            self.assertEqual(result.repair_rounds, 0)
            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
                self.assertIn("characters/an.png", names)
                self.assertIn("characters/minh.png", names)
                self.assertIn("story_contract.json", names)
                self.assertIn("outline_evidence.json", names)
                self.assertIn("quality_decision.json", names)
                story_bytes = archive.read("story.json")
                story = json.loads(story_bytes)
                contract = json.loads(archive.read("story_contract.json"))
                outline_evidence = json.loads(archive.read("outline_evidence.json"))
                quality_decision = json.loads(archive.read("quality_decision.json"))
                validation_ledger = json.loads(archive.read("validation_ledger.json"))
                report = json.loads(archive.read("story_validation.json"))
                manifest = json.loads(archive.read("workflow_manifest.json"))
            self.assertEqual(list(story), ["schema_version", "meta", "characters", "outline", "script"])
            self.assertEqual(contract["schema_version"], "1.0")
            self.assertEqual(outline_evidence["story_contract_digest_sha256"], hashlib.sha256(
                json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest())
            self.assertEqual(quality_decision["editorial_status"], "NOT_ASSESSED")
            self.assertEqual(quality_decision["advancement_status"], "ALLOWED")
            self.assertEqual(quality_decision["continuation_policy"], "CONTINUE_WITH_WARNINGS")
            self.assertEqual(len(report), 15)
            self.assertEqual(report["quality"]["editorial_status"], "NOT_ASSESSED_FIXTURE")
            self.assertTrue(all(gate["status"] == "PASS" for gate in report["gates"]))
            failed = {gate["gate_id"] for gate in report["gates"] if gate["status"] == "FAIL"}
            self.assertNotIn("CHARACTER_REFERENCE_SET_GATE", failed)
            self.assertNotIn("INTRA_ZONE_REPETITION_GATE", failed)
            self.assertEqual(report["story_sha256"], hashlib.sha256(story_bytes).hexdigest())
            self.assertEqual(manifest["schema_version"], "1.1")
            self.assertEqual(manifest["generation"]["provider_mode"], "deterministic")
            self.assertEqual(manifest["allowed_next_stage"], "STAGE2")
            self.assertEqual(manifest["validation"]["execution_status"], "SUCCEEDED")
            self.assertEqual(manifest["validation"]["integrity_status"], "PASS")
            self.assertEqual(manifest["validation"]["content_quality_status"], "NOT_ASSESSED")
            self.assertEqual(manifest["validation"]["artifact_class"], "TEST_FIXTURE")
            self.assertEqual(validation_ledger["current_stage"], "STAGE1")
            self.assertEqual(
                manifest["validation"]["validation_ledger_digest_sha256"],
                validation_ledger["ledger_digest_sha256"],
            )
            self.assertEqual(
                manifest["validation"]["open_warning_count"],
                validation_ledger["summary"]["open_warning_count"],
            )
            runtime_metrics = manifest["generation"]["runtime_metrics"]
            self.assertGreaterEqual(runtime_metrics["call_count"], 4)
            self.assertGreaterEqual(
                runtime_metrics["attempt_count"],
                runtime_metrics["call_count"] + runtime_metrics["retry_count"],
            )
            self.assertGreater(runtime_metrics["duration_ms"], 0)
            self.assertGreater(runtime_metrics["wall_clock_duration_ms"], 0)
            self.assertGreater(
                manifest["generation"]["operational_metrics"]["duration_seconds"], 0
            )
            self.assertEqual(report["refinement"]["refinement_status"], "NOT_REQUIRED")
            self.assertTrue(all(
                character["reference_asset"]["validation_status"] == "PASS"
                for character in story["characters"]
            ))
            self.assertEqual(
                story["meta"]["story_quality_commitment"]["committed_quality_metrics"]["engagement_score"],
                report["engagement"]["engagement_score"],
            )
            self.assertIsNone(report["quality"]["final_story_quality_score"])
            self.assertGreaterEqual(report["quality"]["preflight_story_quality_score"], 80)
            self.assertIsNone(
                story["meta"]["story_quality_commitment"]["committed_quality_metrics"]["quality_score"]
            )
            self.assertEqual(report["quality"]["scoring_method"], "WEIGHTED_EDITORIAL_RUBRIC_V2")
            self.assertIn("evidence_locators", report["quality"]["dimensions"]["brief_adherence"])
            self.assertEqual(
                sum(item["weight"] for item in report["quality"]["dimensions"].values()),
                100,
            )
            quality_gate = next(gate for gate in report["gates"] if gate["gate_id"] == "STORY_QUALITY_GATE")
            self.assertEqual(quality_gate["metrics"]["minimum_dimension_score"], 60)
            self.assertEqual(quality_gate["metrics"]["assessment_basis"], "DETERMINISTIC_PREFLIGHT_ONLY")
            self.assertEqual(
                {item["role"] for item in manifest["generation"]["providers"]},
                {"story", "character_image", "safety"},
            )
            run_metadata = json.loads((workspace.root / "run.json").read_text(encoding="utf-8"))
            telemetry = run_metadata["telemetry_reconciliation"]
            self.assertEqual(telemetry["status"], "PASS")
            self.assertLessEqual(
                telemetry["deviation_percent"], telemetry["maximum_deviation_percent"]
            )
            events = [
                json.loads(line)
                for line in (workspace.logs_dir / "events.ndjson").read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(any(
                event["event"] == "STAGE1_TELEMETRY_RECONCILED"
                for event in events
            ))

    def test_reduced_minimum_duration_bounds(self) -> None:
        cases = (
            (Profile.YOUTH_SAFE, 5, None),
            (Profile.ADULT_STANDARD, 10, None),
            (Profile.SERIAL_DETECTIVE, 15, "START_SERIES"),
            (Profile.SERIAL_DETECTIVE, 12, "CONTINUE_SERIES"),
            (Profile.SERIAL_DETECTIVE, 18, "FINALIZE_SERIES"),
        )
        for profile, minimum, mode in cases:
            with self.subTest(profile=profile.value, mode=mode):
                plan = confirm_duration(profile, minimum, mode)
                self.assertEqual(plan.length_min, minimum)
                self.assertEqual(plan.length_target, minimum)
                with self.assertRaises(WorkflowError):
                    confirm_duration(profile, minimum - 1, mode)

    def test_editorial_integrity_detects_unseeded_helper_weak_climax_and_told_emotion(self) -> None:
        story = {
            "characters": [{"name": "Hào"}, {"name": "Bác Tư"}],
            "outline": {
                "climax": (
                    "trạng thái đổi từ Hào gặp khó khăn khi trời mưa nặng hạt "
                    "thành Hào bị mưa nặng hạt."
                ),
            },
            "script": [
                {"zone": "GREETING", "text": "Hào nhìn ra biển."},
                {"zone": "OPENING", "text": "Hào cảm thấy lo lắng."},
                {"zone": "INTRODUCTION", "text": "Hào cảm thấy hy vọng."},
                {"zone": "DEVELOPMENT", "text": "Hào cảm thấy lạnh."},
                {"zone": "CLIMAX", "text": "Hào cảm thấy sợ hãi."},
                {"zone": "FALLING", "text": "Bác Tư xuất hiện. Hào cảm thấy nhẹ nhõm."},
                {"zone": "ENDING", "text": "Cả hai về nhà."},
            ],
        }

        gate = Stage1Validator._editorial_integrity(story, Profile.YOUTH_SAFE)

        errors = {finding["error"] for finding in gate.findings}
        self.assertEqual(gate.status, "FAIL")
        self.assertIn("LATE_UNSEEDED_SUPPORTING_CHARACTER", errors)
        self.assertIn("CLIMAX_STATE_DELTA_TOO_WEAK", errors)
        self.assertIn("EXCESSIVE_TOLD_EMOTION", errors)

    def test_youth_safety_rejects_minor_directly_feeding_injured_animal(self) -> None:
        story = {
            "characters": [{
                "name": "Hào", "canonical_age_min": 11, "canonical_age_max": 11,
            }],
            "script": [{
                "zone": "ENDING",
                "text": "Hào đặt thức ăn và nước thẳng vào mỏ con chim bị thương.",
            }],
        }

        gate = Stage1Validator._youth_context_safety(story, Profile.YOUTH_SAFE)

        self.assertTrue(any(
            finding["error"] == "MINOR_DIRECT_ANIMAL_TREATMENT_WITHOUT_PROFESSIONAL_HELP"
            for finding in gate.findings
        ))


if __name__ == "__main__":
    unittest.main()
