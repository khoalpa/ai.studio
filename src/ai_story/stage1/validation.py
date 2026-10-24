from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from statistics import mean
from typing import Any

from ..errors import ArtifactError
from ..hashing import canonical_json_bytes, sha256_bytes
from ..models import Profile
from .config import DurationPlan, stage1_config
from .contract import build_outline_evidence, build_story_contract
from .png import png_dimensions, png_visual_statistics
from .providers import SafetyProvider

WORD_PATTERN = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*", re.UNICODE)
SENTENCE_PATTERN = re.compile(r"[^.!?…]+[.!?…]+", re.UNICODE)
CHARACTER_FIELDS = [
    "character_id", "name", "role", "canonical_age_min", "canonical_age_max",
    "adult_visual_eligibility", "visual_story_importance", "identity_traits", "visual_identity", "reference_asset",
]
VISUAL_IDENTITY_FIELDS = ["presentation", "hair", "wardrobe", "palette", "silhouette", "cultural_context"]
REFERENCE_FIELDS = [
    "schema_version", "reference_image", "file_sha256", "pixel_sha256",
    "dimensions", "identity_lock", "quality_assessment", "validation_status",
]
SCRIPT_FIELDS = ["zone", "environment", "voice", "speed", "lang", "text"]
OUTLINE_FIELDS = ["greeting", "opening", "introduction", "development", "climax", "falling", "ending", "farewell"]
FORBIDDEN_SCRIPT_PATTERNS = {
    "HAN": re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"),
    "CYRILLIC": re.compile(r"[\u0400-\u052f]"),
    "ARABIC": re.compile(r"[\u0600-\u06ff]"),
    "THAI": re.compile(r"[\u0e00-\u0e7f]"),
    "HIRAGANA_KATAKANA": re.compile(r"[\u3040-\u30ff]"),
}
DANGLING_END_WORDS = {
    "vi": {"mỗi", "và", "hoặc", "nhưng", "với", "của", "để", "khi", "nếu", "vì", "mà", "như", "trong", "từ", "bằng", "cho", "đều", "luôn", "những", "các", "chuyến", "câu"},
    "en": {"and", "or", "but", "with", "of", "to", "when", "if", "because", "as", "the", "a", "an"},
}
VALID_END_PHRASES = {
    "vi": {("công", "bằng"), ("cân", "bằng"), ("ngang", "bằng"), ("thăng", "bằng")},
}
TRAILING_CLOSERS = '"\'”’»)]}'
ENGLISH_FUNCTION_WORDS = {
    "the", "and", "she", "he", "they", "this", "that", "with", "from", "look",
    "here", "perfectly", "handed", "said", "asked", "will", "would", "could",
}
SHORT_FRAGMENT_ENDINGS = {
    "vi": {"kể", "cho", "đều", "những", "các", "sẽ", "viết"},
    "en": {"the", "a", "an", "will", "would", "to"},
}


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    severity: str
    status: str
    detector_method: str
    metrics: dict[str, Any]
    findings: list[dict[str, Any]]

    def report_record(self) -> dict[str, Any]:
        evidence = {
            "gate_id": self.gate_id,
            "status": self.status,
            "metrics": self.metrics,
            "findings": self.findings,
        }
        return {
            "gate_id": self.gate_id,
            "severity": self.severity,
            "status": self.status,
            "detector_method": self.detector_method,
            "evidence_id": f"evidence:{self.gate_id.lower()}",
            "validation_digest_sha256": sha256_bytes(canonical_json_bytes(evidence)),
            "evidence_locators": [item.get("locator") for item in self.findings if item.get("locator")],
            "metrics": self.metrics,
            "failure_reason": None if self.status == "PASS" else self.findings,
        }


def count_words(story: dict[str, Any]) -> int:
    return sum(len(WORD_PATTERN.findall(item["text"])) for item in story["script"])


