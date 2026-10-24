# UI/UX foundation

Bộ tài liệu này là đầu ra của Tuần 1 — Discovery và UX foundation cho giao diện web của AI Story.

## Mục tiêu sản phẩm

Giúp người vận hành tạo, kiểm định, sửa và xuất gói truyện qua workflow bốn giai đoạn mà không cần sử dụng CLI hoặc hiểu cấu trúc package nội bộ.

## Tài liệu

1. [Discovery brief](./discovery-brief.md): bối cảnh, giả thuyết người dùng, kế hoạch nghiên cứu và rủi ro.
2. [Ngôn ngữ giao diện](./ui-language.md): thuật ngữ hiển thị và nguyên tắc microcopy.
3. [Kiến trúc thông tin](./information-architecture.md): sitemap, mô hình điều hướng và quyền truy cập.
4. [User flows](./user-flows.md): các luồng chính và nhánh lỗi.
5. [Yêu cầu MVP](./mvp-requirements.md): phạm vi, acceptance criteria và ưu tiên.
6. [Mô hình trạng thái](./state-model.md): trạng thái run, stage, validation và quy tắc hành động.
7. [Wireframes](./wireframes.md): cấu trúc năm màn hình MVP và kịch bản usability test.
8. [Visual design](./visual-design.md): design direction, component states, responsive và accessibility.
9. [Design tokens](./design-tokens.json): token màu, typography, spacing, radius và motion.
10. [Báo cáo QA Tuần 6](./week-6-qa-report.md): test matrix, lỗi đã sửa và release checklist.
11. [Bộ nghiên cứu baseline](./research/week-1-baseline/README.md): kế hoạch tuyển người, kịch bản usability test, phiếu ghi nhận và cách tổng hợp số liệu Tuần 1.

## Quyết định nền tảng

- Sản phẩm được thiết kế như một web dashboard chạy trên workflow local hiện có.
- Đối tượng chính là người vận hành nội dung; thông tin kỹ thuật được đặt ở lớp chi tiết.
- Một `run` là một lần thực thi, không đồng nghĩa với toàn bộ dự án hoặc series.
- Luồng chính là tuyến tuần tự Stage 1 → Stage 4; không cho bỏ qua stage.
- Chỉ hỗ trợ chế độ ảnh `ZONE` trong MVP.
- `REPAIR` chỉ cho phép thay đổi artifact thuộc stage hiện tại.
- `PASS`, `FAIL`, `NOT_VERIFIED`, `ASSESSED_PASS` và `ASSESSED_FAIL` không được gom thành một trạng thái nhị phân.

## Definition of done cho Tuần 1

- Có proto-persona và giả thuyết cần xác thực.
- Có kịch bản phỏng vấn và tiêu chí tuyển người tham gia.
- Thuật ngữ kỹ thuật đã được ánh xạ sang nhãn UI tiếng Việt.
- Có sitemap và mô hình điều hướng.
- Có luồng cho truyện đơn, series, kiểm tra package và repair.
- Có yêu cầu MVP với acceptance criteria có thể kiểm thử.
- Có danh sách câu hỏi mở và rủi ro cần quyết định trước wireframe.
