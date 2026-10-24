# Pilot nội bộ — 10/10/2026

## Phạm vi

Đây là walkthrough kỹ thuật và heuristic do nhóm sản phẩm thực hiện, không phải phiên nghiên cứu với người dùng độc lập. Kết quả không được đưa vào tỷ lệ hoàn thành baseline.

Build được kiểm tra bằng pipeline deterministic và dataset `week1-usability-baseline-v1`.

## Kết quả readiness

| Hạng mục | Kết quả | Bằng chứng |
|---|---|---|
| Workspace sạch | PASS | Không có run trước khi bắt đầu T1 |
| Workflow có blocker | PASS | Có `RESEARCH:BLOCKER:BRIEF_COVERAGE`, trạng thái `FAIL`, mức `PUBLISH_BLOCKER` |
| Workflow sẵn sàng | PASS | Không có blocker mở và `allowed_next_stage` là `STAGE2` |
| Package cảnh báo | PASS | ZIP qua canonical verifier nhưng release status là `BLOCKED` |
| Telemetry Stage 1 | PASS | Test so sánh sai lệch với ngưỡng hiệu lực gồm thời gian đóng gói |
| Khả năng tái tạo | PASS | Dataset được sinh lại bằng một lệnh và có test tự động |

## Phát hiện trong walkthrough

1. Nhiệm vụ 2 và 3 không thể dùng cùng một trạng thái dữ liệu: blocker cố định khiến CTA Stage 2 bị vô hiệu. Dataset đã được tách thành `blocked_workspace` và `ready_workspace`.
2. Nếu Nhiệm vụ 3 thực sự khởi chạy Stage 2, thời gian provider có thể lấn át thời gian thao tác. Điểm dừng được đổi thành trước xác nhận cuối cùng.
3. Tên file và run ID thay đổi mỗi lần sinh dữ liệu. Kịch bản giờ đọc mọi đường dẫn từ `study-manifest.json`.
4. “Pipeline hoàn thành” và “release bị chặn” cùng xuất hiện trong package thử. Đây là tình huống phù hợp để đo mức hiểu, nhưng người điều phối không được giải thích trước.
5. Việc đổi server giữa T2 và T3 có thể gây gián đoạn. Thời gian đổi workspace phải được loại khỏi thời gian nhiệm vụ.

## Điều chỉnh đã áp dụng

- Cập nhật phần chuẩn bị và chuyển cảnh trong kịch bản.
- Thêm ready workspace riêng.
- Thêm kiểm tra tự động cho blocker, trạng thái sẵn sàng và package warning.
- Giữ pilot nội bộ ngoài mẫu nghiên cứu chính.

## Kết luận

Bộ nghiên cứu đã sẵn sàng cho pilot có người tham gia. Chưa đủ căn cứ để công bố tỷ lệ hoàn thành hoặc top pain point theo tần suất.
