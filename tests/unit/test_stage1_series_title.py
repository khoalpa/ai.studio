from __future__ import annotations

from audio_story.workflows.stage1_series_title import resolve_series_title


def test_explicit_series_title_is_preserved() -> None:
    assert (
        resolve_series_title(
            "Bộ truyện đã đặt",
            {"opening": "Một chiếc đèn dẫn đường."},
            [{"text": "Chiếc đèn mở ra con đường mới."}],
            "vi",
        )
        == "Bộ truyện đã đặt"
    )


def test_missing_series_title_is_derived_from_story_content() -> None:
    title = resolve_series_title(
        None,
        {"opening": "Ngọn hải đăng phát tín hiệu giữa đêm."},
        [
            {"text": "Linh lần theo ánh hải đăng để tìm chiếc thuyền bị lạc."},
            {"text": "Ánh hải đăng đưa mọi người trở về bến an toàn."},
        ],
        "vi",
    )

    assert title == "Những Chuyện Về Hải Đăng"
    assert title != "Ngọn hải đăng phát tín hiệu giữa đêm."
