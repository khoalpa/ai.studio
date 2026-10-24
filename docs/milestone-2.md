# Mốc 2 — Stage 1

Stage 1 hiện chạy end-to-end bằng provider adapter:

1. Kiểm profile, brief, language và duration confirmation.
2. Sinh story candidate theo schema 2.3.
3. Tạo ảnh tham chiếu nhân vật PNG 1536×2048.
4. Gắn `reference_asset` và commitment digest.
5. Chạy structure, profile, word/duration, character, quality và safety gates.
6. Auto-repair tối đa hai vòng.
7. Serialize, parse-back và chạy lại toàn bộ gate.
8. Tạo `story_validation.json` 15 trường.
9. Build, reopen và verify `story.zip` Stage 1.

Provider mặc định là deterministic và phục vụ phát triển/test offline. Nó không được mô tả như model sáng tác production hay external safety classifier. Các interface `StoryProvider`, `CharacterImageProvider` và `SafetyProvider` là điểm nối provider thật.
