# Ngôn ngữ giao diện

## 1. Nguyên tắc

- Dùng ngôn ngữ công việc, không dùng tên class hoặc enum làm nhãn chính.
- Nhãn trạng thái phải trả lời được: chuyện gì xảy ra, tác động gì và bước tiếp theo là gì.
- Không dùng “thành công” cho output chưa vượt qua các blocker liên quan.
- Không dịch tên file trong cây package; chỉ thêm tên hiển thị thân thiện bên cạnh.
- ID kỹ thuật, digest và detector được đặt trong “Chi tiết kỹ thuật”.

## 2. Ánh xạ thuật ngữ

| Thuật ngữ hệ thống | Nhãn UI chính | Ghi chú |
|---|---|---|
| Run | Lần chạy | Một lần thực thi workflow hoặc một stage |
| Profile | Loại nội dung | Hiển thị profile cụ thể bên dưới |
| `YOUTH_SAFE` | Truyện thiếu nhi | Đối tượng 7–10 tuổi |
| `ADULT_STANDARD` | Truyện người lớn | Đối tượng 18+ |
| `SERIAL_DETECTIVE` | Series trinh thám | Đối tượng 18+, có continuity |
| Stage 1 | Nội dung & nhân vật | Tạo truyện, kiểm định và ảnh nhân vật |
| Stage 2 | Hình ảnh ngang | Visual plan, visual bible và ảnh 16:9 |
| Stage 3 | Hình ảnh dọc | Ảnh 9:16 và báo cáo chất lượng |
| Stage 4 | Prompt video | Prompt video và package phát hành |
| Artifact | Tệp đầu ra | Dùng “artifact” trong chi tiết kỹ thuật |
| Package | Gói truyện | Tệp `story.zip` và metadata liên quan |
| Gate | Kiểm tra | ID gate chỉ hiển thị trong chi tiết |
| Manifest | Thông tin gói | Có thể mở rộng xem `workflow_manifest.json` |
| Lineage | Nguồn gốc gói | Chuỗi package cha/con |
| CREATE | Tạo mới | Thao tác tạo output của stage |
| REPAIR | Sửa đầu ra | Sửa artifact thuộc stage hiện tại |
| ZONE | Theo phân đoạn | MVP hỗ trợ mười vùng nội dung chuẩn |
| SCENE | Theo cảnh | Chưa hỗ trợ |

## 3. Trạng thái validation

| Trạng thái | Nhãn UI | Giải thích ngắn |
|---|---|---|
| `PASS` | Đã xác minh — đạt | Kiểm tra có bằng chứng xác định và đã đạt |
| `FAIL` | Đã xác minh — không đạt | Có lỗi cần xử lý |
| `NOT_VERIFIED` | Chưa thể xác minh | Thiếu công cụ, dữ liệu hoặc điều kiện kiểm tra |
| `ASSESSED_PASS` | AI đánh giá — đạt | Kết quả đánh giá chất lượng, không thay thế kiểm tra integrity |
| `ASSESSED_FAIL` | AI đánh giá — chưa đạt | Cần xem lại chất lượng hoặc tạo lại |

Không rút gọn `NOT_VERIFIED` thành “Chưa chạy”, vì kiểm tra có thể đã chạy nhưng môi trường không đủ khả năng xác minh.

## 4. Mức độ tác động

| Severity | Nhãn UI | Hành vi |
|---|---|---|
| `PUBLISH_BLOCKER` | Chặn phát hành | Không cho tải package với mục đích phát hành chính thức |
| `QUALITY_BLOCKER` | Chưa đạt chất lượng | Cho xem và sửa; không trình bày như output hoàn chỉnh |
| `ADVISORY` | Khuyến nghị | Không chặn nhưng phải giữ trong báo cáo |

## 5. Microcopy mẫu

### Tác vụ đang chạy

- Tiêu đề: “Đang tạo hình ảnh ngang”
- Nội dung: “Bạn có thể rời màn hình này. Lần chạy vẫn tiếp tục.”
- Không hiển thị phần trăm nếu backend không cung cấp tiến độ thực.

### Stage bị khóa

- Tiêu đề: “Hoàn tất Nội dung & nhân vật trước”
- Nội dung: “Stage tiếp theo chỉ mở khi gói truyện hiện tại vượt qua các kiểm tra bắt buộc.”

### Publish blocker

- Tiêu đề: “Chưa thể phát hành gói truyện”
- Nội dung: “Còn 2 kiểm tra bắt buộc chưa đạt. Mở từng lỗi để xem cách xử lý.”

### Artifact kế thừa

- Tiêu đề: “Tệp này chỉ có thể xem”
- Nội dung: “Tệp được tạo ở Nội dung & nhân vật. Hãy sửa tại stage sở hữu rồi chạy lại các stage phía sau.”

### Chưa thể xác minh

- Tiêu đề: “Chưa thể xác minh kiểm tra này”
- Nội dung: “Kết quả không được xem là đạt. Xem chi tiết để biết dữ liệu hoặc công cụ còn thiếu.”

### Xác nhận thời lượng

- Checkbox: “Tôi xác nhận thời lượng mục tiêu là {minutes} phút.”
- Lỗi: “Thời lượng phải nằm trong khoảng {min}–{max} phút đối với loại nội dung này.”

## 6. Quy tắc đặt CTA

- Một CTA chính trên mỗi màn hình hoặc vùng tác vụ.
- Dùng động từ cụ thể: “Tạo nội dung”, “Chạy Stage 2”, “Sửa đầu ra”, “Tải gói truyện”.
- Không dùng “Tiếp tục” nếu hành động sẽ khởi chạy tác vụ tốn thời gian.
- Hành động tạo run mới hoặc tạo lại phải cho biết output mới, không ghi đè output cũ.
- “Phát hành” khác “Tải xuống”; tải checkpoint có thể được phép trong khi publish bị chặn.
