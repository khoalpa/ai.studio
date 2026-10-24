# Sổ theo dõi phiên validation

## Phiên người thật

| Participant ID | Vai trò mục tiêu | Trạng thái | Phiếu ghi nhận | Dòng CSV |
|---|---|---|---|---|
| P01 | Vận hành nội dung, kỹ thuật thấp hoặc trung bình | Sẵn sàng tuyển | [Phiếu P01](./p01-session-notes.md) | Chưa |
| P02 | Vận hành nội dung, kỹ thuật thấp hoặc trung bình | Chưa tuyển | Chưa tạo | Chưa |
| P03 | Vận hành nội dung, bất kỳ | Chưa tuyển | Chưa tạo | Chưa |
| P04 | Biên tập/QA, kỹ thuật thấp hoặc trung bình | Chưa tuyển | Chưa tạo | Chưa |
| P05 | Biên tập/QA, bất kỳ | Chưa tuyển | Chưa tạo | Chưa |

Runbook điều phối P01: [p01-session-runbook.md](./p01-session-runbook.md).

## Phiên mô phỏng lưu trữ

Theo chỉ định của chủ dự án, Codex thực hiện năm walkthrough mô phỏng theo vai trò. Các phiên này được đánh dấu `SIMULATED_CODEX`, không được trình bày như nghiên cứu với người dùng độc lập.

| Participant ID | Vai trò mục tiêu | Lịch | Trạng thái | Phiếu ghi nhận | Dòng CSV |
|---|---|---|---|---|---|
| S01 | Vận hành nội dung, kỹ thuật thấp | 10/10/2026 | SIMULATED_CODEX | [Báo cáo tổng hợp](./simulated-session-results-2026-10-10.md#p01) | Có |
| S02 | Vận hành nội dung, kỹ thuật trung bình | 10/10/2026 | SIMULATED_CODEX | [Báo cáo tổng hợp](./simulated-session-results-2026-10-10.md#p02) | Có |
| S03 | Vận hành nội dung thường xuyên | 10/10/2026 | SIMULATED_CODEX | [Báo cáo tổng hợp](./simulated-session-results-2026-10-10.md#p03) | Có |
| S04 | Biên tập/QA | 10/10/2026 | SIMULATED_CODEX | [Báo cáo tổng hợp](./simulated-session-results-2026-10-10.md#p04) | Có |
| S05 | QA kỹ thuật và accessibility | 10/10/2026 | SIMULATED_CODEX | [Báo cáo tổng hợp](./simulated-session-results-2026-10-10.md#p05) | Có |

## Điều kiện tổng hợp top 5

- Có ít nhất 5 phiên hợp lệ.
- Mọi pain point có quan sát hoặc trích dẫn làm bằng chứng.
- Điểm tần suất không được suy ra từ pilot nội bộ.
- Vấn đề môi trường được tách khỏi vấn đề UI/UX.

## Khung tổng hợp sau nghiên cứu

| Hạng | Pain point | Số người gặp | Tác động | Điểm | Bằng chứng | Đề xuất Tuần 2 |
|---:|---|---:|---:|---:|---|---|
| 1 | Thông điệp khóa stage mâu thuẫn với CTA đang bật | 5 | 3 | 9 | Quan sát trực tiếp trên ready workspace | Thống nhất state và microcopy |
| 2 | Blocker bị đặt cuối danh sách, PASS mở mặc định | 5 | 3 | 9 | Validation Center có 24 record | Sắp blocker trước và mở blocker đầu tiên |
| 3 | Nội dung truyện quá dài lấn át quyết định vận hành | 4 | 2 | 6 | CTA và kiểm định nằm sau preview dài | Tóm tắt/collapse preview |
| 4 | Cấu hình provider/model xuất hiện trong luồng operator | 3 | 2 | 4 | Bước cấu hình T1/T3 | Progressive disclosure |
| 5 | Modal job buộc người dùng chờ tại chỗ | 3 | 2 | 4 | Khi job chạy chỉ có nút Hủy | Cho đóng và theo dõi nền |
