# Khung đo baseline

## Mức hoàn thành nhiệm vụ

| Mã | Định nghĩa |
|---|---|
| SUCCESS | Hoàn thành đúng mà không cần gợi ý nội dung hoặc vị trí thao tác |
| ASSISTED | Hoàn thành sau một hoặc nhiều hỗ trợ |
| FAILURE | Không hoàn thành, chọn kết quả sai hoặc người điều phối phải thực hiện thay |

Chỉ `SUCCESS` được tính vào tỷ lệ hoàn thành độc lập. Báo cáo thêm tỷ lệ `SUCCESS + ASSISTED` để thấy khả năng phục hồi sau hỗ trợ.

## Cấp hỗ trợ

| Cấp | Mô tả | Ví dụ |
|---:|---|---|
| 0 | Không hỗ trợ | Người dùng tự hoàn thành |
| 1 | Nhắc lại mục tiêu | “Bạn đang cần tìm vấn đề chặn workflow.” |
| 2 | Gợi ý khái niệm | “Bạn có thể tìm khu vực liên quan đến kiểm định.” |
| 3 | Chỉ vị trí hoặc thao tác | “Mở mục Kiểm định ở thanh bên.” |

Hỗ trợ cấp 2 hoặc 3 khiến nhiệm vụ không còn là `SUCCESS`.

## Thời gian nhiệm vụ

- Bắt đầu khi người điều phối đọc xong yêu cầu.
- Kết thúc khi người tham gia tuyên bố đã xong hoặc đạt điểm dừng của nhiệm vụ.
- Tạm dừng đồng hồ nếu có lỗi môi trường không do giao diện.
- Báo cáo median; không dùng trung bình làm số chính với mẫu nhỏ.

## Lỗi nghiêm trọng

Một lỗi được xem là nghiêm trọng nếu dẫn đến ít nhất một kết quả sau:

- Chọn sai profile hoặc stage.
- Hiểu sai một output đã hoàn thành là đủ điều kiện phát hành.
- Bỏ qua blocker cần xử lý.
- Kết luận package an toàn để dùng tiếp khi dữ liệu hiển thị không hỗ trợ kết luận đó.
- Gửi tác vụ ngoài ý muốn hoặc gửi lặp.

## Tiêu chí theo nhiệm vụ

| Nhiệm vụ | Điều kiện SUCCESS |
|---|---|
| T1 | Gửi đúng profile `YOUTH_SAFE`, brief phù hợp và thời lượng 15 phút; nhận ra tác vụ đã được tạo |
| T2 | Chọn đúng blocker ưu tiên và giải thích đúng tác động tới workflow |
| T3 | Tìm đúng CTA Stage 2 và hiểu điều kiện trước khi xác nhận cuối |
| T4 | Mở đúng công cụ, phân biệt integrity/cảnh báo/khuyến nghị và đưa ra kết luận phù hợp dữ liệu |

## Chỉ số báo cáo

- Tỷ lệ hoàn thành độc lập theo nhiệm vụ: `SUCCESS / số phiên hợp lệ`.
- Tỷ lệ hoàn thành có hỗ trợ: `(SUCCESS + ASSISTED) / số phiên hợp lệ`.
- Median thời gian theo nhiệm vụ.
- Median mức tự tin 1–5.
- Số lỗi nghiêm trọng trên mỗi phiên.
- Tỷ lệ hiểu đúng ba khái niệm kiểm tra.
- Tỷ lệ người dùng chọn đúng blocker đầu tiên.

Mọi tỷ lệ phải ghi cả tử số và mẫu số, ví dụ `4/5 (80%)`. Không suy rộng thống kê từ mẫu định tính nhỏ.

## Ưu tiên pain point

Chấm mỗi vấn đề theo hai trục từ 1 đến 3:

- Tần suất: 1 = một người, 2 = hai hoặc ba người, 3 = ít nhất bốn người.
- Tác động: 1 = do dự, 2 = cần hỗ trợ hoặc làm lại, 3 = thất bại hoặc lỗi nghiêm trọng.

Điểm ưu tiên = `Tần suất × Tác động`. Với cùng điểm, ưu tiên vấn đề có tác động cao hơn. Mỗi pain point phải có ít nhất một quan sát hoặc trích dẫn làm bằng chứng.

## Mẫu bảng tổng hợp

| Chỉ số | T1 | T2 | T3 | T4 |
|---|---:|---:|---:|---:|
| SUCCESS | Chưa đo | Chưa đo | Chưa đo | Chưa đo |
| SUCCESS + ASSISTED | Chưa đo | Chưa đo | Chưa đo | Chưa đo |
| Median thời gian | Chưa đo | Chưa đo | Chưa đo | Chưa đo |
| Median tự tin | Chưa đo | Chưa đo | Chưa đo | Chưa đo |
| Lỗi nghiêm trọng | Chưa đo | Chưa đo | Chưa đo | Chưa đo |
