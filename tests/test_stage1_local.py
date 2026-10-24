from __future__ import annotations

import re
import unittest

from ai_story.errors import RuntimeUnavailableError
from ai_story.models import Profile
from ai_story.stage1.config import confirm_duration
from ai_story.stage1.contract import build_outline_evidence
from ai_story.stage1.local_providers import (
    LocalCharacterImageProvider,
    LocalSafetyProvider,
    LocalStoryProvider,
)
from ai_story.stage1.validation import Stage1Validator


class FakeRegistry:
    def __init__(self) -> None:
        self.calls = []

    def binding(self, role):
        return {"model_id": "fake-local"}

    def generate_json(self, role, request, cancellation=None):
        self.calls.append((role, request))
        if "TASK: PLAN" in request.prompt:
            return {
                "title": "Khu Vườn Sau Mưa",
                "genre": "phiêu lưu",
                "tone": ["ấm áp"],
                "tags": ["tình bạn"],
                "characters": [
                    {
                        "name": "An",
                        "role": "nhân vật chính",
                        "age": 12,
                        "importance": "PRIMARY",
                        "identity_traits": ["tóc đen", "áo xanh"],
                        "visual_identity": {"presentation": "ANDROGYNOUS", "hair": "tóc đen", "wardrobe": "áo xanh", "palette": ["blue"], "silhouette": "nhỏ gọn", "cultural_context": "Việt Nam đương đại"},
                    }
                ],
                "outline": {
                    "greeting": "Lời chào.",
                    "opening": "Một dấu hiệu xuất hiện.",
                    "introduction": "An nhận nhiệm vụ.",
                    "development": "Thử thách tăng dần.",
                    "climax": "An lựa chọn.",
                    "falling": "Hậu quả lắng xuống.",
                    "ending": "Lời hứa được giữ.",
                    "farewell": "Tạm biệt.",
                },
            }
        if "TASK: WRITE_ZONE" in request.prompt:
            return {
                "environment": "garden_morning",
                "voice": "NARRATOR",
                "speed": "NORMAL",
                "text": "An quan sát khu vườn và đưa ra một lựa chọn rõ ràng.",
            }
        if "TASK: EXTEND_ZONE" in request.prompt:
            return {
                "environment": "garden_morning",
                "voice": "NARRATOR",
                "speed": "NORMAL",
                "text": " ".join(["Câu chuyện tiếp diễn rõ ràng."] * 100),
            }
        if "TASK: CRITIC" in request.prompt:
            return {"findings": [], "evidence_locators": ["script[1].text", "script[4].text", "script[6].text"]}
        if "TASK: SAFETY_ASSESSMENT" in request.prompt:
            return {"status": "PASS", "findings": []}
        if "TASK: LANGUAGE_AND_PUNCTUATION_CLEANUP" in request.prompt:
            return {
                "environment": "sea_wind_soft", "voice": "NARRATOR", "speed": "NORMAL",
                "text": 'Hào đặt mảnh cuối cùng vào bản đồ rồi reo lên: "Đây là đường ra!"',
            }
        raise AssertionError(request.prompt[:80])


