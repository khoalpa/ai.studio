# Mốc 3 — Stage 2 ZONE

Stage 2 hiện thực hiện:

1. Reopen và kiểm package Stage 1.
2. Phục hồi profile từ manifest; không hỏi hoặc tự đổi profile.
3. Safe-extract các member kế thừa, bỏ manifest cũ.
4. Kiểm binding giữa `story.json`, `story_validation.json` và active profile.
5. Khóa `ZONE` với đúng 10 basename canonical.
6. Tạo `visual_plan.json` schema 1.0 và `visual_bible.json` schema 2.0.
7. Chạy một landscape transaction cho từng basename.
8. Kiểm PNG, kích thước 3840×2160, post-write hash và cardinality.
9. Finalize digest của Visual Plan và Visual Bible.
10. Build/reopen/verify `story.zip` Stage 2 với parent bind canonical package digest Stage 1.

Provider deterministic tạo PNG hợp lệ để test offline, không đại diện chất lượng mỹ thuật production. `SCENE`, resume và Stage 2 REPAIR vẫn bị feature gate chặn.
