# Mốc 5 — Stage 4

Stage 4 hiện thực hiện:

1. Chỉ nhận package Stage 3 đã đạt `AUDIO_STORY_RELEASE`.
2. Giữ toàn bộ member Stage 3 ở chế độ read-only.
3. Dựng timeline từ word count, WPM, speed và terminal pause.
4. Chia utterance dài lossless với word offset liên tục và usable span tối đa 7,95 giây.
5. Chọn clip container nhỏ nhất trong 4/6/8 giây.
6. Tạo derived scene registry, clip source binding và continuity chain.
7. Chỉ route `characters/*.png` làm static references; cấm landscape/portrait.
8. Tạo voice strategy và exact source speech plan.
9. Tạo `video_prompts.json` schema 1.2 với tám root field.
10. Parse-back, recompute output digest, coverage và continuity.
11. Build/reopen/verify package `VIDEO_PRODUCTION_RELEASE`.

Stage 4 chỉ tạo provider-neutral prompt plan; không gọi video, audio hoặc image generator. FULL_STORY trên 120 clip cần xác nhận `--confirm-large-plan`.
