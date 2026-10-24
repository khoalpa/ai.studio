# Nền tảng UI/UX

Thư mục này tập hợp đầu ra của Tuần 1 — Discovery và UX foundation cho giao diện web AI Story.

## Mục tiêu sản phẩm

Giúp người vận hành tạo, kiểm định, chỉnh sửa và xuất gói truyện qua workflow bốn giai đoạn mà không phải dùng CLI hoặc hiểu cấu trúc package nội bộ.

## Danh mục tài liệu

| Tài liệu | Nội dung |
|---|---|
| [Discovery brief](./discovery-brief.md) | Bối cảnh, giả thuyết người dùng, kế hoạch nghiên cứu và rủi ro |
| [Ngôn ngữ giao diện](./ui-language.md) | Thuật ngữ hiển thị và nguyên tắc microcopy |
| [Kiến trúc thông tin](./information-architecture.md) | Sitemap, mô hình điều hướng và quyền truy cập |
| [User flow](./user-flows.md) | Luồng chính và các nhánh lỗi |
| [Yêu cầu MVP](./mvp-requirements.md) | Phạm vi, acceptance criteria và mức ưu tiên |
| [Mô hình trạng thái](./state-model.md) | Trạng thái run, stage, validation và quy tắc hành động |
| [Wireframe](./wireframes.md) | Cấu trúc năm màn hình MVP và kịch bản usability test |
| [Visual design](./visual-design.md) | Design direction, trạng thái component, responsive và accessibility |
| [Design token](./design-tokens.json) | Màu sắc, typography, spacing, radius và motion |
| [Báo cáo QA Tuần 6](./week-6-qa-report.md) | Test matrix, lỗi đã sửa và release checklist |
| [Nghiên cứu baseline Tuần 1](./research/week-1-baseline/README.md) | Tuyển người, kịch bản usability test, biểu mẫu ghi nhận và cách tổng hợp số liệu |

## Các quyết định nền tảng

- Sản phẩm là web dashboard chạy trên workflow local hiện có.
- Người dùng chính là nhân sự vận hành nội dung; thông tin kỹ thuật nằm ở lớp chi tiết.
- Một `run` biểu thị một lần thực thi, không đại diện cho toàn bộ dự án hoặc series.
- Luồng chính đi tuần tự từ Stage 1 đến Stage 4 và không cho phép bỏ qua stage.
- MVP chỉ hỗ trợ chế độ ảnh `ZONE`.
- `REPAIR` chỉ được thay đổi artifact thuộc stage hiện tại.
- Các trạng thái `PASS`, `FAIL`, `NOT_VERIFIED`, `ASSESSED_PASS` và `ASSESSED_FAIL` phải được giữ riêng, không quy về một trạng thái nhị phân.

## Điều kiện hoàn thành Tuần 1

- Có proto-persona và danh sách giả thuyết cần xác thực.
- Có kịch bản phỏng vấn và tiêu chí tuyển người tham gia.
- Thuật ngữ kỹ thuật đã được ánh xạ sang nhãn UI tiếng Việt.
- Có sitemap và mô hình điều hướng.
- Có luồng cho truyện đơn, series, kiểm tra package và repair.
- Có yêu cầu MVP với acceptance criteria có thể kiểm thử.
- Có danh sách câu hỏi mở và rủi ro cần xử lý trước khi làm wireframe.
