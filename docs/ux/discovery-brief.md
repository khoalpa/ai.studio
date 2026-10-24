# Discovery brief

## 1. Bối cảnh

AI Story hiện là một workflow chạy bằng CLI, tạo package truyện qua bốn giai đoạn:

1. Nội dung truyện và nhân vật.
2. Kế hoạch hình ảnh và ảnh ngang.
3. Ảnh dọc và báo cáo chất lượng.
4. Prompt sản xuất video.

Hệ thống đã có profile, kiểm định, manifest, package lineage, repair và run index. Dashboard web vẫn chưa được triển khai.

## 2. Vấn đề cần giải quyết

Người vận hành hiện phải:

- nhớ lệnh, tham số và đường dẫn package;
- tự xác định stage tiếp theo;
- đọc JSON để hiểu kết quả hoặc lỗi;
- phân biệt lỗi integrity, lỗi chất lượng và trạng thái chưa được xác minh;
- bảo toàn đúng package đầu vào giữa các stage;
- quản lý series anchor bằng file.

Giá trị của UI không chỉ là thay thế câu lệnh bằng nút bấm. UI phải làm rõ workflow, giảm lỗi vận hành và giải thích điều kiện phát hành.

## 3. Giả thuyết sản phẩm

| ID | Giả thuyết | Cần xác thực bằng |
|---|---|---|
| H1 | Người dùng chính là người vận hành nội dung, không phải kỹ sư | Phỏng vấn vai trò và quan sát công việc |
| H2 | Người dùng suy nghĩ theo “dự án truyện/tập” thay vì “package/run” | Card sorting và phỏng vấn thuật ngữ |
| H3 | Stepper bốn giai đoạn giúp giảm việc chọn sai package đầu vào | Usability test prototype |
| H4 | Người dùng cần preview nội dung trước chi tiết manifest | Quan sát thứ tự thông tin được tìm |
| H5 | Lỗi cần được diễn giải thành tác động và hành động, không chỉ gate ID | Test comprehension |
| H6 | Series cần được quản lý như một thực thể cấp cao hơn run | Phỏng vấn quy trình sản xuất series |
| H7 | Người dùng cần theo dõi tác vụ dài và thử lại ở cấp artifact | Phỏng vấn và telemetry sau MVP |

## 4. Proto-persona

Các persona dưới đây là giả thuyết, chưa phải kết quả nghiên cứu.

### P1 — Người vận hành nội dung

- Mục tiêu: tạo trọn bộ tài sản cho một truyện hoặc tập truyện.
- Kỹ năng: quen công cụ nội dung, không muốn dùng terminal hoặc chỉnh JSON.
- Nhu cầu: quy trình rõ ràng, preview nhanh, lỗi có hướng xử lý.
- Rủi ro: khởi chạy sai profile, chọn nhầm package, không nhận ra lỗi chặn publish.
- Tần suất dự kiến: hằng ngày.

### P2 — Biên tập viên / kiểm soát chất lượng

- Mục tiêu: kiểm tra nội dung, hình ảnh, continuity và điều kiện phát hành.
- Kỹ năng: hiểu tiêu chuẩn nội dung nhưng không cần hiểu checksum.
- Nhu cầu: so sánh đầu ra, lọc blocker, truy cập bằng chứng và lịch sử sửa.
- Rủi ro: nhầm `ASSESSED_PASS` với kiểm định deterministic; sửa artifact sai stage.
- Tần suất dự kiến: theo từng checkpoint.

### P3 — Quản trị kỹ thuật

- Mục tiêu: chẩn đoán package lỗi, kiểm tra lineage và cấu hình provider.
- Kỹ năng: hiểu manifest, digest, log và filesystem.
- Nhu cầu: chi tiết kỹ thuật, package inspector, event log, đường dẫn đầu ra.
- Rủi ro: thiếu dữ liệu trạng thái hoặc lỗi bị UI che mất.
- Tần suất dự kiến: khi có sự cố.

## 5. Jobs to be done

- Khi có một ý tưởng truyện, tôi muốn cấu hình và khởi chạy đúng profile để nhận được bản nội dung có thể duyệt.
- Khi một stage hoàn thành, tôi muốn biết nó có đủ điều kiện đi tiếp hay không và vì sao.
- Khi có lỗi, tôi muốn biết lỗi tác động đến phát hành thế nào và tôi có thể làm gì tiếp theo.
- Khi tiếp tục series, tôi muốn hệ thống duy trì đúng continuity mà không phải tự quản lý anchor file.
- Khi nhận một package từ nguồn khác, tôi muốn kiểm tra nhanh tính hợp lệ và nội dung của nó.
- Khi cần sửa đầu ra, tôi muốn sửa đúng phần được phép mà không phá vỡ artifact kế thừa.

