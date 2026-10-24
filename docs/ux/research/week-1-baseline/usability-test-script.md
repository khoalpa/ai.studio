# Kịch bản usability test

## Chuẩn bị trước phiên

- Dùng đúng build đã ghi trong baseline sản phẩm.
- Khởi động server ở localhost và kiểm tra trang Tổng quan tải được.
- Mở `clean_workspace` trong `study-manifest.json` cho Nhiệm vụ 1.
- Mở `blocked_workspace` và đúng `blocked_run_id` cho Nhiệm vụ 2.
- Khởi động lại server với `ready_workspace`, sau đó mở cùng run ID cho Nhiệm vụ 3. Không yêu cầu người tham gia chờ sửa blocker trong phiên.
- Dùng `warning_package` trong manifest cho Nhiệm vụ 4.
- Tắt thông báo không liên quan và không mở sẵn trang đích.

## Mở đầu — 5 phút

Đọc nguyên văn:

> Cảm ơn bạn đã tham gia. Hôm nay chúng tôi kiểm tra sản phẩm, không kiểm tra bạn. Một số phần có thể chưa rõ hoặc chưa hoạt động như mong đợi; đó chính là điều chúng tôi muốn phát hiện. Trong lúc làm, hãy nói thành tiếng điều bạn đang tìm, điều bạn nghĩ sẽ xảy ra và điều khiến bạn phân vân. Tôi sẽ không hướng dẫn vị trí nút, nhưng có thể nhắc lại yêu cầu của nhiệm vụ. Bạn có thể dừng bất cứ lúc nào.

Hỏi ngắn:

1. Bạn thường tạo hoặc duyệt nội dung bằng quy trình nào?
2. Khi thấy một đầu ra AI, bạn kiểm tra điều gì trước?
3. Các từ “giai đoạn”, “lần chạy”, “package” và “kiểm định” gợi cho bạn điều gì?

## Nhiệm vụ 1 — Tạo Stage 1

Đưa cho người tham gia:

> Bạn cần tạo một truyện thiếu nhi dài khoảng 15 phút. Nội dung nói về một đứa trẻ giữ lời hứa sau một trận mưa. Hãy bắt đầu tạo phần nội dung và nhân vật. Dừng lại khi bạn tin rằng yêu cầu đã được gửi thành công.

Quan sát:

- Điểm bắt đầu và CTA được chọn.
- Cách hiểu loại nội dung, brief, thời lượng, provider và preset.
- Lỗi nhập liệu hoặc quay lại giữa các bước.
- Dấu hiệu cho thấy người tham gia tin tác vụ đã được gửi.

Câu hỏi sau nhiệm vụ:

- Bạn nghĩ hệ thống đang làm gì tiếp theo?
- Bạn sẽ đi đâu để xem tiến trình?
- Mức tự tin từ 1 đến 5?

## Nhiệm vụ 2 — Xác định blocker đầu tiên

Đưa cho người tham gia:

> Truyện này đã xử lý xong nhưng chưa thể đi tiếp. Hãy tìm vấn đề quan trọng nhất cần xử lý và giải thích vì sao nó chặn workflow.

Không yêu cầu sửa lỗi. Ghi nhận record đầu tiên người dùng chọn, cách họ phân biệt `FAIL`, `NOT_VERIFIED` và trạng thái AI đánh giá.

Câu hỏi sau nhiệm vụ:

- Bằng chứng nào khiến bạn chọn vấn đề này?
- Bạn sẽ làm gì tiếp theo nếu đang làm việc thật?
- “Đã xử lý xong” có đồng nghĩa với “sẵn sàng phát hành” không?

## Nhiệm vụ 3 — Chạy stage tiếp theo

Đưa cho người tham gia:

> Sau khi vấn đề đã được xử lý, bạn muốn tạo hình ảnh ngang cho truyện. Hãy tìm cách bắt đầu giai đoạn tiếp theo. Dừng trước lần xác nhận cuối cùng.

Trước nhiệm vụ, người điều phối chuyển sang workspace sẵn sàng và nói: “Bây giờ hãy giả định vấn đề vừa xem đã được xử lý.” Việc chuyển workspace không được tính vào thời gian nhiệm vụ.

Quan sát:

- Người dùng có hiểu stage hiện tại và stage tiếp theo hay không.
- Họ có nhận ra điều kiện bị khóa và lý do hay không.
- Họ có hiểu cấu hình trong dialog khởi chạy hay không.

## Nhiệm vụ 4 — Kiểm tra package bên ngoài

Đưa cho người tham gia:

> Một đồng nghiệp gửi cho bạn file ZIP này. Hãy kiểm tra file và cho biết: cấu trúc có hợp lệ không, có cảnh báo nào không và bạn có khuyên dùng nó làm đầu vào tiếp theo hay không.

Quan sát khả năng tìm Package Inspector và khả năng tách ba khái niệm: integrity, chất lượng nội dung và khuyến nghị phát hành.

## Kết thúc — 10 phút

1. Phần nào làm bạn mất nhiều công sức nhất?
2. Có thuật ngữ nào khó hiểu hoặc mang nghĩa khác với công việc của bạn?
3. Bạn xem đơn vị công việc là truyện, tập, workflow, run hay package?
4. Thông tin nào bạn muốn thấy ngay trên Tổng quan?
5. Nếu chỉ được sửa một điểm, bạn sẽ chọn gì?
6. Chấm mức dễ sử dụng chung từ 1 đến 7 và giải thích.

Sau khi kết thúc, người điều phối hoàn thành phiếu ghi nhận trước khi bắt đầu phiên tiếp theo.

## Thay đổi sau pilot nội bộ ngày 10/10/2026

- Tách workspace có blocker và workspace sẵn sàng để Nhiệm vụ 3 không bị khóa giả tạo.
- Ghi rõ điểm dừng của Nhiệm vụ 3 là trước xác nhận cuối, tránh tạo Stage 2 tốn thời gian trong phiên.
- Dùng đường dẫn từ manifest thay vì tên file hoặc run ID viết tay.
- Yêu cầu ghi riêng lỗi môi trường để không tính vào lỗi sử dụng.
