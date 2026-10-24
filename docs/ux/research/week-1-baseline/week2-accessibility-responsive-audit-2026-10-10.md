# Kiểm tra accessibility và responsive — 10/10/2026

## Phạm vi

Kiểm tra build hiện tại bằng workspace cố định `blocked-workspace` trong bộ dữ liệu nghiên cứu Tuần 1. Phiên kiểm tra tập trung vào dashboard, workspace của truyện và Validation Center.

Đây là kiểm tra tương thích với trình đọc màn hình qua accessibility tree của trình duyệt, không phải một phiên NVDA thủ công. Cần thực hiện thêm một phiên NVDA thật trước khi phát hành.

## Kết quả

| Hạng mục | Kết quả | Bằng chứng |
|---|---|---|
| Nhãn điều hướng | Đạt | Điều hướng có tên “Điều hướng chính”; các liên kết và nút chính đều có accessible name. |
| Thứ tự focus bàn phím | Đạt có điều kiện | Sau khi nội dung route nhận focus, Tab đi tới hành động đầu tiên trong vùng nội dung. Dialog đã có vòng focus và hỗ trợ Escape trong mã nguồn. |
| Validation Center | Đạt | Bộ lọc có label; bản ghi blocker được đọc bằng tên thân thiện; chi tiết kỹ thuật được thu gọn trong `details`. |
| CTA theo blocker | Đạt | “Mở workspace để xử lý” đưa người dùng về đúng workflow. Khi còn blocker, Stage 2 hiển thị “Bị chặn bởi kiểm định” và không còn nút chạy tiếp. |
| Giữ trạng thái | Đạt | Tab “Kỹ thuật” được phục hồi sau khi đi sang Validation Center rồi quay lại. Bộ lọc và vị trí cuộn cũng được lưu theo route trong phiên hiện tại. |
| Responsive compact | Đạt | Ở viewport 714 × 764, media query compact hoạt động; `scrollWidth` là 699 px và không có tràn ngang. Danh sách và chi tiết kiểm định xếp thành một cột. |
| Nhóm workflow | Đạt | Dashboard hiển thị một dòng cho mỗi lineage package, kèm số lần chạy và lần chạy mới nhất. |

## Lỗi phát hiện và đã sửa

Workspace có blocker từng đồng thời hiển thị “Có lỗi chặn” và nút “Chạy Hình ảnh ngang”. Điều kiện chuyển stage nay yêu cầu không còn blocker và không còn lỗi chất lượng. Nhãn stage tiếp theo đổi thành “Bị chặn bởi kiểm định”.

## Tồn tại

- Chưa chạy NVDA thật với chế độ Browse và Focus.
- Trạng thái tab, bộ lọc và vị trí cuộn chỉ tồn tại trong phiên trang hiện tại, chưa lưu qua lần tải lại trình duyệt.

## Cập nhật sau vòng validation

Các tồn tại về tên gate và ma trận viewport đã được xử lý trong [vòng validation UI/UX](./week2-validation-round-2026-10-10.md). Phiên NVDA thật và validation với người tham gia vẫn chưa thực hiện.

## Tiêu chí cho vòng kiểm tra tiếp theo

1. Hoàn tất bảng tên thân thiện cho 100% gate xuất hiện trong fixture.
2. Chạy một phiên NVDA thủ công cho ba luồng: mở blocker, quay về workspace và mở chi tiết kỹ thuật.
3. Chạy ma trận viewport 390 px, 768 px và 1280 px, không có tràn ngang và không che CTA.
4. Xác nhận người dùng nhận ra workflow nhiều lần chạy trong vòng 10 giây.
5. Xác nhận không thể khởi chạy stage tiếp theo khi còn blocker mở.