## 6. Kế hoạch nghiên cứu

### Người tham gia

- 3 người làm vận hành hoặc sản xuất nội dung.
- 2 biên tập viên/QA.
- 1 người đang vận hành CLI hiện tại hoặc hiểu workflow kỹ thuật.

Nếu một người kiêm nhiều vai trò, ghi nhận từng công việc riêng trong buổi phỏng vấn.

### Phương pháp

1. Phỏng vấn bán cấu trúc, 45 phút/người.
2. Quan sát một lần tạo truyện bằng quy trình hiện tại.
3. Card sorting mở với các mục: dự án, run, stage, package, series, kiểm định và artifact.
4. Test comprehension cho năm trạng thái validation.
5. Tổng hợp affinity map, cập nhật persona và ưu tiên pain point.

### Câu hỏi phỏng vấn

1. Hãy mô tả lần gần nhất bạn tạo một truyện từ đầu đến đầu ra cuối.
2. Bạn xem đơn vị công việc là dự án, truyện, tập, lần chạy hay package?
3. Ở bước nào bạn thường phải chờ, kiểm tra lại hoặc nhờ hỗ trợ?
4. Bạn quyết định một đầu ra “đủ tốt để đi tiếp” như thế nào?
5. Khi một kiểm tra thất bại, thông tin nào giúp bạn hành động?
6. Bạn cần xem hoặc so sánh artifact nào trước khi phê duyệt?
7. Nếu tạo series, bạn quản lý thông tin xuyên tập ở đâu?
8. Bạn cần khôi phục hoặc làm lại một phần công việc trong trường hợp nào?
9. Bạn có cần chia sẻ hoặc bàn giao kết quả cho vai trò khác không?
10. Thành công của dashboard này được đo bằng điều gì trong công việc của bạn?

Không hỏi “Bạn có thích tính năng X không?”. Yêu cầu người tham gia kể lại hành vi đã xảy ra và cho xem ví dụ khi có thể.

### Dữ liệu cần ghi nhận

- Tần suất thực hiện từng công việc.
- Thời gian và số lần chuyển công cụ.
- Các lỗi thường gặp và chi phí khắc phục.
- Thuật ngữ người dùng tự sử dụng.
- Thông tin họ cần trước khi xác nhận.
- Quyền sửa và phê duyệt theo vai trò.

## 7. Câu hỏi mở và rủi ro

| Mức | Vấn đề | Hành động đề xuất |
|---|---|---|
| Cao | `spec/execution_matrix.json` vẫn đánh dấu toàn bộ tuyến `SERIAL_DETECTIVE` là `DEFERRED`, trong khi Mốc 6 và runtime cho biết đã hỗ trợ | Chọn một nguồn sự thật và đồng bộ trước khi bật CTA tạo series |
| Cao | Runtime mới lưu `status: INITIALIZED` trong `run.json`; chưa có state tổng hợp đáng tin cậy cho dashboard | Định nghĩa API/state aggregator trước triển khai UI |
| Cao | Chưa có API web hoặc cơ chế job async | Chốt kiến trúc backend và contract tiến trình/lỗi |
| Trung bình | Chưa biết ai có quyền repair hoặc phê duyệt | Xác thực qua nghiên cứu; MVP có thể dùng một vai trò duy nhất |
| Trung bình | `MODEL_ASSESSED` có thể bị hiểu là đã xác minh | Kiểm thử microcopy và luôn hiển thị nguồn đánh giá |
| Trung bình | Chưa có ước tính thời gian/chi phí với provider thật | Không cam kết số liệu trong MVP; dùng trạng thái không xác định |
| Thấp | Tên file kỹ thuật không phù hợp với người dùng nội dung | Dùng tên thân thiện, cho xem tên file trong phần chi tiết |

## 8. Kết quả cần có sau nghiên cứu thực địa

- Persona được xác thực hoặc thay thế.
- Journey map của quy trình hiện tại.
- Top 5 pain point theo tần suất × mức ảnh hưởng.
- Thuật ngữ cuối cùng cho điều hướng.
- Danh sách chức năng MVP đã điều chỉnh.
- Quyết định rõ về quyền repair, phê duyệt và series.