class LocalStage1ProviderTests(unittest.TestCase):
    def test_surface_cleanup_removes_dangling_vietnamese_from(self) -> None:
        cleaned = LocalStoryProvider._deterministic_surface_cleanup(
            "Minh lần theo dấu phấn bắt đầu từ.", "vi"
        )

        self.assertEqual(cleaned, "Minh lần theo dấu phấn bắt đầu.")

    def test_surface_cleanup_removes_stray_escapes_and_restores_sentence_spacing(self) -> None:
        cleaned = LocalStoryProvider._deterministic_surface_cleanup(
            '\\Hào chạy tới cửa nhà.Cậu gọi Bác Tư."Hãy giúp cháu!"', "vi"
        )

        self.assertEqual(
            cleaned,
            'Hào chạy tới cửa nhà. Cậu gọi Bác Tư. "Hãy giúp cháu!"',
        )

    def test_deterministic_repair_removes_conflicting_leading_speaker(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        provider._context = {"language": "vi"}
        story = {
            "characters": [{"name": "Hào"}, {"name": "Bác Tư"}],
            "script": [{
                "zone": "FALLING",
                "text": 'Bác Tư nói: "Bác Tư ơi, bác giúp con được không?" Hào hỏi.',
            }],
        }

        repaired = provider.deterministic_repair(story, [{
            "gate_id": "DIALOGUE_STRUCTURE_GATE",
            "error": "CONFLICTING_DIALOGUE_ATTRIBUTION",
            "locator": "script[0].text",
            "turn_index": 0,
            "prefix_speaker": "bác tư",
            "suffix_speaker": "hào",
        }])

        self.assertEqual(
            repaired["script"][0]["text"],
            '"Bác Tư ơi, bác giúp con được không?" Hào hỏi.',
        )

    def test_deterministic_repair_aligns_conflicting_destination_to_state_plan(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        provider._context = {"language": "vi"}
        story = {
            "characters": [{"name": "Hào"}],
            "script": [{
                "zone": "OPENING",
                "text": "Hào quyết định đi đến phòng khám thú y. Trời bắt đầu tối.",
            }],
        }

        repaired = provider.deterministic_repair(story, [{
            "gate_id": "SCENE_STATE_CONTINUITY_GATE",
            "error": "SCENE_DESTINATION_CONFLICT",
            "locator": "script[0].text#sentence[0]",
            "expected_destination": "nhà",
        }])

        self.assertIn("tiếp tục đến nhà theo kế hoạch", repaired["script"][0]["text"])
        self.assertNotIn("phòng khám", repaired["script"][0]["text"])

    def test_content_integrity_repair_converges_after_sentence_indexes_shift(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        provider._context = {"language": "vi"}
        story = {
            "characters": [
                {"name": "Hào", "canonical_age_min": 11, "canonical_age_max": 11},
                {"name": "Bác Tư", "canonical_age_min": 45, "canonical_age_max": 45},
            ],
            "outline": {
                "climax": (
                    "trạng thái đổi từ Hào gặp khó khăn khi trời mưa nặng hạt "
                    "thành Hào bị mưa nặng hạt."
                ),
                "opening": (
                    "trạng thái đổi từ Hào thấy chim bị thương "
                    "thành Hào di chuyển về nhà."
                ),
            },
            "script": [
                {"zone": "GREETING", "text": "Hào nhìn ra biển."},
                {"zone": "OPENING", "text": (
                    "Hào quyết định đi đến phòng khám thú y. Hào nhìn con chim. "
                    "Hào quyết định đi đến phòng khám thú y."
                )},
                {"zone": "INTRODUCTION", "text": "Hào cảm thấy lo lắng."},
                {"zone": "DEVELOPMENT", "text": "Hào cảm thấy lạnh."},
                {"zone": "CLIMAX", "text": "Hào cảm thấy sợ hãi."},
                {"zone": "FALLING", "text": (
                    'Bác Tư nói: "Bác Tư ơi, bác giúp con được không?" Hào hỏi. '
                    "Hào cảm thấy nhẹ nhõm."
                )},
                {"zone": "ENDING", "text": (
                    "Hào đặt thức ăn và nước thẳng vào mỏ con chim. "
                    "Hào cảm thấy vui."
                )},
            ],
        }

        repaired = provider.repair_content_integrity(story, Profile.YOUTH_SAFE)

        gates = (
            Stage1Validator._semantic_repetition(repaired),
            Stage1Validator._dialogue_structure(repaired),
            Stage1Validator._scene_state_continuity(repaired),
            Stage1Validator._editorial_integrity(repaired, Profile.YOUTH_SAFE),
            Stage1Validator._youth_context_safety(repaired, Profile.YOUTH_SAFE),
        )
        self.assertTrue(
            all(gate.status == "PASS" for gate in gates),
            [(gate.gate_id, gate.findings) for gate in gates],
        )

    def test_sentence_repair_balances_quote_and_removes_located_dangling_tail(self) -> None:
        text = 'Minh nói: "Ta đi thôi. Lan đứng yên trong.'
        findings = [
            {"locator": "script[0].text", "error": "UNCLOSED_QUOTE"},
            {"locator": "script[0].text#sentence[1]", "error": "DANGLING_CLAUSE_END"},
        ]

        repaired = LocalStoryProvider._repair_sentence_defects(text, findings, "vi")

        self.assertEqual(repaired.count('"') % 2, 0)
        self.assertNotIn(" yên trong.", repaired)
        self.assertTrue(repaired.endswith("."))

    def test_post_repair_finalizer_removes_repeat_and_premature_outcome(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        provider._context = {
            "language": "vi",
            "duration": None,
            "system": "system",
        }
        repeated = "Minh đặt lá thư cũ lên bàn rồi nhìn Lan trong im lặng."
        story = {
            "outline": {"falling": "Minh còn cân nhắc.", "farewell": "Minh rời đi nhẹ nhõm."},
            "script": [
                {"zone": "OPENING", "text": repeated},
                {"zone": "FALLING", "text": f"{repeated} Minh rời đi và cảm thấy nhẹ nhõm."},
                {"zone": "FAREWELL", "text": "Minh rời đi nhẹ nhõm."},
            ],
        }
        findings = [
            {
                "error": "CROSS_ZONE_SEMANTIC_REPETITION", "locator": "script[1].text",
                "target_sentence": 0,
            },
            {
                "error": "PREMATURE_SCENE_OUTCOME", "locator": "script[1].text",
                "outcome": "Minh rời đi cảm thấy nhẹ nhõm", "expected_zone": "FAREWELL",
            },
        ]

        repaired = provider.finalize_after_repair(story, findings)

        self.assertNotIn(repeated, repaired["script"][1]["text"])
        self.assertNotIn("rời đi", repaired["script"][1]["text"])

    def test_post_repair_finalizer_expands_under_budget_story(self) -> None:
        class ExpansionRegistry(FakeRegistry):
            def generate_json(self, role, request, cancellation=None):
                self.calls.append((role, request))
                if "TASK: POST_REPAIR_EXPANSION" in request.prompt:
                    return {"text": " ".join(
                        ["Chi tiết mới làm cảnh tiến triển rõ ràng"] * 60
                    ) + "."}
                return super().generate_json(role, request, cancellation)

        registry = ExpansionRegistry()
        provider = LocalStoryProvider(registry)
        provider._context = {
            "language": "vi",
            "duration": confirm_duration(Profile.YOUTH_SAFE, 5),
            "system": "system",
        }
        story = {
            "outline": {zone.lower(): f"Beat {zone}" for zone in (
                "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
                "CLIMAX", "FALLING", "ENDING", "FAREWELL",
            )},
            "script": [
                {"zone": zone, "text": "Một cảnh ngắn kết thúc rõ ràng."}
                for zone in (
                    "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
                    "CLIMAX", "FALLING", "ENDING", "FAREWELL",
                )
            ],
        }

        repaired = provider.finalize_after_repair(story, [])

        total = sum(len(item["text"].split()) for item in repaired["script"])
        self.assertGreater(total, 500)
        self.assertTrue(any(
            "TASK: POST_REPAIR_EXPANSION" in request.prompt
            for _, request in registry.calls
        ))

    def test_post_repair_novelty_rejects_semantic_copy(self) -> None:
        story = {"script": [{
            "zone": "OPENING",
            "text": "Minh mở cánh cửa gỗ rồi bước chậm vào căn phòng tối.",
        }]}

        self.assertFalse(LocalStoryProvider._addition_is_novel(
            story, "Minh mở cửa gỗ và chậm rãi bước vào căn phòng tối."
        ))

    def test_post_repair_caps_bookends_at_complete_sentence(self) -> None:
        story = {"script": [{
            "zone": "GREETING",
            "text": (
                "Xin chào các bạn đến với câu chuyện hôm nay. "
                + " ".join(["Lời giới thiệu kéo dài không cần thiết"] * 12)
                + "."
            ),
        }]}

        LocalStoryProvider._cap_bookends(story)

        self.assertLessEqual(len(story["script"][0]["text"].split()), 50)
        self.assertTrue(story["script"][0]["text"].endswith("."))

    def test_deterministic_repair_handles_bookend_and_semantic_locator(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        provider._context = {"language": "vi"}
        repeated = "Minh đặt chiếc hộp lên bàn rồi nhìn Lan trong im lặng."
        story = {"script": [
            {"zone": "GREETING", "text": " ".join(["lời chào dài"] * 30)},
            {"zone": "OPENING", "text": repeated},
            {"zone": "ENDING", "text": repeated},
        ]}

        repaired = provider.deterministic_repair(story, [{
            "gate_id": "SEMANTIC_REPETITION_GATE",
            "error": "CROSS_ZONE_SEMANTIC_REPETITION",
            "locator": "script[2].text",
            "target_sentence": 0,
        }])

        self.assertLessEqual(len(repaired["script"][0]["text"].split()), 50)
        self.assertNotEqual(repaired["script"][2]["text"], repeated)

    def test_deterministic_repair_balances_quote_after_bookend_trim(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        provider._context = {"language": "vi"}
        story = {"script": [{
            "zone": "FAREWELL",
            "text": 'Lan nói: "Cảm ơn bạn đã nghe. ' + " ".join(["lời chào"] * 60),
        }]}

        repaired = provider.deterministic_repair(story, [{
            "gate_id": "ZONE_BUDGET_GATE",
            "error": "BOOKEND_TOO_LONG",
            "locator": "script[0].text",
        }])

        text = repaired["script"][0]["text"]
        self.assertLessEqual(len(text.split()), 50)
        self.assertEqual(text.count('"') % 2, 0)

    def test_deterministic_repair_does_not_hide_underfill_with_generic_filler(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        duration = confirm_duration(Profile.YOUTH_SAFE, 5)
        provider._context = {"language": "vi", "duration": duration}
        repeated = "Nam và Hoa cùng kiểm tra dụng cụ rồi ghi lại kết quả mới."
        filler = "Hai bạn kiểm tra từng bước thật cẩn thận."
        filler_count = (
            round(duration.target_words * 0.95) - 2 * len(repeated.split())
        ) // len(filler.split())
        story = {
            "outline": {"development": {
                "actor": "Nam và Hoa", "prop": "bình thí nghiệm", "location": "câu lạc bộ",
            }},
            "script": [
                {"zone": "OPENING", "text": repeated},
                {"zone": "DEVELOPMENT", "text": (
                    " ".join([filler] * filler_count)
                    + " " + repeated
                )},
            ],
        }
        finding = {
            "gate_id": "SEMANTIC_REPETITION_GATE",
            "error": "CROSS_ZONE_SEMANTIC_REPETITION",
            "locator": "script[1].text",
            "target_sentence": filler_count,
        }

        repaired = provider.deterministic_repair(story, [finding])

        total = sum(len(item["text"].split()) for item in repaired["script"])
        self.assertLess(total, round(duration.target_words * 0.95))
        self.assertNotIn("ghi chú và dụng cụ", repaired["script"][1]["text"])

    def test_deterministic_repair_varies_dense_attributions_without_losing_dialogue(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        text = " ".join(
            f'Lan nói: "Câu trả lời số {index}."' for index in range(1, 9)
        )
        story = {"script": [{"zone": "DEVELOPMENT", "text": text}]}

        repaired = provider.deterministic_repair(story, [{
            "gate_id": "PROSE_HYGIENE_GATE",
            "error": "ATTRIBUTION_TEMPLATE_DENSITY",
            "locator": "script[0].text",
        }])

        repaired_text = repaired["script"][0]["text"]
        self.assertEqual(repaired_text.count('"'), text.count('"'))
        self.assertEqual(repaired_text.count("Lan nói:"), 2)
        self.assertIn("Lan đáp:", repaired_text)

    def test_deterministic_repair_varies_all_dense_attribution_punctuation(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        text = " ".join(
            f'Lan nói rằng câu {index} đã rõ.' if index % 2 else f'Lan nói, "Câu {index} đã rõ."'
            for index in range(1, 9)
        )
        story = {"script": [{"zone": "DEVELOPMENT", "text": text}]}

        repaired = provider.deterministic_repair(story, [{
            "gate_id": "PROSE_HYGIENE_GATE",
            "error": "ATTRIBUTION_TEMPLATE_DENSITY",
            "locator": "script[0].text",
        }])

        self.assertEqual(len(re.findall(r"\bLan nói\b", repaired["script"][0]["text"])), 2)

    def test_deterministic_repair_removes_multiple_repetitions_from_end_first(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        story = {"script": [{"zone": "DEVELOPMENT", "text": "Một. Hai. Ba. Bốn."}]}
        findings = [
            {"error": "CROSS_ZONE_SEMANTIC_REPETITION", "locator": "script[0].text", "target_sentence": 1},
            {"error": "CROSS_ZONE_SEMANTIC_REPETITION", "locator": "script[0].text", "target_sentence": 3},
        ]

        repaired = provider.deterministic_repair(story, findings)

        self.assertEqual(repaired["script"][0]["text"], "Một. Ba.")

    def test_deterministic_repair_replaces_repetition_when_contract_beat_is_available(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        provider._active_contract = {"zone_beats": {"development": {
            "actor": "Hà", "action": "treo chiếc chuông gió",
            "prop": "chiếc móc đồng", "location": "bên cửa sổ",
        }}}
        story = {"script": [{
            "zone": "DEVELOPMENT", "environment": "home_day",
            "text": "Hà nhìn chiếc chuông. Hà nhìn chiếc chuông.",
        }]}
        repaired = provider.deterministic_repair(story, [{
            "error": "CROSS_ZONE_SEMANTIC_REPETITION",
            "locator": "script[0].text", "target_sentence": 1,
        }])
        self.assertIn("chiếc móc đồng", repaired["script"][0]["text"])
        self.assertEqual(repaired["script"][0]["text"].count("Hà nhìn chiếc chuông"), 1)

    def test_deterministic_repair_replaces_generic_filler_with_current_beat(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        provider._context = {"language": "vi"}
        story = {
            "characters": [{"name": "Linh"}],
            "outline": {"development": {
                "actor": "Linh", "action": "mở chiếc hộp ký ức",
                "prop": "tấm ảnh cũ", "location": "căn gác",
            }},
            "script": [{
                "zone": "DEVELOPMENT",
                "text": "Cả nhóm bình tĩnh kiểm tra mọi việc lần cuối.",
            }],
        }
        repaired = provider.deterministic_repair(story, [{
            "gate_id": "PROSE_HYGIENE_GATE", "error": "GENERIC_REPAIR_FILLER",
            "locator": "script[0].text#sentence[0]",
        }])
        text = repaired["script"][0]["text"]
        self.assertNotIn("kiểm tra mọi việc lần cuối", text)
        self.assertIn("vật chứng", text)

    def test_deterministic_repair_changes_only_unquoted_narrative_person(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        story = {
            "characters": [{"name": "Bình", "role": "Protagonist"}],
            "script": [{
                "zone": "DEVELOPMENT",
                "text": 'Tôi bước tới chiếc radio. Bình nói: "Tôi vẫn nhớ âm thanh ấy."',
            }],
        }
        repaired = provider.deterministic_repair(story, [{
            "gate_id": "NARRATIVE_VOICE_GATE",
            "error": "NARRATIVE_PERSON_SHIFT",
            "locator": "script[0].text",
        }])
        text = repaired["script"][0]["text"]
        self.assertTrue(text.startswith("Bình bước tới"))
        self.assertIn('"Tôi vẫn nhớ âm thanh ấy."', text)

    def test_filter_novel_addition_keeps_only_new_complete_sentences(self) -> None:
        story = {"script": [{"text": "Lan mở chiếc hộp gỗ cạnh cửa sổ."}]}
        addition = (
            "Lan mở chiếc hộp gỗ cạnh cửa sổ. "
            "Bên dưới lớp vải, cô tìm thấy một tấm ảnh chưa từng thấy."
        )
        filtered = LocalStoryProvider._filter_novel_addition(story, addition)
        self.assertNotIn("Lan mở chiếc hộp", filtered)
        self.assertIn("tấm ảnh", filtered)

    def test_post_repair_replaces_bookend_without_early_sentence_boundary(self) -> None:
        story = {
            "meta": {"title": "Ngọn đèn", "author": "An"},
            "script": [{
                "zone": "GREETING",
                "text": " ".join(["lời giới thiệu kéo dài"] * 30),
            }],
        }

        LocalStoryProvider._cap_bookends(story, "vi")

        self.assertLessEqual(len(story["script"][0]["text"].split()), 50)
        self.assertEqual(story["script"][0]["text"], 'Xin chào. Mời bạn nghe truyện "Ngọn đèn" của An.')

    def test_surface_cleanup_rewrites_only_located_zone_in_vietnamese(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        provider._context = {
            "language": "vi",
            "duration": confirm_duration(Profile.YOUTH_SAFE, 5),
        }
        story = {"script": [
            {"zone": "GREETING", "text": "Chào các bạn!"},
            {"zone": "OPENING", "text": 'Hào said: "This could be our way out!'},
        ]}
        repaired = provider.sanitize_surface_defects(
            story,
            [{"locator": "script[1].text", "error": "UNEXPECTED_LANGUAGE_TOKENS"}],
        )
        self.assertEqual(repaired["script"][0]["text"], "Chào các bạn!")
        self.assertEqual(
            repaired["script"][1]["text"],
            'Hào đặt mảnh cuối cùng vào bản đồ rồi reo lên: "Đây là đường ra!"',
        )
        self.assertIn(
            "Tuyệt đối không dùng chữ Hán",
            provider.registry.calls[-1][1].system_prompt,
        )
        self.assertIn("ORIGINAL_WORDS=", provider.registry.calls[-1][1].prompt)

    def test_surface_cleanup_keeps_deterministic_fallback_when_runtime_fails(self) -> None:
        class FailingCleanupRegistry(FakeRegistry):
            def generate_json(self, role, request, cancellation=None):
                self.calls.append((role, request))
                raise RuntimeUnavailableError("invalid JSON: finish_reason='length'")

        provider = LocalStoryProvider(FailingCleanupRegistry())
        provider._context = {"language": "vi", "duration": None}
        story = {"script": [{
            "zone": "CLIMAX",
            "text": 'Minh said: "We found the kite and can fly it now!"',
        }]}

        repaired = provider.sanitize_surface_defects(
            story,
            [{"locator": "script[0].text", "error": "UNEXPECTED_LANGUAGE_TOKENS"}],
        )

        self.assertEqual(
            repaired["script"][0]["text"],
            'Minh said: "We found the kite and can fly it now!"',
        )
        self.assertEqual(len(provider.registry.calls), 1)

    def test_surface_candidate_score_rejects_han_and_incomplete_text(self) -> None:
        clean = 'Hà nói: "Mình đến nơi an toàn rồi."'
        self.assertEqual(LocalStoryProvider._surface_defect_score(clean, "vi"), 0)
        self.assertGreater(
            LocalStoryProvider._surface_defect_score("Hà đã 安全。", "vi"),
            LocalStoryProvider._surface_defect_score(clean, "vi"),
        )
        self.assertGreater(LocalStoryProvider._surface_defect_score("Hà chạy", "vi"), 0)

    def test_deterministic_surface_cleanup_removes_mixed_han_and_closes_sentences(self) -> None:
        source = (
            'Hoa小心翼i thử đưa tay gần chim non. Hoa nói: "Chim về tổ rồi. " '
            "Hai chị em vui và成就感。"
        )
        cleaned = LocalStoryProvider._deterministic_surface_cleanup(source, "vi")
        self.assertNotRegex(cleaned, r"[\u3400-\u4dbf\u4e00-\u9fff。！？]")
        self.assertIn("Hoa thử đưa tay", cleaned)
        self.assertIn('rồi."', cleaned)
        self.assertTrue(cleaned.endswith("."))
        self.assertEqual(LocalStoryProvider._surface_defect_score(cleaned, "vi"), 0)

    def test_contract_requirement_is_restored_after_targeted_rewrite(self) -> None:
        contract = LocalStoryProvider._story_contract(
            "Một cơn bão đang tới. Hà cùng mẹ bảo vệ ngôi nhà rồi sơ tán an toàn.",
            "vi",
            [
                "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
                "CLIMAX", "FALLING", "ENDING", "FAREWELL",
            ],
            [30, 80, 90, 140, 110, 80, 80, 30],
            Profile.YOUTH_SAFE,
        )
        story = {"script": [
            {"zone": zone, "text": "Hà chuẩn bị cẩn thận."}
            for zone in (
                "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
                "CLIMAX", "FALLING", "ENDING", "FAREWELL",
            )
        ]}
        LocalStoryProvider._ensure_contract_requirements(story, contract)
        outcome_text = " ".join(
            item["text"] for item in story["script"] if item["zone"] in {"FALLING", "ENDING"}
        ).casefold()
        self.assertIn("sơ tán", outcome_text)
        self.assertIn("đến nơi an toàn", outcome_text)

    def test_story_craft_stabilizer_attributes_dialogue_and_removes_rescue_subplot(self) -> None:
        story = {
            "characters": [{"name": "Phương"}, {"name": "An"}],
            "script": [
                {"zone": "OPENING", "text": 'Phương thấy chim non. "Nhìn kìa!"'},
                {"zone": "DEVELOPMENT", "text": '"Mình nhờ mẹ nhé."'},
                {"zone": "CLIMAX", "text": (
                    "Mẹ đặt chim về tổ. Bỗng, một tiếng kêu cứu vang lên từ xa. "
                    "Phương và An chạy về phía cánh đồng."
                )},
            ],
        }
        LocalStoryProvider._stabilize_story_craft(story, Profile.YOUTH_SAFE)
        combined = " ".join(item["text"] for item in story["script"])
        self.assertIn('Phương nói: "Nhìn kìa!"', combined)
        self.assertIn("quyết định tiếp tục", combined)
        self.assertIn("lo vì", combined)
        self.assertNotIn("kêu cứu", combined)
        self.assertNotIn("cánh đồng", combined)

    def test_story_craft_stabilizer_adds_second_agency_signal(self) -> None:
        story = {
            "characters": [{"name": "Phương"}, {"name": "An"}],
            "script": [
                {"zone": "OPENING", "text": "Phương lo khi trời sắp mưa."},
                {"zone": "DEVELOPMENT", "text": "Phương thử gọi mẹ đến giúp."},
                {"zone": "CLIMAX", "text": "Mẹ đưa chim non về tổ."},
            ],
        }
        LocalStoryProvider._stabilize_story_craft(story, Profile.YOUTH_SAFE)
        agency = " ".join(item["text"] for item in story["script"][1:]).casefold()
        self.assertIn("tự quyết định tiếp tục", agency)

    def test_exact_cross_zone_copy_backstop_keeps_first_occurrence(self) -> None:
        repeated = "Tú nhẹ nhàng lật từng trang nhật ký để tìm hiểu dấu hiệu kỳ lạ."
        story = {"script": [
            {"zone": "CLIMAX", "text": f"{repeated} Tú ghi dấu hiệu vào vở."},
            {"zone": "ENDING", "text": f"{repeated} Tú tìm thấy một manh mối mới."},
        ]}

        LocalStoryProvider._remove_exact_cross_zone_copies(story)

        self.assertIn(repeated, story["script"][0]["text"])
        self.assertNotIn(repeated, story["script"][1]["text"])
        self.assertIn("manh mối mới", story["script"][1]["text"])

    def test_exact_copy_backstop_does_not_delete_dialogue_turns(self) -> None:
        repeated = 'Tú nói: "Mình sẽ tiếp tục tìm hiểu cuốn nhật ký cổ này."'
        story = {"script": [
            {"zone": "CLIMAX", "text": repeated},
            {"zone": "ENDING", "text": repeated},
        ]}

        LocalStoryProvider._remove_exact_cross_zone_copies(story)

        self.assertIn('"Mình sẽ tiếp tục', story["script"][1]["text"])

    def test_targeted_repair_prompt_includes_current_zone_and_preservation_rules(self) -> None:
        provider = LocalStoryProvider(FakeRegistry())
        provider._active_profile = Profile.YOUTH_SAFE
        provider._active_contract = {"requirements": []}
        provider._write_zone(
            "system", "ENDING", 80, "vi", {"title": "Nhật ký"},
            [{"name": "Tú"}], {"ending": "Tú tìm thấy manh mối."},
            [{"zone": "CLIMAX", "tail": "Tú đọc dấu hiệu."}],
            '{"findings": [], "current_zone": {"text": "Tú nói: \\"Mình hiểu rồi.\\""}}',
        )
        prompt = next(
            request.prompt for _, request in provider.registry.calls
            if "TASK: WRITE_ZONE" in request.prompt
        )
        self.assertIn("CURRENT_ZONE_DATA", prompt)
        self.assertIn("Preserve its concrete events", prompt)
        self.assertIn("never copy or closely paraphrase", prompt)

    def test_lost_bird_contract_stabilizer_keeps_relationship_and_children_below(self) -> None:
        contract = LocalStoryProvider._story_contract(
            "Hai chị em trả chim non về tổ trước cơn mưa và nhờ người lớn giúp.",
            "vi", ["OPENING", "DEVELOPMENT", "CLIMAX", "ENDING"],
            [100, 150, 150, 100], Profile.YOUTH_SAFE,
        )
        story = {
            "characters": [
                {"name": "Phương", "canonical_age_max": 9},
                {"name": "An", "canonical_age_max": 8},
                {"name": "Mẹ", "canonical_age_max": 35},
            ],
            "script": [
                {"zone": "OPENING", "text": "Phương và An thấy chim non."},
                {"zone": "DEVELOPMENT", "text": "Các em nhờ mẹ giúp."},
                {"zone": "CLIMAX", "text": "Mẹ đỡ Phương và An lên cây."},
                {"zone": "ENDING", "text": "Chim non đã ở trong tổ."},
            ],
        }
        LocalStoryProvider._ensure_contract_requirements(story, contract)
        combined = " ".join(item["text"] for item in story["script"]).casefold()
        self.assertIn("hai chị em", combined)
        self.assertIn("đứng dưới", combined)
        self.assertNotIn("đỡ phương và an lên cây", combined)

    def test_story_craft_stabilizer_removes_surprise_animal_subplot(self) -> None:
        story = {
            "characters": [{"name": "Phương"}, {"name": "An"}],
            "script": [{"zone": "ENDING", "text": (
                "Chim non đã về tổ. Bỗng một chú sóc nhỏ xuất hiện bên bụi cây. "
                "Hai em mỉm cười rồi trở về nhà."
            )}],
        }
        LocalStoryProvider._stabilize_story_craft(story, Profile.YOUTH_SAFE)
        self.assertNotIn("chú sóc", story["script"][0]["text"].casefold())

    def test_environment_is_inferred_from_story_location(self) -> None:
        self.assertEqual(
            LocalStoryProvider._infer_environment("Ba bạn đứng trên bãi biển cạnh hải đăng"),
            "sea_wind_soft",
        )
        self.assertEqual(
            LocalStoryProvider._infer_environment("Hai chị em trú dưới mái hiên khi trời mưa"),
            "rain_soft",
        )

    def test_character_provider_builds_shared_vietnamese_cast_bible(self) -> None:
        provider = LocalCharacterImageProvider(FakeRegistry(), assessor=object())
        provider.configure_cast({"characters": [{
            "character_id": "an", "name": "An", "canonical_age_min": 8,
            "visual_identity": {
                "presentation": "FEMININE", "hair": "tóc đen buộc hai bên",
                "wardrobe": "áo mưa xanh lá", "palette": ["green", "cream"],
                "silhouette": "nhỏ nhắn", "cultural_context": "Việt Nam đương đại",
            },
        }]})
        self.assertIn("vietnamese-storybook-semi-realistic-v1", provider._cast_context)
        self.assertIn("áo mưa xanh lá", provider._cast_context)
        self.assertIn("same warm neutral studio backdrop", provider._cast_context)

    def test_planner_zone_writer_and_critic_form_canonical_story(self) -> None:
        registry = FakeRegistry()
        provider = LocalStoryProvider(registry)
        story = provider.generate(
            Profile.YOUTH_SAFE,
            "Hai bạn nhỏ bảo vệ khu vườn",
            confirm_duration(Profile.YOUTH_SAFE, 15),
            "vi",
        )
        self.assertEqual(
            list(story), ["schema_version", "meta", "characters", "outline", "script"]
        )
        self.assertEqual(len(story["script"]), 8)
        self.assertEqual(
            [item["zone"] for item in story["script"]],
            [
                "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
                "CLIMAX", "FALLING", "ENDING", "FAREWELL",
            ],
        )
        self.assertEqual(story["characters"][0]["adult_visual_eligibility"], "NOT_ADULT")
        self.assertGreaterEqual(len(registry.calls), 18)
        self.assertTrue(all(call[1].json_schema for call in registry.calls))
        words = sum(len(item["text"].split()) for item in story["script"])
        target_words = confirm_duration(Profile.YOUTH_SAFE, 15).target_words
        self.assertGreaterEqual(words, round(target_words * 0.95))
        self.assertLessEqual(words, round(target_words * 1.05))
        self.assertTrue(all(item["text"].endswith(".") for item in story["script"]))
        self.assertLessEqual(len(story["script"][0]["text"].split()), 50)
        self.assertLessEqual(len(story["script"][-1]["text"].split()), 50)
        self.assertEqual(story["meta"]["target"], "7–10 tuổi")
        self.assertEqual(provider.editorial_assessment["status"], "PASS")
        self.assertEqual(provider.editorial_assessment["method"], "MODEL_STORY_CRITIC_V2")
        self.assertTrue(all("STORY_CONTRACT=" in call[1].prompt for call in registry.calls if "TASK: PLAN" in call[1].prompt or "TASK: WRITE_ZONE" in call[1].prompt or "TASK: CRITIC" in call[1].prompt))

    def test_critic_excludes_large_character_reference_provenance(self) -> None:
        registry = FakeRegistry()
        provider = LocalStoryProvider(registry)
        provider._active_contract = {"requirements": []}
        story = {
            "characters": [{
                "character_id": "bo", "name": "Bo", "role": "nhân vật chính",
                "canonical_age_min": 8, "canonical_age_max": 8,
                "visual_identity": {"hair": "tóc đen", "wardrobe": "áo xanh"},
                "reference_asset": {
                    "quality_assessment": {"candidate_history": ["x" * 20000]},
                    "hash": "a" * 64,
                },
            }],
            "outline": {"opening": "Bo nhìn chiếc thuyền."},
            "script": [{"zone": "OPENING", "text": "Bo nhìn chiếc thuyền bị rách."}],
        }
        provider._critic("system", story)
        prompt = registry.calls[-1][1].prompt
        self.assertIn('"character_id":"bo"', prompt)
        self.assertNotIn("reference_asset", prompt)
        self.assertNotIn("candidate_history", prompt)
        self.assertLess(len(prompt), 5000)

    def test_critic_bounds_long_scene_text_while_preserving_both_ends(self) -> None:
        registry = FakeRegistry()
        provider = LocalStoryProvider(registry)
        provider._active_contract = {"requirements": []}
        long_text = "MỞ ĐẦU " + ("chi tiết ở giữa " * 500) + " KẾT QUẢ CUỐI"
        story = {
            "characters": [{"character_id": "an", "name": "An"}],
            "outline": {"opening": "An lựa chọn."},
            "script": [{"zone": "OPENING", "text": long_text}],
        }

        provider._critic("system", story)

        prompt = registry.calls[-1][1].prompt
        self.assertIn("MỞ ĐẦU", prompt)
        self.assertIn("KẾT QUẢ CUỐI", prompt)
        self.assertIn("text_excerpt", prompt)
        self.assertLess(len(prompt), 5000)

    def test_zone_repair_excludes_character_reference_provenance(self) -> None:
        registry = FakeRegistry()
        provider = LocalStoryProvider(registry)
        provider._active_profile = Profile.YOUTH_SAFE
        provider._active_contract = {"requirements": [], "zone_beats": {}}
        story = {
            "meta": {"title": "Chiếc thuyền"},
            "characters": [{
                "character_id": "bo", "name": "Bo", "role": "nhân vật chính",
                "canonical_age_min": 8, "canonical_age_max": 8,
                "reference_asset": {"candidate_history": ["x" * 20000]},
            }],
            "outline": {"opening": "Bo nhìn chiếc thuyền."},
            "script": [{
                "zone": "OPENING", "environment": "room", "voice": "NARRATOR",
                "speed": "NORMAL", "lang": "vi",
                "text": "Bo nhìn chiếc thuyền bị rách.",
            }],
        }
        provider._apply_critic(
            "system", story,
            [{"zone": "OPENING", "issue": "clarify", "instruction": {"error": "X"}}],
            [30], "vi",
        )
        prompt = next(
            request.prompt for _, request in registry.calls
            if "TASK: WRITE_ZONE" in request.prompt
        )
        self.assertIn('"character_id":"bo"', prompt)
        self.assertNotIn("reference_asset", prompt)
        self.assertNotIn("candidate_history", prompt)
        self.assertLess(len(prompt), 10000)

    def test_boat_brief_becomes_ordered_contract_with_negative_constraint(self) -> None:
        duration = confirm_duration(Profile.YOUTH_SAFE, 15)
        allocations = LocalStoryProvider._word_allocations(duration.target_words, 8)
        contract = LocalStoryProvider._story_contract(
            "Bo nói mình buồn. Bo giữ chiếc thuyền còn vết rách. Thuyền không lành lại.",
            "vi",
            ["GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT", "CLIMAX", "FALLING", "ENDING", "FAREWELL"],
            allocations,
        )
        self.assertEqual(contract["ordered_beats"][0], "Bo nói mình buồn")
        self.assertIn("Thuyền không lành lại", contract["negative_constraints"])
        self.assertIn("thuyền", {value.casefold() for value in contract["required_terms"]})
        self.assertLessEqual(contract["zone_word_budgets"]["GREETING"], 50)
        self.assertLessEqual(contract["zone_word_budgets"]["FAREWELL"], 50)
        self.assertEqual(sum(contract["zone_word_budgets"].values()), duration.target_words)

    def test_youth_contract_requires_progressive_beats_dialogue_and_no_subplot(self) -> None:
        duration = confirm_duration(Profile.YOUTH_SAFE, 5)
        allocations = LocalStoryProvider._word_allocations(duration.target_words, 8)
        contract = LocalStoryProvider._story_contract(
            "Hai chị em trả chim non về tổ trước cơn mưa và nhờ người lớn khi nguy hiểm.",
            "vi",
            [
                "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
                "CLIMAX", "FALLING", "ENDING", "FAREWELL",
            ],
            allocations,
            Profile.YOUTH_SAFE,
        )
        self.assertEqual(contract["dialogue_turn_target"], [6, 10])
        self.assertIn("CLIMAX", contract["dialogue_zones"])
        self.assertTrue(contract["narrative_environment_required"])
        self.assertTrue(any("unrelated subplot" in rule for rule in contract["progression_rules"]))

    def test_structured_beat_sheet_keeps_before_after_state(self) -> None:
        fields = {
            "actor": "An", "action": "đặt chim vào hộp", "location": "mái hiên",
            "prop": "hộp lót khăn", "before_state": "chim ướt ngoài mưa",
            "after_state": "chim được che mưa", "dialogue_goal": "gọi ông Tư",
        }
        raw = {zone: dict(fields) for zone in (
            "greeting", "opening", "introduction", "development",
            "climax", "falling", "ending", "farewell",
        )}
        beats = LocalStoryProvider._normalize_beat_sheet(
            raw,
            [
                "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
                "CLIMAX", "FALLING", "ENDING", "FAREWELL",
            ],
        )
        self.assertEqual(beats["DEVELOPMENT"]["before_state"], "chim ướt ngoài mưa")
        self.assertEqual(beats["DEVELOPMENT"]["after_state"], "chim được che mưa")
        self.assertIn("trạng thái đổi từ", LocalStoryProvider._beat_summary(beats["DEVELOPMENT"]))

    def test_outline_contract_binding_is_deterministic_and_complete(self) -> None:
        contract = LocalStoryProvider._story_contract(
            "Hai chị em tìm thấy chim non bị lạc, nhờ người lớn và đưa chim về tổ.",
            "vi",
            [
                "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
                "CLIMAX", "FALLING", "ENDING", "FAREWELL",
            ],
            [30, 80, 90, 140, 110, 80, 80, 30],
            Profile.YOUTH_SAFE,
        )
        outline = {zone.lower(): "Một beat cụ thể." for zone in (
            "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
            "CLIMAX", "FALLING", "ENDING", "FAREWELL",
        )}
        LocalStoryProvider._bind_outline_to_contract(outline, contract)
        evidence = build_outline_evidence({"outline": outline}, contract)
        self.assertEqual(evidence["unbound_requirement_count"], 0)
        self.assertIn("chim non", outline["opening"].casefold())
        self.assertIn("nhờ người lớn", outline["introduction"].casefold())
        self.assertIn("về tổ", outline["climax"].casefold())

    def test_global_duration_trim_removes_only_complete_trailing_sentences(self) -> None:
        duration = confirm_duration(Profile.YOUTH_SAFE, 5)
        story = {
            "script": [
                {
                    "zone": zone,
                    "text": " ".join([
                        "Mai quan sát khu vườn rất cẩn thận.",
                        "Mai ghi lại từng thay đổi trong cuốn sổ nhỏ.",
                        "Mai cùng Bảo thử một ý tưởng mới bên luống hoa.",
                    ]),
                }
                for zone in (
                    "GREETING", "OPENING", "INTRODUCTION", "DEVELOPMENT",
                    "CLIMAX", "FALLING", "ENDING", "FAREWELL",
                )
            ]
        }
        # Inflate one narrative zone beyond the global five-minute ceiling.
        story["script"][3]["text"] += " " + " ".join(
            ["Mai kiểm tra kết quả rồi mỉm cười vui vẻ."] * 70
        )
        LocalStoryProvider._trim_story_to_duration(story, duration)
        total = sum(len(item["text"].split()) for item in story["script"])
        self.assertLessEqual(total, round(duration.target_words * 1.05))
        self.assertGreaterEqual(total, round(duration.target_words * 0.95))
        self.assertTrue(all(item["text"].endswith(".") for item in story["script"]))

    def test_global_duration_balance_leaves_underfill_for_scene_expansion(self) -> None:
        duration = confirm_duration(Profile.YOUTH_SAFE, 5)
        story = {"script": [
            {
                "zone": zone,
                "text": " ".join(["An kiểm tra chiếc hộp cẩn thận."] * count),
            }
            for zone, count in (
                ("GREETING", 3), ("OPENING", 12), ("INTRODUCTION", 12),
                ("DEVELOPMENT", 17), ("CLIMAX", 14), ("FALLING", 12),
                ("ENDING", 12), ("FAREWELL", 3),
            )
        ]}
        before = sum(len(item["text"].split()) for item in story["script"])
        self.assertLess(before, round(duration.target_words * 0.95))
        LocalStoryProvider._trim_story_to_duration(story, duration)
        after = sum(len(item["text"].split()) for item in story["script"])
        self.assertEqual(after, before)
        self.assertLess(after, round(duration.target_words * 0.95))

    def test_local_safety_is_independent_structured_assessment(self) -> None:
        registry = FakeRegistry()
        provider = LocalSafetyProvider(registry)
        decision = provider.assess(
            Profile.YOUTH_SAFE,
            {
                "characters": [{"name": "An", "canonical_age_min": 12}],
                "script": [{"text": "An trở về nhà an toàn."}],
            },
        )
        self.assertEqual(decision.status, "PASS")
        self.assertEqual(decision.method, "MODEL_ASSESSED_LOCAL")
        self.assertEqual(registry.calls[0][0], "safety")
        schema = registry.calls[0][1].json_schema
        self.assertEqual(schema["properties"]["status"]["enum"], ["PASS", "FAIL"])
        self.assertEqual(schema["properties"]["findings"]["maxItems"], 8)

    def test_state_plan_is_chained_and_equal_states_are_repaired(self) -> None:
        sheet = {
            "OPENING": {
                "actor": "An", "action": "thấy dấu chân", "location": "vườn",
                "prop": "dấu chân", "before_state": "chưa biết", "after_state": "có manh mối",
            },
            "DEVELOPMENT": {
                "actor": "An", "action": "lần theo dấu", "location": "vườn",
                "prop": "đèn pin", "before_state": "sai trạng thái", "after_state": "có manh mối",
            },
        }
        repairs = LocalStoryProvider._stabilize_beat_sheet(
            sheet, ["OPENING", "DEVELOPMENT"], strict=True
        )
        self.assertEqual(sheet["DEVELOPMENT"]["before_state"], "có manh mối")
        self.assertNotEqual(
            sheet["DEVELOPMENT"]["after_state"], sheet["DEVELOPMENT"]["before_state"]
        )
        self.assertEqual([item["reason"] for item in repairs], [
            "CHAIN_PREVIOUS_EXIT_STATE", "MATERIAL_STATE_DELTA_REQUIRED",
        ])

    def test_scene_local_review_requires_actor_and_concrete_beat_evidence(self) -> None:
        beat = {
            "actor": "An", "action": "đào đất", "location": "khu vườn",
            "prop": "xẻng", "before_state": "chưa tìm thấy hộp", "after_state": "thấy chiếc hộp",
        }
        findings = LocalStoryProvider._scene_draft_findings(
            {"environment": "none", "text": "Bình ngồi trong phòng và đọc sách."},
            beat, "DEVELOPMENT", Profile.YOUTH_SAFE, strict=True,
        )
        errors = {item["error"] for item in findings}
        self.assertIn("SCENE_ACTOR_MISSING", errors)
        self.assertIn("SCENE_BEAT_EVIDENCE_INSUFFICIENT", errors)
        self.assertIn("SCENE_ENVIRONMENT_MISSING", errors)
        self.assertEqual(
            LocalStoryProvider._scene_draft_findings(
                {"environment": "garden_morning", "text": "An dùng xẻng đào đất trong khu vườn."},
                beat, "DEVELOPMENT", Profile.YOUTH_SAFE, strict=True,
            ),
            [],
        )

    def test_scene_local_review_enforces_dialogue_and_climax(self) -> None:
        beat = {
            "actor": "Bo", "action": "chọn giữ thuyền", "location": "phòng ngủ",
            "prop": "thuyền giấy", "before_state": "Bo buồn", "after_state": "Bo bình tĩnh",
        }
        findings = LocalStoryProvider._scene_draft_findings(
            {"environment": "bedroom_soft", "text": "Bo nhìn thuyền giấy trong phòng ngủ."},
            beat, "CLIMAX", Profile.YOUTH_SAFE, strict=True, target_words=200,
        )
        errors = {item["error"] for item in findings}
        self.assertIn("SCENE_DIALOGUE_MISSING", errors)
        self.assertIn("SCENE_CLIMAX_ACTION_MISSING", errors)

    def test_characters_replace_unspecified_presentation(self) -> None:
        characters = LocalStoryProvider._characters([
            {"name": "Bo", "role": "trẻ em", "age": 8, "visual_identity": {}},
            {"name": "Mẹ", "role": "mẹ", "age": 32, "visual_identity": {}},
            {"name": "An", "role": "bạn", "age": 8, "visual_identity": {}},
        ], Profile.YOUTH_SAFE)
        self.assertEqual(
            [item["visual_identity"]["presentation"] for item in characters],
            ["MASCULINE", "FEMININE", "ANDROGYNOUS"],
        )
        self.assertTrue(all(
            "việt nam" in item["visual_identity"]["cultural_context"].casefold()
            for item in characters
        ))

    def test_local_safety_normalizes_known_status_alias(self) -> None:
        class AliasRegistry(FakeRegistry):
            def generate_json(self, role, request, cancellation=None):
                self.calls.append((role, request))
                return {"status": "safe", "findings": []}

        registry = AliasRegistry()
        decision = LocalSafetyProvider(registry).assess(
            Profile.YOUTH_SAFE,
            {
                "characters": [{"name": "An", "canonical_age_min": 8}],
                "script": [{"text": "An đứng dưới mái hiên và gọi người lớn."}],
            },
        )
        self.assertEqual(decision.status, "PASS")
        self.assertEqual(len(registry.calls), 1)

    def test_local_safety_retries_unknown_status_then_fails_closed(self) -> None:
        class InvalidRegistry(FakeRegistry):
            def generate_json(self, role, request, cancellation=None):
                self.calls.append((role, request))
                return {"status": "UNKNOWN", "findings": []}

        registry = InvalidRegistry()
        decision = LocalSafetyProvider(registry).assess(
            Profile.YOUTH_SAFE,
            {
                "characters": [{"name": "An", "canonical_age_min": 8}],
                "script": [{"text": "An trở về nhà."}],
            },
        )
        self.assertEqual(decision.status, "FAIL")
        self.assertEqual(decision.method, "MODEL_ASSESSED_LOCAL_INVALID")
        self.assertEqual(decision.findings[0]["category"], "INVALID_ASSESSMENT")
        self.assertEqual(len(registry.calls), 2)


if __name__ == "__main__":
    unittest.main()