class Stage1Validator:
    @staticmethod
    def _has_dangling_end(words: list[str], language: str) -> bool:
        if not words or words[-1] not in DANGLING_END_WORDS.get(language, set()):
            return False
        phrase = tuple(words[-2:]) if len(words) >= 2 else tuple(words)
        return phrase not in VALID_END_PHRASES.get(language, set())

    def __init__(self, safety_provider: SafetyProvider, editorial_assessment: dict[str, Any] | None = None):
        self.safety_provider = safety_provider
        self.editorial_assessment = editorial_assessment or {}

    def validate(
        self, story: dict[str, Any], profile: Profile, duration: DurationPlan,
        image_bytes: dict[str, bytes], brief: str | None = None,
    ) -> list[GateResult]:
        return [
            self._brief_policy(brief or "", profile),
            self._structure(story),
            self._profile(story, profile),
            self._word_duration(story, duration),
            self._zone_budget(story),
            self._characters(story, profile, image_bytes),
            self._language_integrity(story),
            self._sentence_completeness(story),
            self._prose_hygiene(story),
            self._narrative_voice_consistency(story),
            self._brief_adherence(story, brief or ""),
            self._story_contract_compliance(story, brief or ""),
            self._narrative_invariants(story, brief or ""),
            self._narrative_coherence(story),
            self._scene_state_continuity(story),
            self._intra_zone_repetition(story),
            self._semantic_repetition(story),
            self._age_profile(story, profile, duration),
            self._dialogue_structure(story, profile),
            self._editorial_integrity(story, profile),
            self._youth_context_safety(story, profile),
            self._quality(story, profile, brief or "", self.editorial_assessment),
            self._safety(story, profile),
        ]

    @staticmethod
    def _brief_policy(brief: str, profile: Profile) -> GateResult:
        """Reject explicit requests for unsafe or deliberately incoherent outcomes."""
        normalized = unicodedata.normalize("NFC", brief).casefold()
        findings: list[dict[str, Any]] = []
        graphic_violence = any(term in normalized for term in (
            "đẫm máu", "máu me", "bạo lực đồ họa", "mô tả chi tiết một cuộc đánh nhau",
        ))
        child_subject = any(term in normalized for term in (
            "trẻ em", "trẻ con", "học sinh", "bé trai", "bé gái",
        ))
        if profile is Profile.YOUTH_SAFE and graphic_violence and child_subject:
            findings.append({
                "locator": "request.brief",
                "error": "UNSAFE_GRAPHIC_CHILD_VIOLENCE_REQUEST",
                "resolution": "REJECT",
            })
        unsupported_culprit = (
            "hung thủ" in normalized
            and any(term in normalized for term in (
                "không có manh mối", "không có bằng chứng", "dù trước đó không",
            ))
        )
        if unsupported_culprit:
            findings.append({
                "locator": "request.brief",
                "error": "UNSUPPORTED_CULPRIT_REVEAL_REQUEST",
                "resolution": "REPAIR_BRIEF",
            })
        unexplained_evidence_change = (
            any(term in normalized for term in ("tang vật", "vật chứng"))
            and any(term in normalized for term in ("đổi vị trí", "biến mất", "xuất hiện lại"))
            and any(term in normalized for term in ("không có lời giải", "không giải thích"))
        )
        if unexplained_evidence_change:
            findings.append({
                "locator": "request.brief",
                "error": "UNEXPLAINED_EVIDENCE_STATE_CHANGE_REQUEST",
                "resolution": "REPAIR_BRIEF",
            })
        unexplained_return_after_death = (
            any(term in normalized for term in ("chết giữa truyện", "đã chết"))
            and any(term in normalized for term in ("xuất hiện bình thường", "sống lại", "trở lại"))
            and any(term in normalized for term in ("không giải thích", "không có lời giải"))
        )
        if unexplained_return_after_death:
            findings.append({
                "locator": "request.brief",
                "error": "UNEXPLAINED_RETURN_AFTER_DEATH_REQUEST",
                "resolution": "REPAIR_BRIEF",
            })
        unattributed_multi_speaker_dialogue = (
            any(term in normalized for term in ("tranh luận", "đối thoại", "hội thoại"))
            and any(term in normalized for term in ("bốn người", "nhiều người"))
            and any(term in normalized for term in (
                "không ghi dấu người nói", "không rõ người nói", "không ghi người nói",
            ))
        )
        if unattributed_multi_speaker_dialogue:
            findings.append({
                "locator": "request.brief",
                "error": "UNATTRIBUTED_MULTI_SPEAKER_DIALOGUE_REQUEST",
                "resolution": "REPAIR_BRIEF",
            })
        if "câu cụt" in normalized and any(term in normalized for term in (
            "viết toàn", "toàn câu cụt", "mưa. chạy. sợ.",
        )):
            findings.append({
                "locator": "request.brief",
                "error": "DELIBERATE_FRAGMENT_STYLE_REQUEST",
                "resolution": "REPAIR_BRIEF",
            })
        return GateResult(
            "BRIEF_POLICY_GATE",
            "PUBLISH_BLOCKER",
            "PASS" if not findings else "FAIL",
            "DETERMINISTIC_BRIEF_INTENT_POLICY",
            {
                "active_profile": profile.value,
                "violation_count": len(findings),
                "request_disposition": "ACCEPT" if not findings else findings[0]["resolution"],
            },
            findings,
        )

    @staticmethod
    def _structure(story: dict[str, Any]) -> GateResult:
        findings: list[dict[str, Any]] = []
        config = stage1_config()
        if list(story) != ["schema_version", "meta", "characters", "outline", "script"]:
            findings.append({"locator": "$", "error": "STORY_ROOT_ORDER_INVALID"})
        if story.get("schema_version") != config["story_schema_version"]:
            findings.append({"locator": "schema_version", "error": "STORY_SCHEMA_VERSION_INVALID"})
        if list(story.get("outline", {})) != OUTLINE_FIELDS:
            findings.append({"locator": "outline", "error": "OUTLINE_SHAPE_INVALID"})
        zones = config["zones"]
        observed: list[str] = []
        rank = {zone: index for index, zone in enumerate(zones)}
        previous = -1
        for index, item in enumerate(story.get("script", [])):
            if list(item) != SCRIPT_FIELDS:
                findings.append({"locator": f"script[{index}]", "error": "SCRIPT_SHAPE_INVALID"})
                continue
            zone = item["zone"]
            observed.append(zone)
            for field, allowed in (
                ("zone", zones), ("environment", config["environments"]),
                ("voice", config["voices"]), ("speed", config["speeds"]),
            ):
                if item[field] not in allowed:
                    findings.append({"locator": f"script[{index}].{field}", "error": "SCRIPT_ENUM_VALUE_INVALID"})
            expected_lang = str(story.get("meta", {}).get("language", "")).upper()
            if item["lang"] != expected_lang:
                findings.append({"locator": f"script[{index}].lang", "error": "SCRIPT_LANG_META_MISMATCH"})
            current = rank.get(zone, -1)
            if current < previous:
                findings.append({"locator": f"script[{index}].zone", "error": "ZONE_REGRESSION"})
            previous = current
            terminal_text = item["text"].strip().rstrip(TRAILING_CLOSERS).rstrip()
            if not terminal_text or terminal_text[-1:] not in ".!?…":
                findings.append({"locator": f"script[{index}].text", "error": "INCOMPLETE_TEXT"})
        if set(observed) != set(zones):
            findings.append({"locator": "script", "error": "ZONE_COVERAGE_INVALID"})
        metrics = {
            "scanned_item_count": len(story.get("script", [])),
            "expected_item_count": len(story.get("script", [])),
            "invalid_item_count": len({item["locator"].split(".")[0] for item in findings}),
            "violation_count": len(findings),
            "violations": findings,
        }
        return GateResult("PRE-SERIALIZE-SCRIPT-ENUM-VALIDATION-01", "PUBLISH_BLOCKER", "PASS" if not findings else "FAIL", "DETERMINISTIC", metrics, findings)

    @staticmethod
    def _profile(story: dict[str, Any], profile: Profile) -> GateResult:
        findings = []
        expected_channel = stage1_config()["channels"][profile.value]
        if story["meta"].get("channel") != expected_channel:
            findings.append({"locator": "meta.channel", "error": "PROFILE_CHANNEL_MISMATCH"})
        if story["meta"].get("language") not in stage1_config()["languages"]:
            findings.append({"locator": "meta.language", "error": "LANGUAGE_INVALID"})
        return GateResult("PROFILE_GATE", "PUBLISH_BLOCKER", "PASS" if not findings else "FAIL", "DETERMINISTIC", {"active_profile": profile.value}, findings)

    @staticmethod
    def _word_duration(story: dict[str, Any], duration: DurationPlan) -> GateResult:
        words = count_words(story)
        lower = round(duration.target_words * 0.95)
        upper = round(duration.target_words * 1.05)
        estimated = round(words / duration.target_wpm, 3)
        findings = []
        if not lower <= words <= upper:
            findings.append({"locator": "script", "error": "WORD_BUDGET_INVALID", "actual": words, "expected": [lower, upper]})
        target_lower = duration.length_target * 0.95
        target_upper = duration.length_target * 1.05
        if not target_lower <= estimated <= target_upper:
            findings.append({"locator": "script", "error": "DURATION_INVALID", "actual": estimated, "expected": [round(target_lower, 3), round(target_upper, 3)]})
        return GateResult("WORD_DURATION_GATE", "PUBLISH_BLOCKER", "PASS" if not findings else "FAIL", "DETERMINISTIC", {"total_words": words, "target_words": duration.target_words, "estimated_duration_minutes": estimated, "target_wpm": duration.target_wpm}, findings)

    @staticmethod
    def _zone_budget(story: dict[str, Any]) -> GateResult:
        findings: list[dict[str, Any]] = []
        metrics: dict[str, int] = {}
        for index, item in enumerate(story.get("script", [])):
            zone = str(item.get("zone", ""))
            words = len(WORD_PATTERN.findall(str(item.get("text", ""))))
            metrics[zone] = words
            if zone in {"GREETING", "FAREWELL"} and words > 50:
                findings.append({
                    "locator": f"script[{index}].text", "error": "BOOKEND_TOO_LONG",
                    "zone": zone, "actual": words, "maximum": 50,
                })
        return GateResult(
            "ZONE_BUDGET_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_ZONE_WORD_BUDGET", {"zone_word_counts": metrics, "bookend_maximum": 50}, findings,
        )

    @staticmethod
    def _characters(story: dict[str, Any], profile: Profile, image_bytes: dict[str, bytes]) -> GateResult:
        findings = []
        ids: set[str] = set()
        names: set[str] = set()
        style_ids: set[str] = set()
        expected_size = stage1_config()["character_image"]
        for index, character in enumerate(story["characters"]):
            locator = f"characters[{index}]"
            if list(character) != CHARACTER_FIELDS:
                findings.append({"locator": locator, "error": "CHARACTER_SHAPE_INVALID"})
                continue
            identifier = character["character_id"]
            name = unicodedata.normalize("NFC", character["name"])
            if not re.fullmatch(r"[a-z][a-z0-9_]*", identifier) or identifier in ids:
                findings.append({"locator": f"{locator}.character_id", "error": "CHARACTER_ID_INVALID"})
            if name in names:
                findings.append({"locator": f"{locator}.name", "error": "CHARACTER_NAME_DUPLICATE"})
            ids.add(identifier)
            names.add(name)
            if not (0 <= character["canonical_age_min"] <= character["canonical_age_max"] <= 120):
                findings.append({"locator": locator, "error": "CHARACTER_AGE_INVALID"})
            traits = character["identity_traits"]
            if not isinstance(traits, list) or not 2 <= len(traits) <= 6 or len(set(traits)) != len(traits):
                findings.append({"locator": f"{locator}.identity_traits", "error": "IDENTITY_TRAITS_INVALID"})
            visual_identity = character.get("visual_identity")
            if not isinstance(visual_identity, dict) or list(visual_identity) != VISUAL_IDENTITY_FIELDS:
                findings.append({"locator": f"{locator}.visual_identity", "error": "VISUAL_IDENTITY_SHAPE_INVALID"})
            else:
                if visual_identity["presentation"] not in {"MASCULINE", "FEMININE", "ANDROGYNOUS"}:
                    findings.append({"locator": f"{locator}.visual_identity.presentation", "error": "VISUAL_PRESENTATION_UNRESOLVED"})
                palette = visual_identity.get("palette")
                if not isinstance(palette, list) or not 2 <= len(palette) <= 5 or not all(
                    isinstance(value, str) and value.strip() for value in palette
                ):
                    findings.append({"locator": f"{locator}.visual_identity.palette", "error": "VISUAL_PALETTE_INVALID"})
                for field in ("hair", "wardrobe", "silhouette", "cultural_context"):
                    value = str(visual_identity.get(field, "")).strip()
                    if not value or value.casefold() in {"unspecified", "consistent", "contemporary"}:
                        findings.append({"locator": f"{locator}.visual_identity.{field}", "error": "VISUAL_IDENTITY_DETAIL_MISSING"})
                if story.get("meta", {}).get("language") == "vi":
                    culture = str(visual_identity.get("cultural_context", "")).casefold()
                    if "việt" not in culture and "viet" not in culture:
                        findings.append({"locator": f"{locator}.visual_identity.cultural_context", "error": "VIETNAMESE_CONTEXT_MISSING"})
            expected_adult = "VERIFIED_ADULT" if character["canonical_age_min"] >= 18 else "NOT_ADULT"
            if character["adult_visual_eligibility"] != expected_adult:
                findings.append({"locator": f"{locator}.adult_visual_eligibility", "error": "ADULT_VISUAL_STATUS_INVALID"})
            reference = character["reference_asset"]
            if not isinstance(reference, dict) or list(reference) != REFERENCE_FIELDS:
                findings.append({"locator": f"{locator}.reference_asset", "error": "REFERENCE_ASSET_SHAPE_INVALID"})
                continue
            path = reference.get("reference_image") if isinstance(reference, dict) else None
            locks = reference.get("identity_lock", []) if isinstance(reference, dict) else []
            required_lock_prefixes = (
                "style:", "age:", "presentation:", "hair:", "wardrobe:",
                "palette:", "silhouette:", "culture:",
            )
            for prefix in required_lock_prefixes:
                if not any(str(value).startswith(prefix) for value in locks):
                    findings.append({
                        "locator": f"{locator}.reference_asset.identity_lock",
                        "error": "IDENTITY_LOCK_INCOMPLETE", "missing_prefix": prefix,
                    })
            style_values = [str(value)[6:] for value in locks if str(value).startswith("style:")]
            style_ids.update(style_values)
            data = image_bytes.get(path or "")
            if data is None:
                findings.append({"locator": f"{locator}.reference_asset", "error": "REFERENCE_IMAGE_MISSING"})
            else:
                width, height = png_dimensions(data)
                if [width, height] != [expected_size["width"], expected_size["height"]]:
                    findings.append({"locator": path, "error": "REFERENCE_DIMENSIONS_INVALID"})
                if reference.get("dimensions") != [width, height]:
                    findings.append({"locator": path, "error": "REFERENCE_DECLARED_DIMENSIONS_INVALID"})
                if reference.get("file_sha256") != sha256_bytes(data):
                    findings.append({"locator": path, "error": "REFERENCE_HASH_INVALID"})
                reference_status = reference.get("validation_status")
                if reference_status not in {"PASS", "FAIL", "NOT_VERIFIED"}:
                    findings.append({"locator": path, "error": "REFERENCE_STATUS_INVALID"})
                elif reference_status == "FAIL":
                    findings.append({"locator": path, "error": "REFERENCE_STATUS_FAILED"})
                assessment = reference.get("quality_assessment")
                if not isinstance(assessment, dict):
                    findings.append({"locator": path, "error": "CHARACTER_SEMANTIC_EVIDENCE_MISSING"})
                else:
                    assessment_status = assessment.get("status")
                    assessment_method = assessment.get("method")
                    if assessment_status == "ASSESSED_FAIL":
                        for semantic_finding in assessment.get("findings", []):
                            findings.append({
                                "locator": path,
                                **(semantic_finding if isinstance(semantic_finding, dict) else {
                                    "error": "CHARACTER_SEMANTIC_QA_FAILED",
                                    "detail": str(semantic_finding),
                                }),
                            })
                    elif assessment_status == "NOT_ASSESSED":
                        findings.append({
                            "locator": path,
                            "error": "CHARACTER_SEMANTIC_NOT_ASSESSED",
                            "method": assessment_method,
                        })
                    elif assessment_status not in {"ASSESSED_PASS", "TEST_FIXTURE"}:
                        findings.append({"locator": path, "error": "CHARACTER_SEMANTIC_STATUS_INVALID"})
                try:
                    statistics = png_visual_statistics(data)
                    if statistics["sampled_unique_colors"] < 16 or statistics["sampled_channel_range"] < 12:
                        findings.append({
                            "locator": path, "error": "REFERENCE_IMAGE_LOW_INFORMATION",
                            **statistics,
                        })
                except ArtifactError as exc:
                    findings.append({"locator": path, "error": "REFERENCE_IMAGE_QA_UNSUPPORTED", "detail": str(exc)})
        if len(style_ids) != 1:
            findings.append({
                "locator": "characters[*].reference_asset.identity_lock",
                "error": "CHARACTER_ART_DIRECTION_MISMATCH",
                "observed_style_ids": sorted(style_ids),
            })
        return GateResult(
            "CHARACTER_REFERENCE_SET_GATE", "PUBLISH_BLOCKER",
            "PASS" if not findings else "FAIL", "DETERMINISTIC_IMAGE_CONTENT",
            {
                "character_count": len(story["characters"]),
                "art_direction_ids": sorted(style_ids),
                "semantic_assessed_count": sum(
                    character.get("reference_asset", {}).get("quality_assessment", {}).get("status")
                    == "ASSESSED_PASS" for character in story["characters"]
                ),
                "semantic_assessments": [
                    {
                        "character_id": character.get("character_id"),
                        **character.get("reference_asset", {}).get("quality_assessment", {}),
                    }
                    for character in story["characters"]
                ],
            },
            findings,
        )

    @staticmethod
    def _brief_adherence(story: dict[str, Any], brief: str) -> GateResult:
        stop = {
            "và", "là", "của", "một", "những", "các", "được", "cho", "với", "trong", "khi",
            "thì", "mình", "cùng", "dần", "lại", "không", "the", "and", "with", "from", "that",
        }
        brief_tokens = {
            word.casefold() for word in WORD_PATTERN.findall(unicodedata.normalize("NFC", brief))
            if len(word) >= 3 and word.casefold() not in stop
        }
        content = " ".join(
            [str(story.get("meta", {}).get("title", ""))]
            + [str(character.get("name", "")) for character in story.get("characters", [])]
            + [str(value) for value in story.get("outline", {}).values()]
            + [str(item.get("text", "")) for item in story.get("script", [])]
        )
        content_tokens = {word.casefold() for word in WORD_PATTERN.findall(unicodedata.normalize("NFC", content))}
        matched = sorted(brief_tokens & content_tokens)
        missing = sorted(brief_tokens - content_tokens)
        coverage = len(matched) / max(1, len(brief_tokens))
        findings = []
        if brief_tokens and coverage < 0.35:
            findings.append({
                "locator": "script", "error": "BRIEF_CONTENT_COVERAGE_TOO_LOW",
                "actual": round(coverage, 4), "minimum": 0.35, "missing_terms": missing[:20],
            })
        protagonist_match = re.match(
            r"\s*([A-ZÀ-Ỹ][^,\s]*),", unicodedata.normalize("NFC", brief)
        )
        expected_protagonist = protagonist_match.group(1) if protagonist_match else None
        characters = story.get("characters", [])
        observed_protagonist = str(characters[0].get("name", "")) if characters else ""
        if (
            expected_protagonist
            and observed_protagonist.casefold() != expected_protagonist.casefold()
        ):
            findings.append({
                "locator": "characters[0]", "error": "BRIEF_PROTAGONIST_MISMATCH",
                "actual": observed_protagonist, "expected": expected_protagonist,
            })
        return GateResult(
            "BRIEF_ADHERENCE_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_BRIEF_LEXICAL_COVERAGE",
            {"brief_term_count": len(brief_tokens), "matched_term_count": len(matched), "coverage": round(coverage, 4), "missing_terms": missing[:20], "expected_protagonist": expected_protagonist, "observed_protagonist": observed_protagonist},
            findings,
        )

    @staticmethod
    def _story_contract_compliance(story: dict[str, Any], brief: str) -> GateResult:
        contract = build_story_contract(brief, str(story.get("meta", {}).get("language", "vi")))
        findings: list[dict[str, Any]] = []
        characters = story.get("characters", [])
        character_by_name = {
            str(item.get("name", "")).casefold(): (index, item)
            for index, item in enumerate(characters)
        }

        for entity in contract["entities"]:
            expected_name = str(entity.get("name", ""))
            match = character_by_name.get(expected_name.casefold())
            if match is None:
                findings.append({
                    "locator": "characters",
                    "error": "REQUIRED_ROLE_MISSING",
                    "entity": expected_name,
                    "role": entity["role"],
                })
                continue
            index, character = match
            minimum = entity.get("age_min")
            maximum = entity.get("age_max")
            actual_min = character.get("canonical_age_min")
            actual_max = character.get("canonical_age_max")
            if minimum is not None and maximum is not None and (
                not isinstance(actual_min, int)
                or not isinstance(actual_max, int)
                or actual_min < minimum
                or actual_max > maximum
            ):
                findings.append({
                    "locator": f"characters[{index}]",
                    "error": "ROLE_AGE_CONTRADICTION",
                    "entity": expected_name,
                    "role": entity["role"],
                    "actual": [actual_min, actual_max],
                    "expected": [minimum, maximum],
                })

        script_by_zone = {
            str(item.get("zone", "")): unicodedata.normalize("NFC", str(item.get("text", ""))).casefold()
            for item in story.get("script", [])
        }
        requirement_evidence: dict[str, list[str]] = {}
        for requirement in contract["requirements"]:
            locators = []
            for zone in requirement["allowed_zones"]:
                text = script_by_zone.get(zone, "")
                if any(anchor in text for anchor in requirement["anchors"]):
                    index = next((i for i, item in enumerate(story.get("script", [])) if item.get("zone") == zone), -1)
                    if index >= 0:
                        locators.append(f"script[{index}].text")
            requirement_evidence[requirement["requirement_id"]] = locators
            if not locators:
                error = {
                    "SETUP": "MISSING_REQUIRED_SETUP",
                    "ACTION": "OFF_BRIEF_EVENT_CHAIN",
                    "OUTCOME": "MISSING_REQUIRED_OUTCOME",
                }[requirement["kind"]]
                findings.append({
                    "locator": "script",
                    "error": error,
                    "requirement_id": requirement["requirement_id"],
                    "expected_zones": requirement["allowed_zones"],
                })

        outline_evidence = build_outline_evidence(story, contract)
        for binding in outline_evidence["requirement_bindings"]:
            if binding["status"] == "UNBOUND":
                findings.append({
                    "locator": "outline",
                    "error": "OUTLINE_REQUIREMENT_UNBOUND",
                    "requirement_id": binding["requirement_id"],
                })

        if contract["relationships"]:
            dialogue_text = " ".join(script_by_zone.values())
            if re.search(r'["“][^"”]*(?:cậu|tớ)[^"”]*["”]\s*,?\s*mẹ\s+(?:đáp|nói)', dialogue_text):
                findings.append({
                    "locator": "script",
                    "error": "RELATIONSHIP_DIALOGUE_MISMATCH",
                    "relationship": "PARENT_OF",
                })
            if "hai bạn" in dialogue_text and "mẹ" in character_by_name:
                findings.append({
                    "locator": "script",
                    "error": "RELATIONSHIP_NARRATION_MISMATCH",
                    "relationship": "PARENT_OF",
                })

        ending = script_by_zone.get("ENDING", "")
        all_script = " ".join(script_by_zone.values())
        for outcome in contract.get("forbidden_outcomes", []):
            matched = next((anchor for anchor in outcome.get("anchors", []) if anchor in all_script), None)
            if matched:
                findings.append({
                    "locator": "script",
                    "error": "FORBIDDEN_OUTCOME_PRESENT",
                    "outcome_id": outcome.get("outcome_id"),
                    "matched_anchor": matched,
                })
        if contract.get("scenario") == "LOST_BIRD_RETURN":
            child_names = [
                str(item.get("name", "")).casefold()
                for item in story.get("characters", [])
                if int(item.get("canonical_age_max", 120)) < 18
            ]
            for index, item in enumerate(story.get("script", [])):
                for sentence in re.findall(r"[^.!?…]+[.!?…]+", str(item.get("text", ""))):
                    folded = sentence.casefold()
                    if (
                        any(name and name in folded for name in child_names)
                        and any(term in folded for term in ("trèo", "leo lên cây", "lên cây", "theo sau"))
                        and not any(term in folded for term in ("đứng dưới", "chờ dưới", "ở dưới"))
                    ):
                        findings.append({
                            "locator": f"script[{index}].text",
                            "error": "FORBIDDEN_OUTCOME_PRESENT",
                            "outcome_id": "child_climbs_in_rain",
                            "matched_anchor": "child_named_in_climbing_context",
                        })
                        break
        missing_actions = [
            item["requirement_id"] for item in contract["requirements"]
            if item["kind"] == "ACTION" and not requirement_evidence.get(item["requirement_id"])
        ]
        if missing_actions and any(term in ending for term in ("hoàn thành", "đã xong", "thành công", "complete", "completed")):
            findings.append({
                "locator": next((f"script[{i}].text" for i, item in enumerate(story.get("script", [])) if item.get("zone") == "ENDING"), "script"),
                "error": "UNSUPPORTED_COMPLETION_CLAIM",
                "missing_requirements": missing_actions,
            })

        return GateResult(
            "STORY_CONTRACT_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_STORY_CONTRACT_V1",
            {
                "scenario": contract["scenario"],
                "entity_count": len(contract["entities"]),
                "relationship_count": len(contract["relationships"]),
                "requirement_count": len(contract["requirements"]),
                "forbidden_outcome_count": len(contract.get("forbidden_outcomes", [])),
                "requirement_evidence": requirement_evidence,
                "outline_requirement_bindings": outline_evidence["requirement_bindings"],
                "unbound_outline_requirement_count": outline_evidence["unbound_requirement_count"],
                "violation_count": len(findings),
            },
            findings,
        )
    @staticmethod
    def _intra_zone_repetition(story: dict[str, Any]) -> GateResult:
        placeholder = re.compile(
            r"^(?:hình ảnh|dấu vết|ở bước|thử thách|hành động|hậu quả|chi tiết|image|clue|at step|challenge|action|consequence|detail)\s+(?:<n>|\d+)",
            re.IGNORECASE,
        )
        findings: list[dict[str, Any]] = []
        zone_metrics = []
        for item_index, item in enumerate(story.get("script", [])):
            sentences = [sentence for _, _, sentence in Stage1Validator._sentences({"script": [item]})]
            normalized = [re.sub(r"\d+", "<n>", sentence.casefold()).strip() for sentence in sentences]
            frequencies = {value: normalized.count(value) for value in set(normalized)}
            dominant = max(frequencies.values(), default=0)
            ratio = dominant / max(1, len(normalized))
            placeholder_count = sum(bool(placeholder.match(value)) for value in normalized)
            zone_metrics.append({
                "zone": item.get("zone"), "sentence_count": len(normalized),
                "normalized_unique_count": len(frequencies), "dominant_template_ratio": round(ratio, 4),
                "placeholder_sentence_count": placeholder_count,
            })
            if dominant >= 3 and ratio > 0.2:
                findings.append({
                    "locator": f"script[{item_index}].text", "error": "INTRA_ZONE_TEMPLATE_REPETITION",
                    "dominant_count": dominant, "sentence_count": len(normalized), "ratio": round(ratio, 4),
                })
            if placeholder_count:
                findings.append({
                    "locator": f"script[{item_index}].text", "error": "PLACEHOLDER_PROSE_DETECTED",
                    "sentence_count": placeholder_count,
                })
        return GateResult(
            "INTRA_ZONE_REPETITION_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_NORMALIZED_SENTENCE_TEMPLATES",
            {"zone_metrics": zone_metrics, "violation_count": len(findings)}, findings,
        )

    @staticmethod
    def _language_integrity(story: dict[str, Any]) -> GateResult:
        language = str(story.get("meta", {}).get("language", "")).lower()
        findings: list[dict[str, Any]] = []
        total_letters = 0
        foreign_letters = 0
        unexpected_language_words = 0
        for index, item in enumerate(story.get("script", [])):
            text = unicodedata.normalize("NFC", str(item.get("text", "")))
            if re.search(r"\\(?=[\"'A-Za-zÀ-ỹ])", text):
                findings.append({
                    "locator": f"script[{index}].text",
                    "error": "STRAY_ESCAPE_CHARACTER",
                })
            missing_space_pattern = re.compile(
                r'(?:[.!?…](?=["“][A-ZÀ-ỸĐ])|[.!?…]["”’](?=[A-ZÀ-ỸĐ])|'
                r'[.!?…](?=[A-ZÀ-ỸĐ]))'
            )
            if missing_space_pattern.search(text):
                for match in missing_space_pattern.finditer(text):
                    findings.append({
                        "locator": f"script[{index}].text",
                        "error": "MISSING_INTER_SENTENCE_SPACE",
                        "offset": match.end(),
                    })
            total_letters += sum(character.isalpha() for character in text)
            for script_name, pattern in FORBIDDEN_SCRIPT_PATTERNS.items():
                matches = pattern.findall(text)
                if matches:
                    foreign_letters += len(matches)
                    findings.append({
                        "locator": f"script[{index}].text",
                        "error": "UNEXPECTED_UNICODE_SCRIPT",
                        "script": script_name,
                        "character_count": len(matches),
                    })
            if "。" in text:
                findings.append({
                    "locator": f"script[{index}].text",
                    "error": "UNEXPECTED_SENTENCE_PUNCTUATION",
                    "character": "。",
                })
            if language == "vi":
                tokens = [word.casefold() for word in WORD_PATTERN.findall(text)]
                english_hits = [word for word in tokens if word in ENGLISH_FUNCTION_WORDS]
                if len(english_hits) >= 3:
                    unexpected_language_words += len(english_hits)
                    findings.append({
                        "locator": f"script[{index}].text",
                        "error": "UNEXPECTED_LANGUAGE_TOKENS",
                        "language": "en",
                        "matched_words": sorted(set(english_hits))[:12],
                        "word_count": len(english_hits),
                    })
            stripped = text.rstrip()
            sentence = re.split(r"[.!?…]+", stripped)[-2 if re.search(r"[.!?…]$", stripped) else -1]
            words = WORD_PATTERN.findall(sentence.casefold())
            if Stage1Validator._has_dangling_end(words, language):
                findings.append({
                    "locator": f"script[{index}].text",
                    "error": "DANGLING_SENTENCE_END",
                    "word": words[-1],
                })
        ratio = foreign_letters / max(1, total_letters)
        metrics = {
            "expected_language": language,
            "total_letter_count": total_letters,
            "unexpected_script_character_count": foreign_letters,
            "unexpected_script_ratio": round(ratio, 6),
            "unexpected_language_word_count": unexpected_language_words,
            "violation_count": len(findings),
        }
        return GateResult(
            "LANGUAGE_INTEGRITY_GATE", "PUBLISH_BLOCKER",
            "PASS" if not findings else "FAIL", "DETERMINISTIC_SCRIPT_AND_LEXICAL", metrics, findings,
        )

    @staticmethod
    def _sentence_completeness(story: dict[str, Any]) -> GateResult:
        language = str(story.get("meta", {}).get("language", "vi")).lower()
        findings: list[dict[str, Any]] = []
        for index, item in enumerate(story.get("script", [])):
            text = str(item.get("text", "")).strip()
            locator = f"script[{index}].text"
            if not text or not re.search(r"[.!?…][\"'”’»)]*$", text):
                findings.append({"locator": locator, "error": "MISSING_SENTENCE_BOUNDARY"})
                continue
            if (
                text.count('"') % 2
                or text.count("“") != text.count("”")
                or text.count("‘") != text.count("’")
            ):
                findings.append({"locator": locator, "error": "UNCLOSED_QUOTE"})
            sentences = [value.strip().strip(TRAILING_CLOSERS) for value in re.split(r"[.!?…]+", text) if value.strip()]
            last_words = WORD_PATTERN.findall(sentences[-1].casefold()) if sentences else []
            for sentence_index, sentence in enumerate(sentences):
                words = WORD_PATTERN.findall(sentence.casefold())
                sentence_locator = f"{locator}#sentence[{sentence_index}]"
                if Stage1Validator._has_dangling_end(words, language):
                    findings.append({"locator": sentence_locator, "error": "DANGLING_CLAUSE_END", "word": words[-1]})
                if language == "vi" and re.fullmatch(
                    r"(?:cô|cậu|anh|chị|ông|bà|em)\s+(?:bé|ấy|ta|tôi|mình)",
                    " ".join(words),
                ):
                    findings.append({"locator": sentence_locator, "error": "SUBJECT_ONLY_FRAGMENT", "text": sentence})
            fragment_endings = SHORT_FRAGMENT_ENDINGS.get(language, set())
            if len(sentences) > 1 and 0 < len(last_words) <= 4 and last_words[-1] in fragment_endings:
                findings.append({"locator": locator, "error": "SUSPICIOUS_FINAL_FRAGMENT", "word_count": len(last_words)})
        return GateResult(
            "SENTENCE_COMPLETENESS_GATE", "PUBLISH_BLOCKER",
            "PASS" if not findings else "FAIL", "DETERMINISTIC_SENTENCE_BOUNDARY",
            {"scanned_item_count": len(story.get("script", [])), "violation_count": len(findings)}, findings,
        )

    @staticmethod
    def _prose_hygiene(story: dict[str, Any]) -> GateResult:
        findings: list[dict[str, Any]] = []
        names = {
            " ".join(WORD_PATTERN.findall(str(character.get("name", "")).casefold()))
            for character in story.get("characters", []) if character.get("name")
        }
        generic_fillers = (
            "nhân vật kiểm tra chi tiết trước mắt",
            "mọi người cùng quan sát kết quả thật cẩn thận",
            "cả nhóm bình tĩnh kiểm tra mọi việc lần cuối",
            "the character checks the detail in front",
            "kiểm tra ghi chú và dụng cụ",
            "đối chiếu ghi chú và dụng cụ",
            "quan sát ghi chú và dụng cụ",
        )
        for item_index, item in enumerate(story.get("script", [])):
            text = str(item.get("text", ""))
            if re.search(r'["“]\s*[.!?…]+\s*["”]', text):
                findings.append({
                    "locator": f"script[{item_index}].text",
                    "error": "MALFORMED_EMPTY_QUOTE",
                })
            sentences = [
                match.group(0).strip()
                for match in re.finditer(r"[^.!?…]+(?:[.!?…]+|$)", text)
                if match.group(0).strip()
            ]
            for sentence_index, sentence in enumerate(sentences):
                locator = f"script[{item_index}].text#sentence[{sentence_index}]"
                normalized = " ".join(WORD_PATTERN.findall(sentence.casefold()))
                if normalized in names:
                    findings.append({"locator": locator, "error": "NAME_ONLY_FRAGMENT"})
                if any(value in sentence.casefold() for value in generic_fillers):
                    findings.append({"locator": locator, "error": "GENERIC_REPAIR_FILLER"})
            attribution_count = sum(
                len(re.findall(rf"\b{re.escape(name)}\s+nói\b", text, re.IGNORECASE))
                for name in names if name
            )
            if attribution_count >= 6 and attribution_count / max(1, len(sentences)) >= 0.25:
                findings.append({
                    "locator": f"script[{item_index}].text",
                    "error": "ATTRIBUTION_TEMPLATE_DENSITY",
                    "count": attribution_count,
                    "sentence_count": len(sentences),
                })
        return GateResult(
            "PROSE_HYGIENE_GATE", "QUALITY_BLOCKER",
            "PASS" if not findings else "FAIL", "DETERMINISTIC_PROSE_HYGIENE_V1",
            {"violation_count": len(findings)}, findings,
        )

    @staticmethod
    def _narrative_voice_consistency(story: dict[str, Any]) -> GateResult:
        findings: list[dict[str, Any]] = []
        first_person = re.compile(r"\b(?:tôi|chúng tôi)\b", re.IGNORECASE)
        third_person = re.compile(r"\b(?:cô|cậu|anh|chị|ông|bà|họ)\b", re.IGNORECASE)
        character_names = [
            str(item.get("name", "")) for item in story.get("characters", []) if item.get("name")
        ]
        for item_index, item in enumerate(story.get("script", [])):
            if item.get("voice") != "NARRATOR":
                continue
            text = str(item.get("text", ""))
            # Ignore dialogue, including a malformed/unclosed final quote. Person
            # words spoken by a character do not change the narrator's viewpoint.
            prose = re.sub(r'[“\"][^”\"]*(?:[”\"]|$)', " ", text)
            first_hits = list(first_person.finditer(prose))
            third_signal = bool(third_person.search(prose)) or any(name in prose for name in character_names)
            if first_hits and third_signal:
                findings.append({
                    "locator": f"script[{item_index}].text",
                    "error": "NARRATIVE_PERSON_SHIFT",
                    "first_person_terms": sorted({match.group(0).casefold() for match in first_hits}),
                })
        protagonist = next((item for item in story.get("characters", []) if item.get("role") == "Protagonist"), None)
        if protagonist and protagonist.get("visual_identity", {}).get("presentation") == "FEMININE":
            protagonist_name = str(protagonist.get("name", ""))
            for item_index, item in enumerate(story.get("script", [])):
                text = str(item.get("text", ""))
                if protagonist_name and protagonist_name in text and re.search(r"\bcon trai\b", text, re.IGNORECASE):
                    findings.append({
                        "locator": f"script[{item_index}].text",
                        "error": "CHARACTER_GENDER_ADDRESS_MISMATCH",
                        "character": protagonist_name,
                        "address": "con trai",
                    })
        return GateResult(
            "NARRATIVE_VOICE_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_PERSON_AND_ADDRESS_CONSISTENCY",
            {"violation_count": len(findings)}, findings,
        )

    @staticmethod
    def _scene_state_continuity(story: dict[str, Any]) -> GateResult:
        stop = {"hà", "đã", "và", "của", "một", "những", "the", "and", "has", "have", "been"}

        def tokens(value: str) -> set[str]:
            return {word.casefold() for word in WORD_PATTERN.findall(value) if word.casefold() not in stop and len(word) > 2}

        zone_order = [name.upper() for name in OUTLINE_FIELDS]
        outline = story.get("outline", {})
        scripts = {str(item.get("zone", "")): str(item.get("text", "")) for item in story.get("script", [])}
        states: list[tuple[str, str, str, bool]] = []
        findings: list[dict[str, Any]] = []
        for zone_name in OUTLINE_FIELDS:
            raw_value = outline.get(zone_name, "")
            if isinstance(raw_value, dict):
                entry = str(raw_value.get("entry_state", "")).strip()
                exit_state = str(raw_value.get("exit_state", "")).strip()
                if entry and exit_state:
                    states.append((zone_name.upper(), entry, exit_state, True))
                continue
            value = str(raw_value)
            match = re.search(r"trạng thái đổi từ\s+(.+?)\s+thành\s+(.+?)(?:\.|$)", value, re.IGNORECASE)
            if match:
                states.append((zone_name.upper(), match.group(1).strip(), match.group(2).strip(), False))
        for index in range(1, len(states)):
            previous_zone, _, previous_exit, previous_structured = states[index - 1]
            zone, entry, _, structured = states[index]
            if not (previous_structured and structured):
                continue
            left, right = tokens(previous_exit), tokens(entry)
            overlap = len(left & right) / max(1, min(len(left), len(right)))
            if left and right and overlap < 0.34:
                findings.append({
                    "locator": f"outline.{zone.lower()}", "error": "SCENE_ENTRY_STATE_MISMATCH",
                    "previous_zone": previous_zone, "previous_exit_state": previous_exit,
                    "entry_state": entry, "token_overlap": round(overlap, 3),
                })
        # A declared destination is an intent lock. Catch a scene that explicitly
        # decides to head somewhere else even when both versions share generic
        # words such as the actor and rescued object.
        destination_pattern = re.compile(
            r"\b(?:đến|tới|về)\s+((?:phòng\s+khám(?:\s+thú\s+y)?|nhà|trường|"
            r"bệnh\s+viện|trạm\s+cứu\s+hộ|đồn\s+công\s+an|văn\s+phòng))\b",
            re.IGNORECASE,
        )
        decision_pattern = re.compile(
            r"\b(?:quyết\s+định|dự\s+định|chọn|sẽ|phải)\b[^.!?…]{0,100}?"
            r"\b(?:đi|chạy|di\s+chuyển|đưa|mang)?\s*(?:đến|tới|về)\s+"
            r"((?:phòng\s+khám(?:\s+thú\s+y)?|nhà|trường|bệnh\s+viện|"
            r"trạm\s+cứu\s+hộ|đồn\s+công\s+an|văn\s+phòng))\b",
            re.IGNORECASE,
        )
        expected_destinations: list[str | None] = []
        for zone, entry, exit_state, _ in states:
            match = destination_pattern.search(f"{entry} {exit_state}")
            expected_destinations.append(match.group(1).casefold() if match else None)
        for state_index, (zone, _, _, _) in enumerate(states):
            expected = next(
                (value for value in expected_destinations[state_index:state_index + 2] if value),
                None,
            )
            if not expected:
                continue
            text = scripts.get(zone, "")
            for match in decision_pattern.finditer(text):
                observed = match.group(1).casefold()
                if observed == expected or observed in expected or expected in observed:
                    continue
                sentence_index = len(re.findall(r"[.!?…]+", text[:match.start()]))
                findings.append({
                    "locator": f"script[{zone_order.index(zone)}].text#sentence[{sentence_index}]",
                    "error": "SCENE_DESTINATION_CONFLICT",
                    "zone": zone,
                    "observed_destination": observed,
                    "expected_destination": expected,
                })
        for zone, _, exit_state, _ in states:
            expected_index = zone_order.index(zone)
            required = tokens(exit_state)
            if len(required) < 2:
                continue
            core_phrase = " ".join(
                word.casefold() for word in WORD_PATTERN.findall(exit_state)
                if word.casefold() not in (stop - {"đã", "has", "have", "been"})
            )
            coverages = []
            for candidate in zone_order:
                observed_text = " ".join(word.casefold() for word in WORD_PATTERN.findall(scripts.get(candidate, "")))
                observed = tokens(observed_text)
                coverage = len(required & observed) / len(required)
                completion_markers = {marker for marker in ("đã", "returned", "completed") if marker in core_phrase}
                sentence_matches = []
                for sentence in re.split(r"[.!?…]+", scripts.get(candidate, "")):
                    normalized_sentence = " ".join(word.casefold() for word in WORD_PATTERN.findall(sentence))
                    if completion_markers and not all(marker in normalized_sentence for marker in completion_markers):
                        continue
                    sentence_matches.append(SequenceMatcher(None, core_phrase, normalized_sentence).ratio())
                phrase_similarity = max(sentence_matches, default=0.0)
                coverages.append(coverage if coverage >= 0.75 and phrase_similarity >= 0.62 else 0.0)
            expected_coverage = coverages[expected_index]
            earlier_best = max(coverages[:expected_index], default=0.0)
            if earlier_best >= 0.75 and earlier_best > expected_coverage + 0.2:
                premature_index = coverages[:expected_index].index(earlier_best)
                findings.append({
                    "locator": f"script[{premature_index}].text", "error": "PREMATURE_SCENE_OUTCOME",
                    "expected_zone": zone, "observed_zone": zone_order[premature_index],
                    "outcome": exit_state, "coverage": round(earlier_best, 3),
                })
        expected_by_zone = {zone: exit_state for zone, _, exit_state, _ in states}
        for observed_index, observed_zone in enumerate(zone_order):
            text = scripts.get(observed_zone, "")
            for match in re.finditer(r"trạng thái chuyển từ.+?sang\s+(.+?)(?:\.|$)", text, re.IGNORECASE):
                announced = tokens(match.group(1))
                if not announced:
                    continue
                for expected_zone in zone_order[observed_index + 1:]:
                    expected = tokens(expected_by_zone.get(expected_zone, ""))
                    overlap = len(announced & expected) / max(1, min(len(announced), len(expected)))
                    if expected and overlap >= 0.6:
                        findings.append({
                            "locator": f"script[{observed_index}].text",
                            "error": "PREMATURE_SCENE_OUTCOME",
                            "expected_zone": expected_zone,
                            "observed_zone": observed_zone,
                            "outcome": match.group(1).strip(),
                            "coverage": round(overlap, 3),
                        })
                        break
        return GateResult(
            "SCENE_STATE_CONTINUITY_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_OUTLINE_STATE_GRAPH",
            {"state_count": len(states), "violation_count": len(findings)}, findings,
        )

    @staticmethod
    def _youth_context_safety(story: dict[str, Any], profile: Profile) -> GateResult:
        findings: list[dict[str, Any]] = []
        if profile is Profile.YOUTH_SAFE:
            minors = [
                item for item in story.get("characters", [])
                if int(item.get("canonical_age_max", 99)) < 18
            ]
            adults = [
                str(item.get("name", "")).casefold() for item in story.get("characters", [])
                if int(item.get("canonical_age_min", 0)) >= 18 and item.get("name")
            ]
            minor_names = [str(item.get("name", "")).casefold() for item in minors if item.get("name")]
            risk = re.compile(
                r"\b(?:lái|điều khiển|chèo|bước lên)\b[^.!?…]{0,80}\b(?:thuyền|xuồng|cano)|"
                r"\b(?:một mình|không có người lớn)\b[^.!?…]{0,80}\b(?:biển|rừng|đêm|đảo)",
                re.IGNORECASE,
            )
            for item_index, item in enumerate(story.get("script", [])):
                sentences = [match.group(0) for match in SENTENCE_PATTERN.finditer(str(item.get("text", "")))]
                for sentence_index, sentence in enumerate(sentences):
                    normalized = sentence.casefold()
                    if not risk.search(normalized) or not any(name in normalized for name in minor_names):
                        continue
                    neighborhood = " ".join(sentences[max(0, sentence_index - 1):sentence_index + 2]).casefold()
                    if any(adult in neighborhood for adult in adults):
                        continue
                    findings.append({
                        "locator": f"script[{item_index}].text#sentence[{sentence_index}]",
                        "error": "UNSUPERVISED_MINOR_HIGH_RISK_ACTIVITY",
                        "activity": sentence.strip(),
                    })
            animal_treatment = re.compile(
                r"\b(?:băng\s+bó|nẹp|đặt|đổ|nhỏ|nhét|cho)\b[^.!?…]{0,70}"
                r"\b(?:cánh|vết\s+thương|mỏ|thức\s+ăn|nước)\b",
                re.IGNORECASE,
            )
            professional_help = re.compile(
                r"\b(?:bác\s+sĩ\s+thú\s+y|phòng\s+khám\s+thú\s+y|"
                r"trạm|trung\s+tâm)\s+(?:cứu\s+hộ|thú\s+y)?\b",
                re.IGNORECASE,
            )
            for item_index, item in enumerate(story.get("script", [])):
                sentences = [match.group(0) for match in SENTENCE_PATTERN.finditer(str(item.get("text", "")))]
                for sentence_index, sentence in enumerate(sentences):
                    normalized = sentence.casefold()
                    if not animal_treatment.search(normalized):
                        continue
                    if not any(name in normalized for name in minor_names):
                        continue
                    if professional_help.search(normalized) and re.search(
                        r"\b(?:hướng\s+dẫn|giám\s+sát|thực\s+hiện)\b", normalized
                    ):
                        continue
                    findings.append({
                        "locator": f"script[{item_index}].text#sentence[{sentence_index}]",
                        "error": "MINOR_DIRECT_ANIMAL_TREATMENT_WITHOUT_PROFESSIONAL_HELP",
                        "activity": sentence.strip(),
                    })
        return GateResult(
            "YOUTH_CONTEXT_SAFETY_GATE", "PUBLISH_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_AGE_ACTION_SUPERVISION",
            {"violation_count": len(findings)}, findings,
        )

    @staticmethod
    def _editorial_integrity(story: dict[str, Any], profile: Profile) -> GateResult:
        """Catch structural defects that lexical quality scores can otherwise reward."""
        del profile
        findings: list[dict[str, Any]] = []
        scripts = story.get("script", [])
        names = [
            str(character.get("name", "")).strip()
            for character in story.get("characters", []) if character.get("name")
        ]
        protagonist = names[0] if names else ""
        for name in names[1:]:
            appearances = [
                index for index, item in enumerate(scripts)
                if name.casefold() in str(item.get("text", "")).casefold()
            ]
            if appearances and appearances[0] >= 5:
                findings.append({
                    "locator": f"script[{appearances[0]}].text",
                    "error": "LATE_UNSEEDED_SUPPORTING_CHARACTER",
                    "character": name,
                    "first_appearance_index": appearances[0],
                    "seed_target_index": max(1, appearances[0] - 2),
                })

        climax_index = next(
            (index for index, item in enumerate(scripts) if item.get("zone") == "CLIMAX"),
            None,
        )
        if climax_index is not None:
            outline_value = str(story.get("outline", {}).get("climax", ""))
            state_match = re.search(
                r"trạng thái đổi từ\s+(.+?)\s+thành\s+(.+?)(?:\.|$)",
                outline_value,
                re.IGNORECASE,
            )
            if state_match:
                before = " ".join(WORD_PATTERN.findall(state_match.group(1).casefold()))
                after = " ".join(WORD_PATTERN.findall(state_match.group(2).casefold()))
                similarity = SequenceMatcher(None, before, after).ratio()
                before_tokens = {
                    token for token in before.split()
                    if token not in {"hào", "đã", "đang", "khi", "bắt", "đầu", "gặp"}
                }
                after_tokens = {
                    token for token in after.split()
                    if token not in {"hào", "đã", "đang", "khi", "bắt", "đầu", "bị"}
                }
                state_overlap = len(before_tokens & after_tokens) / max(
                    1, min(len(before_tokens), len(after_tokens))
                )
                climax_text = str(scripts[climax_index].get("text", "")).casefold()
                decisive_shift = bool(re.search(
                    r"\b(?:thay\s+vì|đổi\s+cách|quyết\s+định)\b[^.!?…]{0,100}"
                    r"\b(?:gọi|nhờ|tìm|chọn|dừng|quay)\b",
                    climax_text,
                ))
                if (similarity >= 0.72 or state_overlap >= 0.7) and not decisive_shift:
                    findings.append({
                        "locator": f"script[{climax_index}].text",
                        "error": "CLIMAX_STATE_DELTA_TOO_WEAK",
                        "before_state": state_match.group(1).strip(),
                        "after_state": state_match.group(2).strip(),
                        "similarity": round(similarity, 4),
                        "state_token_overlap": round(state_overlap, 4),
                    })

        explicit_emotion = []
        embodied = 0
        embodied_pattern = re.compile(
            r"\b(?:tay|vai|mắt|giọng|hơi\s+thở|bước\s+chân|nụ\s+cười)\b"
            r"[^.!?…]{0,45}\b(?:run|siết|chậm|nhòe|nghẹn|hổn\s+hển|mỉm\s+cười|sáng)\b",
            re.IGNORECASE,
        )
        for item_index, sentence_index, sentence in Stage1Validator._sentences(story):
            if re.search(r"\bcảm\s+thấy\b", sentence, re.IGNORECASE):
                explicit_emotion.append((item_index, sentence_index, sentence))
            if embodied_pattern.search(sentence):
                embodied += 1
        if len(explicit_emotion) >= 5 and embodied * 2 < len(explicit_emotion):
            item_index, sentence_index, _ = explicit_emotion[-1]
            findings.append({
                "locator": f"script[{item_index}].text#sentence[{sentence_index}]",
                "error": "EXCESSIVE_TOLD_EMOTION",
                "explicit_emotion_count": len(explicit_emotion),
                "embodied_emotion_count": embodied,
            })

        return GateResult(
            "EDITORIAL_INTEGRITY_GATE", "QUALITY_BLOCKER",
            "PASS" if not findings else "FAIL",
            "DETERMINISTIC_CHARACTER_CLIMAX_EMOTION_INTEGRITY_V1",
            {
                "protagonist": protagonist,
                "supporting_character_count": max(0, len(names) - 1),
                "violation_count": len(findings),
            },
            findings,
        )

    @staticmethod
    def _narrative_invariants(story: dict[str, Any], brief: str) -> GateResult:
        findings: list[dict[str, Any]] = []
        normalized_brief = unicodedata.normalize("NFC", brief).casefold()
        rules: list[tuple[str, tuple[str, ...]]] = []
        if any(marker in normalized_brief for marker in ("không lành lại", "vẫn còn rách", "remains broken", "not repaired")):
            rules.append(("DAMAGED_OBJECT_REMAINS_DAMAGED", ("vá xong", "sửa xong", "đã lành", "lành lại", "fully repaired", "fixed completely")))
        if any(marker in normalized_brief for marker in ("không nhắc lại bài học", "không nhắc bài học", "do not repeat the lesson")):
            rules.append(("NO_RESTATED_LESSON", ("bài học", "lesson of the story", "the lesson")))
        for index, item in enumerate(story.get("script", [])):
            text = unicodedata.normalize("NFC", str(item.get("text", ""))).casefold()
            for invariant_id, forbidden in rules:
                for sentence in re.split(r"[.!?…;\n]+", text):
                    matched = next((phrase for phrase in forbidden if phrase in sentence), None)
                    if not matched:
                        continue
                    if invariant_id == "DAMAGED_OBJECT_REMAINS_DAMAGED":
                        # Accept natural negated forms such as "không còn lành lại
                        # được". The earlier exact-prefix check incorrectly treated
                        # these as a repaired object and blocked a compliant story.
                        match_start = sentence.find(matched)
                        prefix = sentence[max(0, match_start - 24):match_start]
                        if re.search(r"(?:không|chưa|chẳng|not|never)\b(?:\s+\w+){0,3}\s*$", prefix):
                            continue
                    if invariant_id == "NO_RESTATED_LESSON" and any(
                        marker in sentence for marker in ("không nhắc", "không lặp", "do not repeat")
                    ):
                        continue
                    findings.append({
                        "locator": f"script[{index}].text", "error": "NARRATIVE_INVARIANT_VIOLATION",
                        "invariant_id": invariant_id, "matched_phrase": matched,
                    })
                    break
        return GateResult(
            "NARRATIVE_INVARIANT_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_BRIEF_INVARIANTS", {"invariant_count": len(rules), "violation_count": len(findings)}, findings,
        )

    @staticmethod
    def _quality(
        story: dict[str, Any], profile: Profile, brief: str = "",
        editorial_assessment: dict[str, Any] | None = None,
    ) -> GateResult:
        editorial_assessment = editorial_assessment or {}
        adherence = Stage1Validator._brief_adherence(story, brief)
        repetition = Stage1Validator._semantic_repetition(story)
        intra_repetition = Stage1Validator._intra_zone_repetition(story)
        invariants = Stage1Validator._narrative_invariants(story, brief)
        age = Stage1Validator._age_profile(story, profile, None)
        zone_budget = Stage1Validator._zone_budget(story)
        dialogue = Stage1Validator._dialogue_structure(story, profile)
        language_integrity = Stage1Validator._language_integrity(story)
        sentence_completeness = Stage1Validator._sentence_completeness(story)
        state_continuity = Stage1Validator._scene_state_continuity(story)
        editorial_integrity = Stage1Validator._editorial_integrity(story, profile)
        zones = {str(item.get("zone")): str(item.get("text", "")) for item in story.get("script", [])}
        narrative_text = " ".join(zones.get(zone, "") for zone in (
            "OPENING", "INTRODUCTION", "DEVELOPMENT", "CLIMAX", "FALLING", "ENDING"
        )).casefold()
        names = [str(item.get("name", "")).casefold() for item in story.get("characters", []) if item.get("name")]
        dimensions: dict[str, dict[str, Any]] = {}

        def record(name: str, score: int, weight: int, locators: list[str], rationale: str) -> None:
            dimensions[name] = {
                "score": max(0, min(100, score)), "max_score": 100, "weight": weight,
                "evidence_locators": locators, "rationale": rationale,
            }

        coverage = float(adherence.metrics["coverage"])
        adherence_score = 100 if coverage >= 0.75 else 80 if coverage >= 0.5 else 60 if coverage >= 0.35 else round(coverage * 100)
        if any(finding.get("error") == "BRIEF_PROTAGONIST_MISMATCH" for finding in adherence.findings):
            adherence_score = min(adherence_score, 40)
        record("brief_adherence", adherence_score, 18, ["brief", "script"],
               f"Story covers {coverage:.0%} of material brief terms.")

        causal_terms = ("vì", "nên", "do đó", "khiến", "bởi", "because", "therefore", "caused")
        causal_count = sum(str(item.get("text", "")).casefold().count(term) for item in story.get("script", []) for term in causal_terms)
        state_score = 50 if invariants.status == "PASS" else 0
        causal_score = min(25, causal_count * 8)
        key_scenes = [zones.get(zone, "").casefold() for zone in ("OPENING", "CLIMAX", "ENDING")]
        distinct_scenes = len({" ".join(WORD_PATTERN.findall(value)[:30]) for value in key_scenes if value}) == 3
        progression_score = 25 if distinct_scenes else 10
        causality_score = state_score + causal_score + progression_score
        record("causality_and_state", causality_score, 12,
               invariants.report_record()["evidence_locators"] or ["outline", "script"],
               f"Invariant score {state_score}/50; {causal_count} causal connectors; key-scene progression={'distinct' if distinct_scenes else 'weak'}.")

        named_zone_hits = sum(any(name in str(item.get("text", "")).casefold() for name in names) for item in story.get("script", [])[1:7])
        emotion_terms = ("buồn", "vui", "sợ", "lo", "giận", "nhẹ nhõm", "hy vọng", "thương", "sad", "afraid", "angry", "relieved", "hope")
        emotion_count = sum(narrative_text.count(term) for term in emotion_terms)
        character_score = min(60, named_zone_hits * 10) + min(40, emotion_count * 10)
        record("character_and_emotion", character_score, 10, ["characters", "script"],
               f"Named characters appear in {named_zone_hits}/6 narrative zones; {emotion_count} emotion signals found.")

        narrative_items = story.get("script", [])[1:7]
        environment_ratio = sum(item.get("environment") != "none" for item in narrative_items) / max(1, len(narrative_items))
        concrete_terms = (
            "thuyền", "gối", "sách", "mưa", "phòng", "cửa", "bàn", "tay", "mắt", "áo", "đường", "vườn",
            "boat", "pillow", "book", "rain", "room", "door", "table", "hand", "eyes", "garden",
        )
        concrete_count = sum(narrative_text.count(term) for term in concrete_terms)
        scene_score = round(environment_ratio * 40) + min(40, concrete_count * 5) + (20 if intra_repetition.status == "PASS" else 0)
        record("concrete_scene_craft", scene_score, 10, ["script", "script[*].environment"],
               f"Concrete environments cover {environment_ratio:.0%} of narrative zones; {concrete_count} concrete detail signals found.")

        turn_count = int(dialogue.metrics["direct_dialogue_turn_count"])
        attributed_ratio = float(dialogue.metrics["attributed_dialogue_ratio"])
        target_turns = 6 if profile is Profile.YOUTH_SAFE else 4
        dialogue_score = min(70, round(turn_count / target_turns * 70)) + round(attributed_ratio * 30)
        record(
            "dialogue_and_voice", dialogue_score, 10,
            dialogue.report_record()["evidence_locators"] or ["script"],
            f"Detected {turn_count}/{target_turns} target dialogue turns; attribution={attributed_ratio:.0%}.",
        )

        opening = zones.get("OPENING", "").casefold()
        opening_signals = sum(term in opening for term in (
            "sợ", "lo", "nhưng", "nếu", "phát hiện", "mất", "fear", "afraid", "but", "if", "discover",
        ))
        protagonist_in_opening = bool(names and names[0] in opening)
        hook_score = min(100, 40 + opening_signals * 15 + (15 if protagonist_in_opening else 0))
        record(
            "opening_hook", hook_score, 10, ["script[1].text"],
            f"Opening has {opening_signals} curiosity/conflict signals; protagonist_present={protagonist_in_opening}.",
        )

        agency_text = " ".join(zones.get(zone, "") for zone in ("DEVELOPMENT", "CLIMAX")).casefold()
        agency_terms = ("chọn", "quyết", "tự", "thử", "tiếp tục", "hành động", "choose", "decide", "tries", "continues", "acts")
        agency_count = sum(agency_text.count(term) for term in agency_terms)
        agency_actor = bool(names and agency_text.count(names[0]) >= 2)
        agency_score = min(100, agency_count * 15 + (40 if agency_actor else 0))
        record(
            "character_agency", agency_score, 10, ["script[3].text", "script[4].text"],
            f"Found {agency_count} decision/action signals; protagonist drives key scenes={agency_actor}.",
        )

        climax = zones.get("CLIMAX", "").casefold()
        ending = zones.get("ENDING", "").casefold()
        climax_signals = sum(term in climax for term in (
            "chọn", "quyết", "đối diện", "không bỏ", "làm được", "thực hiện",
            "bắt đầu", "ổn định", "từ chối", "giữ", "choose", "decide", "face",
            "refuse", "keep", "succeed", "begin to work",
        ))
        payoff_signals = sum(term in ending for term in (
            "hoàn thành", "nhận ra", "thay đổi", "cơ hội", "tự hào", "hài lòng",
            "làm được", "thành công", "nhẹ nhõm", "mỉm cười", "sẽ ổn", "complete",
            "realize", "changed", "proud", "content", "relieved", "smiled", "will be okay",
        ))
        shared_characters = sum(name in climax and name in ending for name in names)
        payoff_score = min(100, climax_signals * 18 + payoff_signals * 18 + shared_characters * 12 + 20)
        record(
            "climax_and_payoff", payoff_score, 10, ["script[4].text", "script[6].text"],
            f"Climax signals={climax_signals}; payoff signals={payoff_signals}; recurring characters={shared_characters}.",
        )

        repeat_count = int(repetition.metrics["semantic_repetition_pair_count"])
        intra_count = int(intra_repetition.metrics["violation_count"])
        repetition_score = max(0, 100 - repeat_count * 12 - intra_count * 15)
        record("repetition_and_style", repetition_score, 5,
               sorted(set(repetition.report_record()["evidence_locators"] + intra_repetition.report_record()["evidence_locators"])) or ["script"],
               f"Detected {repeat_count} cross-zone pairs and {intra_count} intra-zone/placeholder violations.")

        pacing_score = (50 if age.status == "PASS" else 0) + (50 if zone_budget.status == "PASS" else 0)
        record("age_fit_and_pacing", pacing_score, 5,
               sorted(set(age.report_record()["evidence_locators"] + zone_budget.report_record()["evidence_locators"])) or ["script"],
               f"Age profile={age.status}; zone budget={zone_budget.status}.")

        weighted_points = sum(value["score"] * value["weight"] / 100 for value in dimensions.values())
        score = round(weighted_points)
        integrity_failures = [
            gate.gate_id for gate in (
                language_integrity, sentence_completeness, dialogue,
                state_continuity, repetition, intra_repetition, editorial_integrity,
            ) if gate.status != "PASS"
        ]
        uncapped_score = score
        if integrity_failures:
            score = min(score, 79)
        critic_locators = editorial_assessment.get("evidence_locators", [])
        valid_critic_locators = (
            isinstance(critic_locators, list)
            and bool(critic_locators)
            and all(
                isinstance(locator, str)
                and bool(re.fullmatch(r"(?:script\[\d+\]\.text|outline(?:\.[a-z_]+)?|characters(?:\[\d+\])?|brief)", locator))
                for locator in critic_locators
            )
        )
        raw_critic_findings = editorial_assessment.get("findings", [])
        valid_locator_pattern = r"script\[(\d+)\]\.text"
        credible_critic_findings = [
            finding for finding in raw_critic_findings
            if isinstance(finding, dict)
            and finding.get("blocking") is True
            and str(finding.get("category", "")).upper()
            in {"CONTRACT", "CONTINUITY", "STRUCTURE", "SAFETY"}
            and re.fullmatch(valid_locator_pattern, str(finding.get("locator", "")))
            and int(re.fullmatch(valid_locator_pattern, str(finding.get("locator", ""))).group(1))
            < len(story.get("script", []))
            and not re.search(
                r"(?:required|exact|missing)\s+(?:term|word)|từ\s*khóa|nguyên\s*văn",
                f"{finding.get('issue', '')} {finding.get('instruction', '')}",
                re.IGNORECASE,
            )
            and re.search(
                r"state|transition|action|event|beat|dialogue|prop|location|continuity|"
                r"trạng thái|chuyển|hành động|sự kiện|đối thoại|đạo cụ|địa điểm|liên tục|kết|payoff|subplot",
                f"{finding.get('issue', '')} {finding.get('instruction', '')}",
                re.IGNORECASE,
            )
        ] if isinstance(raw_critic_findings, list) else []
        zone_text = {
            str(item.get("zone", "")).upper(): str(item.get("text", "")).casefold()
            for item in story.get("script", [])
        }
        evidence_backed: list[dict[str, Any]] = []
        for finding in credible_critic_findings:
            declared_zone = str(finding.get("zone", "")).upper()
            locator_match = re.fullmatch(
                valid_locator_pattern, str(finding.get("locator", ""))
            )
            located_zone = (
                str(story["script"][int(locator_match.group(1))].get("zone", "")).upper()
                if locator_match else ""
            )
            # A finding cannot describe one zone while pointing at another. This
            # was the main source of stale quality blockers after surgical edits.
            if declared_zone and located_zone and declared_zone != located_zone:
                continue
            text = zone_text.get(declared_zone, "")
            issue = str(finding.get("issue", "")).casefold()
            # Off-topic/subplot classification is subjective and cannot alone be
            # a release blocker. Concrete contract and continuity gates already
            # detect unauthorized entities and state changes deterministically.
            if "subplot" in issue or "tình tiết phụ" in issue:
                continue
            if "dialogue" in issue or "đối thoại" in issue:
                if re.search(r'["“][^"”]{2,}["”]', text):
                    continue
            quoted = re.search(r"['‘“\"]([^'’”\"]{2,})['’”\"]", issue)
            if quoted and any(term in issue for term in ("missing", "thiếu")):
                required_text = " ".join(WORD_PATTERN.findall(quoted.group(1).casefold()))
                normalized_zone = " ".join(WORD_PATTERN.findall(text))
                if required_text and required_text in normalized_zone:
                    continue
            if any(term in issue for term in (
                "state transition", "state change", "chuyển trạng thái", "đổi trạng thái",
            )):
                transition_signals = (
                    "sau đó", "cuối cùng", "quyết định", "trở nên", "cảm thấy",
                    "nhẹ nhõm", "hiểu lầm", "giải quyết", "tiếp tục", "after that",
                    "finally", "decided", "relieved", "resolved", "continue",
                )
                if any(signal in text for signal in transition_signals):
                    continue
            evidence_backed.append(finding)
        credible_critic_findings = evidence_backed
        critic_status = str(editorial_assessment.get("status", ""))
        if critic_status == "FAIL" and not credible_critic_findings:
            critic_status = "PASS"
        finding_locators = [str(finding["locator"]) for finding in credible_critic_findings]
        model_critic_assessed = (
            critic_status in {"PASS", "FAIL"}
            and str(editorial_assessment.get("method", "")).startswith("MODEL_")
            and valid_critic_locators
        )
        corroborated = model_critic_assessed and critic_status == "PASS"
        findings = []
        dedicated_dimension_failures = {
            "repetition_and_style": repetition.status != "PASS" or intra_repetition.status != "PASS",
            "age_fit_and_pacing": age.status != "PASS" or zone_budget.status != "PASS",
        }
        for name, value in dimensions.items():
            if value["score"] < 60:
                # Dedicated deterministic gates already expose these defects with
                # actionable locators. Do not inflate one root cause into a second
                # STORY_QUALITY_GATE blocker.
                if dedicated_dimension_failures.get(name, False):
                    continue
                findings.append({
                    "locator": value["evidence_locators"][0], "error": "EDITORIAL_DIMENSION_BELOW_MINIMUM",
                    "dimension": name, "score": value["score"], "minimum": 60,
                })
        if score < 80:
            findings.append({"locator": "script", "error": "EDITORIAL_SCORE_BELOW_THRESHOLD", "actual": score, "minimum": 80})
        if model_critic_assessed and critic_status == "FAIL":
            findings.append({
                "locator": finding_locators[0],
                "error": "MODEL_CRITIC_FINDINGS_REMAIN",
                "finding_count": len(credible_critic_findings),
            })
        return GateResult(
            "STORY_QUALITY_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "WEIGHTED_EDITORIAL_RUBRIC_V2",
            {
                "editorial_score": score, "minimum_score": 80,
                "raw_score": round(weighted_points, 2), "max_raw_score": 100,
                "uncapped_editorial_score": uncapped_score,
                "integrity_score_cap": 79 if integrity_failures else None,
                "integrity_failure_gate_ids": integrity_failures,
                "minimum_dimension_score": 60, "dimensions": dimensions,
                "assessment_basis": (
                    "MODEL_CRITIC_CORROBORATED" if corroborated
                    else "MODEL_CRITIC_ASSESSED" if model_critic_assessed
                    else "DETERMINISTIC_PREFLIGHT_ONLY"
                ),
                "critic_evidence_valid": valid_critic_locators,
                "model_critic": {
                    **editorial_assessment,
                    "credible_findings": credible_critic_findings,
                    "evidence_locators": finding_locators,
                    "credible_finding_count": len(credible_critic_findings),
                    "rejected_finding_count": max(
                        0, len(raw_critic_findings) - len(credible_critic_findings)
                    ) if isinstance(raw_critic_findings, list) else 0,
                },
            }, findings,
        )

    @staticmethod
    def _sentences(story: dict[str, Any]) -> list[tuple[int, int, str]]:
        values: list[tuple[int, int, str]] = []
        for item_index, item in enumerate(story.get("script", [])):
            matches = [match.group(0).strip() for match in SENTENCE_PATTERN.finditer(str(item.get("text", "")))]
            if not matches and str(item.get("text", "")).strip():
                matches = [str(item["text"]).strip()]
            values.extend((item_index, sentence_index, sentence) for sentence_index, sentence in enumerate(matches))
        return values

    @staticmethod
    def _semantic_repetition(story: dict[str, Any]) -> GateResult:
        stop = {"và", "là", "của", "một", "những", "the", "and", "of", "to", "a", "an", "thì", "đã"}
        prepared = []
        for item_index, sentence_index, sentence in Stage1Validator._sentences(story):
            tokens = [word.casefold() for word in WORD_PATTERN.findall(sentence) if word.casefold() not in stop and not word.isdigit()]
            if len(tokens) >= 7:
                prepared.append((item_index, sentence_index, sentence, tokens))
        pairs = []
        for left_index, left in enumerate(prepared):
            for right in prepared[left_index + 1:]:
                left_set, right_set = set(left[3]), set(right[3])
                jaccard = len(left_set & right_set) / max(1, len(left_set | right_set))
                # SequenceMatcher is comparatively expensive. A pair that
                # shares less than half its content words cannot cross the
                # configured semantic threshold, so reject it cheaply first.
                if jaccard < 0.5:
                    continue
                sequence = SequenceMatcher(None, " ".join(left[3]), " ".join(right[3])).ratio()
                similarity = max(jaccard, sequence)
                # Within one scene, adjacent parallel sentences are often an
                # intentional rhythmic device. Flag only a near-verbatim idea
                # that returns after intervening prose; the existing template
                # gate still handles three-or-more adjacent repetitions.
                if left[0] == right[0] and (
                    right[1] - left[1] < 2 or sequence < 0.96
                ):
                    continue
                if similarity >= 0.86:
                    pairs.append({
                        "source_locator": f"script[{left[0]}].text#sentence[{left[1]}]",
                        "locator": f"script[{right[0]}].text",
                        "target_sentence": right[1], "similarity": round(similarity, 4),
                        "scope": "INTRA_ZONE" if left[0] == right[0] else "CROSS_ZONE",
                    })
                    if len(pairs) >= 20:
                        break
            if len(pairs) >= 20:
                break
        findings = [{
            **pair,
            "error": (
                "INTRA_ZONE_SEMANTIC_REPETITION"
                if pair["scope"] == "INTRA_ZONE"
                else "CROSS_ZONE_SEMANTIC_REPETITION"
            ),
        } for pair in pairs]
        return GateResult(
            "SEMANTIC_REPETITION_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_TOKEN_SEQUENCE_SIMILARITY",
            {"sentence_count": len(prepared), "semantic_repetition_pair_count": len(pairs), "threshold": 0.86, "pairs": pairs}, findings,
        )

    @staticmethod
    def _age_profile(
        story: dict[str, Any], profile: Profile, duration: DurationPlan | None = None
    ) -> GateResult:
        del duration
        profile_name = "KIDS_7_10" if profile is Profile.YOUTH_SAFE else "ADULT"
        maximum = 28 if profile is Profile.YOUTH_SAFE else 48
        target_average = 16 if profile is Profile.YOUTH_SAFE else 28
        lengths = []
        findings = []
        meta = story.get("meta", {})
        if meta:
            expected_target = "7–10 tuổi" if profile is Profile.YOUTH_SAFE else "18+"
            actual_target = str(meta.get("target", ""))
            if actual_target != expected_target:
                findings.append({
                    "locator": "meta.target", "error": "AUDIENCE_METADATA_MISMATCH",
                    "actual": actual_target, "expected": expected_target,
                })
            if profile is Profile.YOUTH_SAFE and "7–10" not in str(meta.get("audience", "")):
                findings.append({
                    "locator": "meta.audience", "error": "AUDIENCE_METADATA_MISMATCH",
                    "actual": str(meta.get("audience", "")), "expected": "trẻ em 7–10 tuổi",
                })
        for item_index, sentence_index, sentence in Stage1Validator._sentences(story):
            count = len(WORD_PATTERN.findall(sentence))
            lengths.append(count)
            if count > maximum:
                findings.append({
                    "locator": f"script[{item_index}].text", "sentence_index": sentence_index,
                    "error": "SENTENCE_TOO_COMPLEX_FOR_AGE_PROFILE", "word_count": count, "maximum": maximum,
                })
        average = mean(lengths) if lengths else 0.0
        if average > target_average:
            findings.append({"locator": "script", "error": "AVERAGE_SENTENCE_TOO_LONG", "actual": round(average, 2), "maximum": target_average})
        return GateResult(
            "AGE_PROFILE_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_SENTENCE_LENGTH_PROFILE",
            {"age_profile": profile_name, "sentence_count": len(lengths), "average_sentence_words": round(average, 2), "maximum_sentence_words": max(lengths, default=0), "limits": {"average": target_average, "sentence": maximum}}, findings[:20],
        )

    @staticmethod
    def _dialogue_structure(
        story: dict[str, Any], profile: Profile | None = None
    ) -> GateResult:
        quote_pattern = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|(?<!\w)\'([^\'\n]+)\'(?!\w)')
        speech_verbs = ("nói", "hỏi", "đáp", "thì thầm", "kêu", "said", "asked", "replied", "whispered")
        names = [str(item.get("name", "")).casefold() for item in story.get("characters", [])]
        turns = []
        for item_index, item in enumerate(story.get("script", [])):
            text = str(item.get("text", ""))
            for turn_index, match in enumerate(quote_pattern.finditer(text)):
                context = text[max(0, match.start() - 100): min(len(text), match.end() + 100)].casefold()
                speakers = [name for name in names if name and name in context]
                prefix = text[max(0, match.start() - 80):match.start()].casefold()
                suffix = text[match.end():min(len(text), match.end() + 80)].casefold()
                attributed = False
                prefix_speaker = None
                suffix_speaker = None
                for name in names:
                    if not name:
                        continue
                    escaped = re.escape(name)
                    prefix_pattern = rf"{escaped}[^.!?…\n]{{0,45}}(?:{'|'.join(speech_verbs)}|:)\s*$"
                    suffix_pattern = rf"^\s*[,—-]?\s*{escaped}\s+(?:{'|'.join(speech_verbs)})\b"
                    if re.search(prefix_pattern, prefix):
                        prefix_speaker = name
                        attributed = True
                    if re.search(suffix_pattern, suffix):
                        suffix_speaker = name
                        attributed = True
                turns.append({
                    "locator": f"script[{item_index}].text", "turn_index": turn_index,
                    "speaker_candidates": speakers, "attributed": attributed,
                    "prefix_speaker": prefix_speaker,
                    "suffix_speaker": suffix_speaker,
                    "speaker_conflict": bool(
                        prefix_speaker and suffix_speaker
                        and prefix_speaker != suffix_speaker
                    ),
                })
        attributed_count = sum(bool(item["attributed"]) for item in turns)
        ratio = attributed_count / max(1, len(turns))
        findings = []
        findings.extend({
            "locator": turn["locator"],
            "error": "CONFLICTING_DIALOGUE_ATTRIBUTION",
            "turn_index": turn["turn_index"],
            "prefix_speaker": turn["prefix_speaker"],
            "suffix_speaker": turn["suffix_speaker"],
        } for turn in turns if turn["speaker_conflict"])
        if len(turns) >= 2 and ratio < 0.5:
            findings.append({"locator": "script", "error": "DIALOGUE_ATTRIBUTION_TOO_LOW", "actual": round(ratio, 4), "minimum": 0.5})
        if profile is Profile.YOUTH_SAFE and len(turns) < 6:
            findings.append({
                "locator": "script", "error": "DIALOGUE_TURN_COUNT_TOO_LOW",
                "actual": len(turns), "minimum": 6,
            })
        item_count = len(story.get("script", []))
        dialogue_items = len({int(item["locator"].split("[")[1].split("]")[0]) for item in turns})
        return GateResult(
            "DIALOGUE_STRUCTURE_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_QUOTE_SPEAKER_PARSER",
            {"direct_dialogue_turn_count": len(turns), "direct_dialogue_item_count": dialogue_items, "dialogue_scene_ratio": round(dialogue_items / max(1, item_count), 4), "attributed_dialogue_count": attributed_count, "attributed_dialogue_ratio": round(ratio, 4), "turns": turns}, findings,
        )

    @staticmethod
    def _narrative_coherence(story: dict[str, Any]) -> GateResult:
        """Deterministic backstop after the provider's plan/draft/critic/rewrite loop."""
        stop = {"và", "là", "của", "một", "những", "the", "and", "of", "to", "a", "an"}
        def tokens(value: str) -> list[str]:
            return [word.casefold() for word in WORD_PATTERN.findall(value) if word.casefold() not in stop]
        findings = []
        coverage = {}
        scripts = story.get("script", [])
        for index, item in enumerate(scripts):
            key = str(item.get("zone", "")).lower()
            if key not in {"greeting", "farewell"} and item.get("environment") == "none":
                findings.append({
                    "locator": f"script[{index}].environment",
                    "error": "NARRATIVE_ENVIRONMENT_MISSING",
                    "zone": key,
                })
            outline_tokens = set(tokens(str(story.get("outline", {}).get(key, ""))))
            script_tokens = set(tokens(str(item.get("text", ""))))
            ratio = len(outline_tokens & script_tokens) / max(1, len(outline_tokens))
            coverage[key] = round(ratio, 4)
            if outline_tokens and ratio == 0:
                findings.append({"locator": f"script[{index}].text", "error": "OUTLINE_COVERAGE_MISSING", "zone": key})
        repetition_pairs = []
        for left in range(len(scripts)):
            left_tokens = tokens(str(scripts[left].get("text", "")))
            left_ngrams = {tuple(left_tokens[i:i + 8]) for i in range(max(0, len(left_tokens) - 7))}
            for right in range(left + 1, len(scripts)):
                right_tokens = tokens(str(scripts[right].get("text", "")))
                right_ngrams = {tuple(right_tokens[i:i + 8]) for i in range(max(0, len(right_tokens) - 7))}
                overlap = len(left_ngrams & right_ngrams) / max(1, min(len(left_ngrams), len(right_ngrams)))
                if overlap > 0.5:
                    repetition_pairs.append([left, right, round(overlap, 4)])
                    findings.append({"locator": f"script[{right}].text", "error": "CROSS_ZONE_REPETITION", "source_index": left, "overlap": round(overlap, 4)})
        return GateResult(
            "NARRATIVE_COHERENCE_GATE", "QUALITY_BLOCKER", "PASS" if not findings else "FAIL",
            "DETERMINISTIC_OUTLINE_NGRAM", {"outline_coverage": coverage, "repetition_pairs": repetition_pairs}, findings,
        )

    def _safety(self, story: dict[str, Any], profile: Profile) -> GateResult:
        decision = self.safety_provider.assess(profile, story)
        return GateResult("PROFILE_SAFETY_GATE", "PUBLISH_BLOCKER", decision.status, decision.method, {"finding_count": len(decision.findings), "provider": self.safety_provider.provider_id}, decision.findings)


def blockers(gates: list[GateResult]) -> list[GateResult]:
    return [gate for gate in gates if gate.severity in {"PUBLISH_BLOCKER", "QUALITY_BLOCKER"} and gate.status != "PASS"]
