# Cải tiến hierarchy của Validation Center

## Thay đổi

- Mặc định hiển thị “Việc cần xử lý” khi workflow có blocker.
- Các kiểm tra đã đạt vẫn truy cập được qua bộ lọc “Tất cả” hoặc “Đã xử lý”.
- Danh sách có tiêu đề, mô tả cách ưu tiên và số lượng kết quả hiện tại.
- Số cảnh báo mở lấy giá trị lớn nhất giữa ledger summary và các record chưa đạt, tránh bỏ sót record nghiên cứu bổ sung.
- Bộ lọc kiểm định, tab workspace và vị trí cuộn được lưu trong `sessionStorage`.
- Trạng thái được phục hồi khi đổi route hoặc tải lại trang trong cùng phiên trình duyệt.

## Kết quả xác minh

Dataset có 24 kiểm tra và một blocker. Ở trạng thái mặc định, Validation Center chỉ hiển thị một việc cần xử lý thay vì dàn đều 24 hàng.

| Viewport | Kiểm tra đang hiển thị | Bộ lọc | Tràn ngang | Trạng thái phiên ở lần tải kế tiếp |
|---:|---:|---|---|---|
| 390 px | 1 | Đang mở | Không | Được phục hồi |
| 768 px | 1 | Đang mở | Không | Được phục hồi |
| 1280 px | 1 | Đang mở | Không | Được phục hồi |

## Giới hạn

`sessionStorage` chỉ tồn tại trong tab và phiên trình duyệt hiện tại. Đây là chủ ý để không áp bộ lọc cũ sang một phiên làm việc mới. Validation với người tham gia và phiên NVDA thật vẫn cần được thực hiện riêng.

## Câu hỏi cho phiên validation với người tham gia

1. Người dùng có nhận ra blocker đầu tiên trong 10 giây không?
2. Người dùng có hiểu rằng 23 kiểm tra còn lại đã đạt và vẫn có thể xem lại không?
3. Sau khi quay lại từ workspace, họ có nhận thấy bộ lọc và vị trí được giữ không?
4. Nhãn “Việc cần xử lý” có rõ hơn “Tất cả kiểm tra” cho tác vụ vận hành không?
5. Người dùng có cần một thao tác đánh dấu đã xem hoặc phân công người xử lý không?
