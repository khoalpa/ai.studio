from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

from ..models import Profile
from .config import DurationPlan, stage1_config
from .png import character_card_png


class StoryProvider(Protocol):
    provider_id: str

    def generate(self, profile: Profile, brief: str, duration: DurationPlan, language: str) -> dict[str, Any]: ...

    def repair(self, story: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]: ...


class CharacterImageProvider(Protocol):
    provider_id: str

    def generate(self, character: dict[str, Any]) -> tuple[bytes, str]: ...


@dataclass(frozen=True)
class SafetyDecision:
    status: str
    findings: list[dict[str, Any]]
    method: str


class SafetyProvider(Protocol):
    provider_id: str

    def assess(self, profile: Profile, story: dict[str, Any]) -> SafetyDecision: ...


class DeterministicStoryProvider:
    """Brief-grounded offline story generator for workflow tests and local development."""

    provider_id = "deterministic-story-provider/1.0"
    _word_pattern = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*", re.UNICODE)

    def generate(self, profile: Profile, brief: str, duration: DurationPlan, language: str) -> dict[str, Any]:
        topic = " ".join(brief.split()) or "một lời hứa nhỏ"
        youth = profile is Profile.YOUTH_SAFE
        context = self._brief_context(topic, language, youth)
        protagonist = context["protagonist"]
        companion = context["companion"]
        companion_is_parent = companion.casefold() in {"mẹ", "mother"}
        companion_age = 35 if companion_is_parent else (context["age"] if youth else context["age"] + 1)
        characters = [
            {
                "character_id": self._slug(protagonist),
                "name": protagonist,
                "role": "nhân vật chính",
                "canonical_age_min": context["age"],
                "canonical_age_max": context["age"],
                "adult_visual_eligibility": "NOT_ADULT" if youth else "VERIFIED_ADULT",
                "visual_story_importance": "PRIMARY",
                "identity_traits": ["mái tóc đen ngang vai", "ánh mắt chăm chú", "áo vàng nhạt"],
                "visual_identity": {"presentation": context["presentation"], "hair": "tóc đen ngang vai", "wardrobe": "áo vàng nhạt hiện đại", "palette": ["yellow", "blue"], "silhouette": "học sinh nhỏ gọn" if youth else "người trưởng thành thanh mảnh", "cultural_context": "Việt Nam đương đại"},
            },
            {
                "character_id": self._slug(companion),
                "name": companion,
                "role": "mẹ" if companion_is_parent else "người đồng hành",
                "canonical_age_min": companion_age,
                "canonical_age_max": companion_age,
                "adult_visual_eligibility": "VERIFIED_ADULT" if companion_is_parent or not youth else "NOT_ADULT",
                "visual_story_importance": "SECONDARY",
                "identity_traits": ["tóc nâu gọn", "nụ cười ấm", "áo khoác màu đất"] if companion_is_parent else ["tóc nâu gọn", "nụ cười ấm", "ba lô màu đất"],
                "visual_identity": {
                    "presentation": "FEMININE" if companion_is_parent else "ANDROGYNOUS",
                    "hair": "tóc nâu gọn",
                    "wardrobe": "trang phục người lớn hiện đại" if companion_is_parent else "trang phục học sinh hiện đại",
                    "palette": ["earth", "green"],
                    "silhouette": "người mẹ trưởng thành" if companion_is_parent else "trẻ em năng động",
                    "cultural_context": "Việt Nam đương đại",
                },
            },
        ]
        zones = stage1_config()["zones"]
        environments = (
            ["none", "bedroom_warm", "bedroom_warm", "bedroom_warm", "bedroom_warm", "school_hallway", "bedroom_warm", "none"]
            if context.get("scenario") == "STORM_EVACUATION"
            else ["none", "school_hallway", "library_soft", "school_hallway", "school_hallway", "garden_morning", "bedroom_warm", "none"]
        )
        bookend = min(44, max(28, duration.target_words // 24))
        narrative_target = max(60, (duration.target_words - bookend * 2) // 6)
        budgets = [bookend, narrative_target, narrative_target, narrative_target, narrative_target, narrative_target, narrative_target, bookend]
        script = []
        for index, zone in enumerate(zones):
            text = self._zone_text(zone, context, budgets[index], language)
            script.append(
                {
                    "zone": zone,
                    "environment": environments[index],
                    "voice": "NARRATOR",
                    "speed": "NORMAL" if zone not in {"CLIMAX", "FALLING"} else ("FAST" if zone == "CLIMAX" else "SLOW"),
                    "lang": language.upper(),
                    "text": text,
                }
            )
        title = context["title"]
        channel = stage1_config()["channels"][profile.value]
        if context.get("scenario") == "STORM_EVACUATION":
            outline = {
                "greeting": f"Người kể mời khán giả theo chân {protagonist} chuẩn bị trước bão.",
                "opening": f"Bão tiến gần {context['place']} và gia đình phải sơ tán đúng hạn.",
                "introduction": f"Mẹ chia cho {protagonist} những việc an toàn, phù hợp với tuổi.",
                "development": f"{protagonist} cất giấy tờ và di chuyển vật dụng trong khi Mẹ bảo vệ ngôi nhà.",
                "climax": f"Khi có lệnh sơ tán, {protagonist} nhờ Mẹ xử lý chỗ nguy hiểm rồi cả hai rời nhà.",
                "falling": "Hai mẹ con kiểm tra đủ người và đồ thiết yếu trên đường đến nơi trú.",
                "ending": "Gia đình đến nơi trú an toàn trước khi bão đổ bộ.",
                "farewell": "Người kể tạm biệt gia đình ở nơi trú an toàn.",
            }
        elif context.get("scenario") == "LOST_BIRD_RETURN":
            outline = {
                "greeting": "Người kể mở câu chuyện về hai chị em và chú chim non.",
                "opening": "Hai chị em phát hiện chim non bị lạc dưới gốc cây trước cơn mưa.",
                "introduction": "Hai em nhờ người lớn giúp thay vì tự trèo cây.",
                "development": "Người lớn kiểm tra tổ và chuẩn bị cách đưa chim lên an toàn.",
                "climax": "Người lớn đặt chim non vào tổ khi hai chị em đứng ở nơi an toàn.",
                "falling": "Chim non trở lại tổ trước khi mưa lớn.",
                "ending": "Hai chị em về nhà sau khi chắc chắn chim đã an toàn.",
                "farewell": "Người kể tạm biệt hai chị em và chú chim non trong tổ.",
            }
        elif context.get("scenario") == "TORN_BOAT_GRIEF":
            outline = {
                "greeting": "Người kể giới thiệu Bo và chiếc thuyền giấy tự gấp.",
                "opening": "Mưa làm chiếc thuyền của Bo mềm và rách.",
                "introduction": "Bo mang thuyền vào phòng gối xanh và để Mẹ ngồi bên.",
                "development": "Bo từ chối thuyền thay thế vì muốn giữ chiếc thuyền cũ.",
                "climax": "Bo xin Mẹ ôm rồi chọn giữ vết rách thay vì che giấu nỗi buồn.",
                "falling": "Hai mẹ con đặt thuyền lên bến khô cạnh gối vịt và trang sách.",
                "ending": "Bo giữ chiếc thuyền còn vết rách; thuyền không lành lại.",
                "farewell": "Người kể tạm biệt Bo và Mẹ bên dòng sông bằng trang sách.",
            }
        else:
            outline = {
                "greeting": f"Người kể mời khán giả theo dõi thử thách của {protagonist}.",
                "opening": f"{protagonist} chuẩn bị {context['goal']} nhưng nỗi sợ xuất hiện.",
                "introduction": f"{companion} giúp {protagonist} chia mục tiêu thành những bước nhỏ.",
                "development": f"{protagonist} luyện tập, vấp váp và học cách tiếp tục.",
                "climax": f"{protagonist} đối diện {context['fear']} và tự mình lựa chọn hành động.",
                "falling": f"{protagonist} bình tĩnh nhìn lại kết quả cùng {companion}.",
                "ending": f"{protagonist} hoàn thành {context['goal']} bằng lòng can đảm.",
                "farewell": "Người kể tạm biệt và giữ lại niềm vui của một bước tiến thật sự.",
            }
        return {
            "schema_version": "2.3",
            "meta": {
                "title": title,
                "series": title,
                "episode": "1",
                "author": "An Nhiên",
                "channel": channel,
                "target": "7–10 tuổi" if youth else "18+",
                "audience": "trẻ em 7–10 tuổi" if youth else "người trưởng thành",
                "genre": "phiêu lưu chữa lành" if youth else "tâm lý chữa lành",
                "language": language,
                "tone": ["ấm áp", "hồi hộp có kiểm soát"],
                "tags": context["tags"],
                "story_quality_commitment": None,
            },
            "characters": characters,
            "outline": outline,
            "script": script,
        }

    @classmethod
    def _brief_context(cls, brief: str, language: str, youth: bool) -> dict[str, Any]:
        if language == "en":
            match = re.match(r"\s*([A-Z][A-Za-z'-]+)", brief)
            name = match.group(1) if match else "Alex"
            return {"protagonist": name, "companion": "Sam", "age": 10 if youth else 28,
                    "presentation": "ANDROGYNOUS", "goal": "the goal described in the brief",
                    "fear": "the central obstacle", "place": "the familiar neighborhood",
                    "brief": brief, "title": f"{name}'s Brave Step",
                    "tags": ["courage", "friendship", "practice", "choice"]}
        match = re.match(r"\s*([A-ZÀ-Ỹ][^,\s]*),", brief)
        candidates = re.findall(r"\b[A-ZÀ-Ỹ][a-zà-ỹđ]+\b", brief)
        ignored = {"Chào", "Mưa", "Chiếc", "Thuyền", "Nhưng", "Nếu", "Một", "Hai", "Ba"}
        repeated = sorted(
            ((candidates.count(value), value) for value in set(candidates) if value not in ignored),
            reverse=True,
        )
        name = match.group(1) if match else (repeated[0][1] if repeated and repeated[0][0] >= 2 else "An")
        grade = re.search(r"lớp\s+(\d+)", brief, re.IGNORECASE)
        age = int(grade.group(1)) + 5 if grade and youth else (10 if youth else 28)
        goal_match = re.search(r"quyết tâm\s+(.+?)(?:\.|,\s*nhưng|\s+nhưng)", brief, re.IGNORECASE)
        goal = goal_match.group(1).strip() if goal_match else "hoàn thành mục tiêu trong đề bài"
        fear_match = re.search(r"(?:nỗi sợ|sợ)\s+(.+?)(?:\.|,|$)", brief, re.IGNORECASE)
        fear = f"nỗi sợ {fear_match.group(1).strip()}" if fear_match else "nỗi sợ thất bại"
        place_match = re.search(r"\sở\s+(.+?)(?:,|\.)", brief, re.IGNORECASE)
        place = place_match.group(1).strip() if place_match else "một khu phố Việt Nam"
        presentation = "FEMININE" if re.search(r"\b(cô|bé gái|nữ sinh)\b", brief, re.IGNORECASE) else "ANDROGYNOUS"
        subject = "Bức Tranh" if "vẽ" in brief.casefold() else "Bước Tiến"
        companion = "Mẹ" if re.search(r"\bmẹ\b", brief, re.IGNORECASE) else "Minh"
        normalized_brief = brief.casefold()
        scenario = (
            "STORM_EVACUATION"
            if "bão" in normalized_brief and any(
                marker in normalized_brief for marker in ("sơ tán", "ngôi nhà", "an toàn")
            )
            else "LOST_BIRD_RETURN"
            if "chim non" in normalized_brief and "tổ" in normalized_brief
            else "TORN_BOAT_GRIEF"
            if "thuyền" in normalized_brief and any(
                marker in normalized_brief for marker in ("rách", "vết rách")
            )
            else "GENERAL"
        )
        if scenario == "LOST_BIRD_RETURN":
            companion = "Mẹ"
        return {"protagonist": name, "companion": companion, "age": age,
                "presentation": presentation, "goal": goal, "fear": fear, "place": place,
                "brief": brief, "title": f"{name} và {subject} Can Đảm",
                "scenario": scenario,
                "tags": ["an toàn", "gia đình", "bão", "sơ tán"] if scenario == "STORM_EVACUATION" else ["can đảm", "luyện tập", "tình bạn", "trưởng thành"]}

    @staticmethod
    def _slug(value: str) -> str:
        normalized = unicodedata.normalize("NFD", value.casefold())
        ascii_value = "".join(character for character in normalized if unicodedata.category(character) != "Mn")
        return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-") or "character"

    @classmethod
    def _zone_text(cls, zone: str, context: dict[str, Any], target_words: int, language: str) -> str:
        if language == "en":
            return cls._fit_zone(cls._english_beats(zone, context), target_words, zone, context, language)
        name, friend = context["protagonist"], context["companion"]
        goal, fear, place = context["goal"], context["fear"], context["place"]
        if context.get("scenario") == "STORM_EVACUATION":
            storm_beats = {
                "GREETING": [f"Xin chào, hôm nay chúng ta theo chân {name} chuẩn bị trước một cơn bão lớn.", "Mời bạn cùng lắng nghe câu chuyện về sự bình tĩnh và an toàn."],
                "OPENING": [f"Mây đen phủ trên {place} khi bản tin báo cơn bão đang tiến gần.", f"Gió mỗi lúc một mạnh khiến {name} thấy sợ.", "Mẹ nhắc rằng hai mẹ con phải bảo vệ ngôi nhà rồi sơ tán trước giờ quy định.", f"{name} nhìn danh sách việc cần làm và quyết định bắt đầu ngay."],
                "INTRODUCTION": [f"Mẹ kiểm tra cửa sổ rồi giao cho {name} những việc an toàn.", f'"Con sẽ cất giấy tờ và đồ kỷ niệm lên cao," {name} nói.', '"Mẹ sẽ đóng cửa và ngắt các thiết bị cần thiết," Mẹ đáp.', "Hai mẹ con đánh dấu từng việc trên danh sách sơ tán.", f"{name} biết mình phải gọi mẹ nếu gặp vật nặng hoặc chỗ nguy hiểm."],
                "DEVELOPMENT": [f"{name} di chuyển những vật dụng giá trị vào chiếc hộp chống ẩm.", "Em cất giấy tờ, ảnh gia đình và thuốc cần thiết vào túi mang theo.", '"Con nghe gió mạnh hơn rồi," em nói.', '"Mình tiếp tục theo danh sách, nhưng tránh xa cửa kính nhé," Mẹ đáp.', "Mẹ chằng cửa và đưa các chậu cây nhẹ vào trong nhà.", f"Một tiếng gió rít làm {name} khựng lại, nhưng em hít chậm rồi báo cho mẹ.", "Hai mẹ con cùng kiểm tra nước uống, đèn pin và số điện thoại khẩn cấp."],
                "CLIMAX": ["Mưa bắt đầu quất vào mái hiên khi loa phường phát lệnh sơ tán.", f"{name} nhớ ra hộp ảnh còn ở chiếc kệ thấp gần cửa sổ.", '"Mẹ ơi, hộp ảnh vẫn ở gần cửa kính," em gọi.', '"Con đứng ở đây, mẹ sẽ lấy nó," Mẹ nói.', "Em không tự chạy vào vùng kính rung mà gọi mẹ đến giúp.", f"Mẹ lấy hộp ảnh, còn {name} cầm túi giấy tờ và kiểm tra danh sách lần cuối.", "Cả hai khóa cửa rồi rời nhà theo tuyến an toàn đã được hướng dẫn."],
                "FALLING": [f"Trên đường đến nơi trú, {name} vẫn nghe gió mạnh phía sau.", "Mẹ nắm tay em và xác nhận cả gia đình đã có mặt.", f'"Nhà mình đã khóa và đồ quan trọng đã cất rồi," {name} nói.', '"Đúng vậy, giờ chúng ta tiếp tục đến nơi trú," Mẹ đáp.', f"{name} nhìn lại danh sách: vật dụng quan trọng đã được cất, cửa đã khóa, điện đã kiểm tra.", "Em thấy nhẹ nhõm vì đã làm đúng việc mà không tự đặt mình vào nguy hiểm."],
                "ENDING": ["Gia đình đến nơi trú an toàn trước khi bão đổ bộ.", f"{name} hiểu rằng can đảm không có nghĩa là làm mọi việc một mình.", "Em đã hoàn thành phần việc phù hợp, nhờ mẹ khi cần và rời nhà đúng lúc.", "Mẹ ôm em, còn túi giấy tờ và hộp kỷ niệm nằm khô ráo bên cạnh.", "Ngoài kia mưa vẫn lớn, nhưng cả gia đình đã sẵn sàng chờ bão qua."],
                "FAREWELL": [f"Tạm biệt {name} và gia đình ở nơi trú an toàn.", "Cảm ơn bạn đã lắng nghe.", "Hẹn gặp lại trong câu chuyện tiếp theo."],
            }[zone]
            return cls._fit_zone(storm_beats, target_words, zone, context, language)
        if context.get("scenario") == "LOST_BIRD_RETURN":
            bird_beats = {
                "GREETING": ["Xin chào, hôm nay chúng ta gặp hai chị em bên một khu vườn nhỏ.", "Câu chuyện bắt đầu khi mây mưa đang kéo đến."],
                "OPENING": ["Hai chị em nghe tiếng kêu yếu dưới gốc cây.", "Các em phát hiện một chú chim non bị lạc khỏi tổ.", "Mây sẫm màu và những giọt mưa đầu tiên bắt đầu rơi.", "Cả hai đứng xa cành trơn để quan sát mà không chạm vào chim."],
                "INTRODUCTION": ["Hai em biết mình phải tránh xa thân cây trơn trong mưa.", "Các em nhờ người lớn ở ngôi nhà gần đó giúp đỡ.", f'"Con thấy chim non bị lạc và cần đưa về tổ," {name} nói.', f'"Con đứng dưới mái hiên nhé, Mẹ sẽ kiểm tra," {friend} đáp.'],
                "DEVELOPMENT": ["Mẹ quan sát tổ bằng ống nhòm rồi gọi nhân viên cứu hộ động vật gần đó.", f'"Con sẽ chỉ đúng vị trí của tổ," {name} nói.', f'"Mẹ nghe rõ rồi, con cứ ở nơi khô ráo," {friend} đáp.', "Hai chị em đặt một chiếc khăn khô cạnh chim theo hướng dẫn.", "Các em giữ khoảng cách và che mưa từ mái hiên.", "Người cứu hộ mang thang an toàn, găng tay và kiểm tra cành cây."],
                "CLIMAX": ["Mưa nặng hạt hơn khi người cứu hộ cố định chiếc thang.", f"{name} quyết định đứng cạnh Mẹ, không bước vào vùng trơn.", f'"Chiếc thang đã ổn định chưa ạ?" {name} hỏi.', f'"Đã ổn định, mọi người cùng lùi lại nhé," {friend} đáp.', "Người cứu hộ nhẹ nhàng đặt chim non vào tổ.", "Chim mẹ bay về cành gần đó rồi cất tiếng gọi."],
                "FALLING": ["Chim non trở lại tổ trước khi cơn mưa mạnh nhất kéo tới.", "Hai chị em nhìn từ mái hiên và thấy chim đã nằm yên bên chim mẹ.", f'"May mà chúng con nhờ người lớn," {name} nói.', f'"Các con đã chọn cách an toàn," {friend} đáp.', "Mẹ xác nhận khu vực đã an toàn rồi đưa hai em về nhà."],
                "ENDING": [f"{name} và em gái về nhà trong áo mưa, lòng nhẹ nhõm vì chim non đã an toàn.", f"{name} nhận ra giúp đỡ đúng cách có nghĩa là biết dừng lại trước nguy hiểm.", "Ngoài cửa sổ, tổ chim vẫn vững trên cành và tiếng chim vang qua màn mưa."],
                "FAREWELL": ["Tạm biệt hai chị em và chú chim non đã trở lại tổ.", "Hẹn gặp lại trong câu chuyện tiếp theo."],
            }[zone]
            return cls._fit_zone(bird_beats, target_words, zone, context, language)
        if context.get("scenario") == "TORN_BOAT_GRIEF":
            boat_beats = {
                "GREETING": [f"Xin chào, hôm nay chúng ta gặp {name} và chiếc thuyền giấy em tự gấp.", "Câu chuyện có tên Chiếc Thuyền Còn Vết Rách, do An Nhiên kể."],
                "OPENING": [f"Mưa tạt qua cửa làm chiếc thuyền của {name} mềm và rách.", f"{name} lo rằng ô cửa nhỏ và những nếp gấp thân quen sẽ biến mất.", "Nếp gấp ở mũi thuyền xô lệch, còn ô cửa nhỏ nhòe màu.", f"{name} nhặt thuyền lên bằng hai tay và mang vào phòng gối xanh.", "Em buồn vì từng nếp giấy đều do chính mình kiên nhẫn tạo ra."],
                "INTRODUCTION": [f"Mẹ ngồi bên {name} cạnh chiếc gối xanh mà không vội sửa thuyền.", f'"Con buồn vì thuyền đã rách," {name} nói.', '"Mẹ ở đây và sẽ nghe con," Mẹ đáp.', f"{name} đặt chiếc thuyền cũ lên khăn khô để ngắm lại ô cửa nhỏ."],
                "DEVELOPMENT": ["Mẹ đặt một tờ giấy mới bên cạnh, nhưng không ép Bo phải dùng.", f'"Con không nhận thuyền mới đâu, con muốn giữ chiếc này," {name} nói.', '"Mẹ hiểu, mình có thể giữ nó đúng như bây giờ," Mẹ đáp.', f"{name} từ chối thuyền thay thế rồi kể cho Mẹ nghe về từng nếp gấp.", "Hai mẹ con mở một trang sách xanh làm dòng sông khô trên sàn."],
                "CLIMAX": [f"Khi chạm vào vết rách, {name} lại thấy nghẹn trong cổ.", f'"Mẹ ôm con một lúc được không?" {name} hỏi.', '"Được, con cứ buồn theo cách của con," Mẹ nói.', f"{name} quyết định không dùng keo che mất vết rách.", "Em chọn giữ chiếc thuyền cũ cùng ký ức về buổi chiều đã gấp nó."],
                "FALLING": [f"Sau cái ôm, {name} đặt thuyền lên một bến khô cạnh gối vịt.", "Mẹ trải trang sách thành dòng sông và ngồi yên bên em.", f'"Vết rách vẫn còn, nhưng con muốn thuyền ở đây," {name} nói.', '"Mẹ sẽ cùng con giữ khoảng yên này," Mẹ đáp.', "Hai mẹ con nhìn chiếc thuyền nghiêng nhẹ trên dòng sông bằng giấy."],
                "ENDING": [f"{name} giữ chiếc thuyền còn vết rách trên bến khô cạnh gối xanh.", "Thuyền không lành lại, và nỗi buồn cũng chưa biến mất hoàn toàn.", f"{name} nhận ra em vẫn có thể yêu quý một vật đã đổi khác.", "Mẹ ngồi bên, còn trang sách tiếp tục làm dòng sông cho chiếc thuyền cũ."],
                "FAREWELL": [f"Tạm biệt {name} và Mẹ bên chiếc thuyền còn vết rách.", "Hẹn gặp lại trong một câu chuyện khác."],
            }[zone]
            text = cls._fit_zone(boat_beats, target_words, zone, context, language)
            for source, replacement in (
                ('"Cậu ', '"Con '), ('"Tớ ', '"Mẹ '), ('"Mình ', '"Con '),
                ("của cậu", "của con"), ("Hai bạn", "Hai mẹ con"),
                ("hai bạn", "hai mẹ con"), ("người bạn", "Mẹ"),
            ):
                text = text.replace(source, replacement)
            return text
        beats = {
            "GREETING": [f"Xin chào, hôm nay chúng ta gặp {name} trong một câu chuyện về lòng can đảm.",
                         "Mời bạn lắng nghe từng lựa chọn nhỏ làm nên một bước tiến lớn."],
            "OPENING": [f"{name} sống ở {place} và đang {goal}.", *cls._safe_brief_sentences(context["brief"]),
                        f"Nghĩ đến ngày thể hiện trước mọi người, {name} thấy lo vì {fear}.",
                        f"Bàn tay {name} khựng lại trên trang giấy, dù ý tưởng đã hiện lên rất rõ."],
            "INTRODUCTION": [f"{friend} tìm thấy {name} bên bàn học và nhận ra vẻ lo lắng.",
                             f'"Mình sợ sẽ làm hỏng tất cả," {name} nói.',
                             f'"Cậu chỉ cần thử một bước nhỏ trước," {friend} đáp.',
                             f"Hai bạn chia việc {goal} thành phác thảo, luyện tập và trình bày.",
                             f"{name} đồng ý bắt đầu bằng điều dễ nhất thay vì bỏ cuộc."],
            "DEVELOPMENT": [f"Sau giờ học, {name} luyện từng nét trong căn phòng yên tĩnh.",
                            f"Một lần vẽ lệch khiến {name} buồn, nhưng cô không xé tờ giấy.",
                            f'"Mình muốn dừng lại một chút," {name} nói.',
                            f'"Nghỉ rồi thử tiếp nhé," {friend} đáp.',
                            f"{name} hít chậm, sửa một góc nhỏ và thấy bức tranh sáng dần.",
                            "Mỗi lần luyện tập giúp cô hiểu rằng sai sót không phải kết thúc."],
            "CLIMAX": [f"Ngày quyết định đến, căn phòng đông người làm {fear} trở lại.",
                       f"{name} nghe tim đập nhanh nhưng vẫn đặt dụng cụ lên bàn.",
                       f'"Mình có thể bắt đầu từ nét đầu tiên," {name} nói.',
                       f'"Tớ ở đây, nhưng lựa chọn là của cậu," {friend} đáp.',
                       f"Vì không muốn bỏ mất cơ hội, {name} nhìn thẳng vào trang giấy.",
                       "Cô vẽ nét đầu, rồi nét thứ hai, để câu chuyện trong tranh tự mở ra."],
            "FALLING": [f"Khi phần thể hiện kết thúc, {name} thở ra và nhìn lại tác phẩm.",
                       "Bức tranh chưa hoàn hảo, nhưng nó chứa lựa chọn can đảm của cô.",
                       f'"Mình vẫn run, nhưng mình đã không bỏ cuộc," {name} nói.',
                       f'"Đó là điều đáng nhớ nhất," {friend} đáp.',
                       "Hai bạn bước ra hành lang, nơi ánh sáng làm màu vẽ thêm ấm."],
            "ENDING": [f"{name} hoàn thành {goal} và tự trình bày ý tưởng của mình.",
                      "Cô nhận ra lòng can đảm có thể xuất hiện ngay khi nỗi sợ còn đó.",
                      f"Kết quả không còn là điều duy nhất quan trọng với {name}.",
                      "Bước tiến thật sự là việc cô đã cho tài năng của mình một cơ hội.",
                      f"{friend} mỉm cười, còn {name} giữ bức tranh như dấu mốc trưởng thành."],
            "FAREWELL": [f"Tạm biệt {name}, người đã tiến lên dù vẫn còn hồi hộp.",
                         "Hẹn gặp lại trong một câu chuyện mới về những lựa chọn chân thành."],
        }[zone]
        text = cls._fit_zone(beats, target_words, zone, context, language)
        if friend.casefold() == "mẹ":
            for source, replacement in (
                ('"Cậu ', '"Con '), ('"Tớ ', '"Mẹ '),
                ('"Mình ', '"Con '), ("của cậu", "của con"),
                ("Hai bạn", "Hai mẹ con"), ("hai bạn", "hai mẹ con"),
                ("người bạn", "Mẹ"),
            ):
                text = text.replace(source, replacement)
        return text

    @classmethod
    def _safe_brief_sentences(cls, brief: str) -> list[str]:
        normalized = unicodedata.normalize("NFC", brief).casefold()
        if "câu cụt" in normalized and any(term in normalized for term in (
            "viết toàn", "toàn câu cụt", "mưa. chạy. sợ.",
        )):
            return []
        values = []
        for sentence in re.split(r"(?<=[.!?])\s+", brief):
            chunks = [sentence] if len(cls._word_pattern.findall(sentence)) <= 27 else re.split(r"[,;]\s*", sentence)
            for chunk in chunks:
                words = cls._word_pattern.findall(chunk)
                if 4 <= len(words) <= 27:
                    text = chunk.strip().rstrip(".!?") + "."
                    values.append(text)
                elif 1 <= len(words) <= 3:
                    subject = chunk.strip().rstrip(".!?")
                    values.append(f"Chủ đề trung tâm của câu chuyện là {subject}.")
        return values[:12]

    @classmethod
    def _fit_zone(cls, beats: list[str], target: int, zone: str, context: dict[str, Any], language: str) -> str:
        selected: list[str] = []
        count = 0
        for sentence in beats:
            size = len(cls._word_pattern.findall(sentence))
            if count + size <= target + 3:
                selected.append(sentence)
                count += size
        if zone in {"GREETING", "FAREWELL"}:
            return " ".join(selected)
        name = context["protagonist"]
        friend = context["companion"]
        actions_by_zone = {
            "OPENING": ["đọc kỹ thể lệ", "chọn ý tưởng chính", "mở hộp màu", "đặt tờ giấy mới", "nhớ đến cuộc thi", "phác đường chân trời"],
            "INTRODUCTION": ["trao đổi kế hoạch", "chia nhỏ công việc", "lắng nghe góp ý", "đánh dấu lịch tập", "chuẩn bị vật liệu", "nói rõ điều lo lắng"],
            "DEVELOPMENT": ["luyện nét cong", "pha thử màu mới", "sửa phần bố cục", "tập giới thiệu tranh", "giữ tay thật đều", "so sánh hai bản nháp"],
            "CLIMAX": ["nhìn về phía trước", "đặt cọ xuống giấy", "giữ nhịp thở chậm", "chọn màu chủ đạo", "tiếp tục phần còn dở", "tự quyết định nét vẽ"],
            "FALLING": ["ngắm lại tác phẩm", "lau màu trên tay", "kể về khoảnh khắc khó", "lắng nghe nhận xét", "ghi nhớ điều đã làm", "cất dụng cụ gọn gàng"],
            "ENDING": ["ký tên lên tranh", "trình bày ý tưởng", "cảm ơn người bạn", "giữ lại bản phác", "nhìn vào sản phẩm", "nhớ về lần bắt đầu"],
        }
        details_by_zone = {
            "OPENING": ["bên cửa sổ lớp", "trước giờ vào học", "trên chiếc bàn gỗ", "giữa mùi giấy mới", "dưới nắng buổi sáng", "cạnh bảng thông báo"],
            "INTRODUCTION": ["trong thư viện nhỏ", "bên cuốn sổ xanh", "sau tiếng trống trường", "ở góc bàn quen", "giữa hai giờ học", "trước bản kế hoạch"],
            "DEVELOPMENT": ["sau giờ tan lớp", "trong buổi tập đầu", "bên giá vẽ thấp", "dưới ngọn đèn vàng", "qua nhiều bản nháp", "trong chiều mưa nhẹ"],
            "CLIMAX": ["giữa căn phòng đông", "trước hàng ghế dài", "khi tiếng nói lắng xuống", "bên khung tranh trắng", "dưới ánh đèn sáng", "trong phút quyết định"],
            "FALLING": ["ngoài hành lang mát", "sau phần trình bày", "bên bức tường sáng", "khi đám đông đã tan", "trong khoảng yên lặng", "dưới bóng cây sân trường"],
            "ENDING": ["trước góc trưng bày", "bên những người bạn", "trong nắng cuối ngày", "sau một hành trình dài", "giữa tiếng cười vui", "cạnh bức tranh hoàn chỉnh"],
        }
        results_by_zone = {
            "OPENING": ["để hiểu thử thách sắp tới", "và thấy mục tiêu rõ hơn", "nhưng vẫn nghe tim đập nhanh", "khi ý tưởng vừa xuất hiện", "để chuẩn bị cho ngày thi", "dù nỗi lo chưa biến mất"],
            "INTRODUCTION": ["để kế hoạch trở nên vừa sức", "và tìm được bước đầu tiên", "khi tình bạn tạo thêm tin tưởng", "để mỗi việc có thời gian", "mà không giấu nỗi sợ", "rồi cùng thống nhất cách làm"],
            "DEVELOPMENT": ["để kỹ năng tiến bộ từng chút", "rồi học từ lỗi vừa gặp", "khi sự kiên nhẫn được thử thách", "nhưng không vò bỏ trang giấy", "và biến lo lắng thành hành động", "để lần sau vững vàng hơn"],
            "CLIMAX": ["dù nhiều ánh mắt đang chờ", "vì cơ hội chỉ đến lúc này", "rồi hoàn thành phần quan trọng", "khi lòng can đảm dẫn đường", "mà không nhờ bạn làm thay", "để tự chịu trách nhiệm lựa chọn"],
            "FALLING": ["và nhận ra mình đã thay đổi", "để hiểu kết quả thật công bằng", "khi cảm giác nhẹ nhõm lan ra", "rồi chấp nhận phần chưa hoàn hảo", "vì nỗ lực đã được nhìn thấy", "mà không quên phút từng run sợ"],
            "ENDING": ["như một dấu mốc trưởng thành", "và trao cho tài năng cơ hội", "khi niềm vui thay chỗ lo âu", "để lần thử sức có ý nghĩa", "rồi mỉm cười với chính mình", "vì cô đã chọn không bỏ cuộc"],
        }
        if context.get("scenario") == "STORM_EVACUATION":
            actions_by_zone = {
                "OPENING": ["nghe bản tin bão", "xem danh sách an toàn", "quan sát mây đen", "đóng gọn đồ nhẹ", "gọi mẹ kiểm tra", "chuẩn bị túi sơ tán"],
                "INTRODUCTION": ["cất giấy tờ", "đánh dấu danh sách", "gom thuốc cần thiết", "xếp nước uống", "kiểm tra đèn pin", "nhắc lại tuyến đi"],
                "DEVELOPMENT": ["di chuyển vật dụng", "đưa kỷ vật lên cao", "cất ảnh gia đình", "đóng các cửa nhỏ", "bọc đồ dễ ướt", "báo mẹ chỗ nguy hiểm"],
                "CLIMAX": ["nghe lệnh sơ tán", "kiểm tra túi giấy tờ", "gọi mẹ hỗ trợ", "khóa cửa lần cuối", "rời nhà đúng lúc", "đi theo tuyến an toàn"],
                "FALLING": ["đếm đủ người thân", "xem lại danh sách", "giữ túi đồ khô", "đi bên cạnh mẹ", "báo đã đến nơi", "ngồi ở khu trú"],
                "ENDING": ["đến nơi trú an toàn", "cất túi giấy tờ", "ôm mẹ nhẹ nhõm", "chờ tin cơn bão", "nhớ các bước an toàn", "cảm ơn người hỗ trợ"],
            }
            details_by_zone = {
                zone_name: ["trước khi mưa lớn", "bên cửa sổ đã đóng", "theo danh sách gia đình", "dưới sự hướng dẫn của mẹ", "khi gió mạnh dần", "trong thời gian còn lại"]
                for zone_name in actions_by_zone
            }
            results_by_zone = {
                "OPENING": ["để hiểu thời hạn sắp tới", "và biết việc nào cần làm", "mà không đến gần cửa kính", "để chuẩn bị thật bình tĩnh", "khi nỗi sợ vẫn còn", "trước giờ sơ tán"],
                "INTRODUCTION": ["để mỗi người có phần việc rõ", "và tránh bỏ quên đồ thiết yếu", "mà không tự làm việc nguy hiểm", "để sẵn sàng rời nhà", "khi mẹ vẫn ở bên", "rồi cùng kiểm tra lại"],
                "DEVELOPMENT": ["để bảo vệ đồ quan trọng", "và giữ lối đi thông thoáng", "mà luôn làm theo hướng dẫn", "để ngôi nhà an toàn hơn", "khi mưa bắt đầu rơi", "rồi chuyển sang việc tiếp theo"],
                "CLIMAX": ["vì lệnh sơ tán đã vang lên", "để không chậm thời hạn", "mà không quay lại một mình", "khi cả hai phối hợp", "rồi khóa cửa cẩn thận", "để rời nhà an toàn"],
                "FALLING": ["và biết gia đình đã đủ người", "để bình tĩnh giữa tiếng gió", "khi nơi trú đã ở phía trước", "mà vẫn giữ đồ thiết yếu", "rồi báo tin cho người thân", "vì kế hoạch đã phát huy tác dụng"],
                "ENDING": ["khi cả gia đình đã an toàn", "và hiểu giá trị của chuẩn bị", "mà không xem nhẹ cơn bão", "để ghi nhớ cách nhờ người lớn", "rồi chờ thời tiết ổn định", "vì mọi người đã rời nhà đúng lúc"],
            }
        elif context.get("scenario") == "TORN_BOAT_GRIEF":
            actions_by_zone = {
                "OPENING": ["nâng chiếc thuyền rách", "nhìn ô cửa nhòe", "chạm vào nếp gấp", "mang thuyền vào phòng"],
                "INTRODUCTION": ["đặt thuyền lên khăn", "kể với Mẹ về mưa", "chỉ cho Mẹ vết rách", "ngồi cạnh gối xanh"],
                "DEVELOPMENT": ["từ chối tờ giấy mới", "nhớ buổi tự gấp thuyền", "giữ ô cửa nhỏ", "mở trang sách xanh"],
                "CLIMAX": ["xin Mẹ ôm", "chọn giữ vết rách", "đặt keo sang bên", "nói rõ nỗi buồn"],
                "FALLING": ["làm một bến khô", "đặt thuyền cạnh gối vịt", "xếp sách thành dòng sông", "ngồi yên cùng Mẹ"],
                "ENDING": ["giữ chiếc thuyền cũ", "nhìn vết rách còn nguyên", "để thuyền trên bến", "khép trang sách nhẹ nhàng"],
            }
            details_by_zone = {
                zone_name: ["trong căn phòng gối xanh", "bên chiếc khăn khô", "cạnh Mẹ", "dưới ánh đèn ấm"]
                for zone_name in actions_by_zone
            }
            results_by_zone = {
                "OPENING": ["vì em nhận ra đồ vật đã đổi khác", "khi nước vẫn đọng trên giấy", "mà không cố kéo phẳng", "để giữ từng nếp tự gấp"],
                "INTRODUCTION": ["để Mẹ hiểu điều em quý", "khi nỗi buồn được gọi tên", "mà không cần vội sửa", "vì em muốn có người ngồi bên"],
                "DEVELOPMENT": ["vì thuyền cũ mang ký ức riêng", "mà không đổi sang chiếc khác", "để giữ ô cửa em từng làm", "khi Mẹ tôn trọng lựa chọn ấy"],
                "CLIMAX": ["để đối diện điều không thể làm lại", "vì em quyết định giữ thuyền", "mà không che mất dấu mưa", "khi cái ôm làm vai em dịu xuống"],
                "FALLING": ["để chiếc thuyền có chỗ nghỉ", "khi dòng sông giấy mở ra", "mà vết rách vẫn còn", "vì hai mẹ con cùng ở lại"],
                "ENDING": ["như một ký ức được gìn giữ", "dù thuyền không lành lại", "khi nỗi buồn vẫn được chấp nhận", "vì em không còn ở một mình"],
            }
        actions = actions_by_zone[zone]
        details = details_by_zone[zone]
        results = results_by_zone[zone]
        index = 0
        while count < target - 8:
            if language == "en":
                themes = {
                    "OPENING": "the first challenge beside the classroom noticeboard",
                    "INTRODUCTION": "the shared plan inside the quiet school library",
                    "DEVELOPMENT": "the practice session near the paint covered worktable",
                    "CLIMAX": "the decisive moment beneath the bright presentation lights",
                    "FALLING": "the honest review along the calm open hallway",
                    "ENDING": "the completed journey beside the finished public display",
                }
                en_actions = ["studies", "adjusts", "discusses", "tests", "organizes", "reviews"]
                en_details = ["a careful choice", "the next small step", "a useful detail", "the available tools", "a fresh approach", "the visible result"]
                en_results = ["with patience", "without hiding the fear", "beside a trusted friend", "before moving forward", "while staying focused", "with growing confidence"]
                sentence = (
                    f"{name} {en_actions[index % 6]} {en_details[(index // 6) % 6]} "
                    f"during {themes[zone]} {en_results[(index // 36) % 6]}."
                )
            else:
                action = actions[index % len(actions)]
                detail = details[(index // len(actions)) % len(details)]
                result = results[(index // (len(actions) * len(details))) % len(results)]
                sentence = f"{name} {action} {detail} {result}."
            size = len(cls._word_pattern.findall(sentence))
            if count + size > target + 3:
                break
            selected.append(sentence)
            count += size
            index += 1
        tails = {
            "OPENING": f"{name} vẫn quyết tâm.",
            "INTRODUCTION": f"{friend} kiên nhẫn chờ.",
            "DEVELOPMENT": f"{name} thử lại lần nữa.",
            "CLIMAX": f"{name} không lùi bước.",
            "FALLING": "Cả hai cùng nhẹ nhõm.",
            "ENDING": f"{name} đã trưởng thành hơn.",
        }
        if language == "en":
            tails = {
                "OPENING": f"{name} remains determined.",
                "INTRODUCTION": f"{friend} waits with patience.",
                "DEVELOPMENT": f"{name} tries once more.",
                "CLIMAX": f"{name} does not retreat.",
                "FALLING": "Both friends feel relieved.",
                "ENDING": f"{name} has grown stronger.",
            }
        tail = tails[zone]
        tail_size = len(cls._word_pattern.findall(tail))
        if count < target - 3 and count + tail_size <= target + 3:
            selected.append(tail)
        return " ".join(selected)

    @staticmethod
    def _english_beats(zone: str, context: dict[str, Any]) -> list[str]:
        name, friend = context["protagonist"], context["companion"]
        beats = {
            "GREETING": [f"Welcome to {name}'s story about courage and one meaningful choice.",
                         "Listen closely as a difficult goal becomes a series of possible steps.",
                         "Our journey begins in a familiar place."],
            "OPENING": [f"{name} prepares for the goal described in the brief.",
                        *DeterministicStoryProvider._safe_brief_sentences(context["brief"]),
                        f"A familiar fear makes {name} hesitate."],
            "INTRODUCTION": [f'"I am afraid to begin," {name} said.', f'"Take one small step," {friend} replied.'],
            "DEVELOPMENT": [f"{name} practices carefully and learns from each mistake.", f'"I will try again," {name} said.'],
            "CLIMAX": [f"At the decisive moment, {name} faces the central obstacle.", f'"I can begin now," {name} said.', f'"The choice is yours," {friend} replied.'],
            "FALLING": [f"Afterward, {name} studies the result with honest relief.", f'"I kept going," {name} said.'],
            "ENDING": [f"{name} completes the goal and gives personal talent a fair chance."],
            "FAREWELL": [f"Goodbye to {name}, who moved forward while fear was still present.",
                         "May this honest effort remain warm in your memory until our next story.",
                         "Thank you for listening."],
        }
        return beats[zone]

    def repair(self, story: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        return story


class DeterministicCharacterImageProvider:
    provider_id = "deterministic-character-image-provider/1.0"

    def generate(self, character: dict[str, Any]) -> tuple[bytes, str]:
        digest = hashlib.sha256(character["character_id"].encode()).digest()
        rgb = (64 + digest[0] % 128, 64 + digest[1] % 128, 64 + digest[2] % 128)
        palette_names = character.get("visual_identity", {}).get("palette", [])
        palette_map = {
            "blue": (55, 105, 190), "yellow": (226, 178, 48), "white": (224, 231, 238),
            "earth": (145, 94, 60), "green": (74, 139, 91), "red": (186, 70, 70),
        }
        primary = next(
            (palette_map[str(name).casefold()] for name in palette_names if str(name).casefold() in palette_map),
            rgb,
        )
        config = stage1_config()["character_image"]
        return character_card_png(
            config["width"], config["height"], rgb, primary,
            str(character.get("visual_identity", {}).get("presentation", "ANDROGYNOUS")),
        )


class RuleBasedSafetyProvider:
    provider_id = "rule-based-safety-provider/1.0"
    _blocked = {"gore", "tình dục", "hướng dẫn phạm pháp", "sexual content"}

    def assess(self, profile: Profile, story: dict[str, Any]) -> SafetyDecision:
        findings = []
        for index, item in enumerate(story["script"]):
            lowered = item["text"].casefold()
            for phrase in self._blocked:
                if phrase in lowered:
                    findings.append({"locator": f"script[{index}].text", "phrase": phrase})
        return SafetyDecision("PASS" if not findings else "FAIL", findings, "DETERMINISTIC_LEXICAL")
