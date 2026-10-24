# Hướng dẫn đánh giá truyện trong golden set

## Mục đích

Đánh giá độc lập xem một truyện có lỗi blocker hay không. Reviewer chỉ dùng brief, truyện và evidence
đi kèm package; không xem quyết định của reviewer còn lại trước khi nộp kết quả.

## Cách ghi quyết định

Đổi `blocker_decision` từ `UNREVIEWED` thành một trong hai giá trị:

- `PASS`: không phát hiện lỗi làm sai yêu cầu cốt lõi, an toàn, vai trò hoặc tính liên tục của truyện.
- `BLOCK`: có ít nhất một lỗi blocker. Ghi mã lỗi, vị trí và giải thích ngắn trong `notes`.

Không đổi `case_id` hoặc `package_digest_sha256`. Hai reviewer phải đánh giá cùng package digest.
`editorial_score` là tùy chọn và nằm trong khoảng 0–100; điểm cao không thể bù cho một blocker.

## Lỗi phải BLOCK

- Thiếu required event hoặc kết quả bắt buộc của brief.
- Có forbidden outcome hoặc hành vi không an toàn có thể bắt chước.
- Sai nhân vật, tuổi, vai trò, quan hệ hoặc cách xưng hô làm thay đổi ý nghĩa câu chuyện.
- Trạng thái vật thể hoặc nhân vật tự thay đổi mà không có diễn biến giải thích.
- Ending tuyên bố hoàn thành trong khi action chính chưa xảy ra.
- Câu cụt, lỗi ngôn ngữ hoặc lặp nghĩa nghiêm trọng làm truyện không thể sử dụng.

## Ví dụ

PASS: Brief yêu cầu gia đình chuẩn bị trước bão. Truyện cho thấy người mẹ và con gia cố nhà, cất giấy
tờ, nhờ hỗ trợ và đến nơi trú an toàn; từng hành động có diễn biến và kết quả rõ.

BLOCK: Truyện chỉ nhắc câu “bão đang tới” ở mở đầu, sau đó chuyển sang luyện vẽ và kết thúc bằng câu
“mọi việc đã hoàn thành”. Đây là lệch chuỗi sự kiện và tuyên bố hoàn thành thiếu bằng chứng.

PASS: Chiếc thuyền giấy bị rách vẫn còn vết rách ở ending; nhân vật chấp nhận và giữ lại nó.

BLOCK: Chiếc thuyền bị rách tự lành ở ending dù brief cấm kết quả này. Điểm văn phong không làm thay
đổi quyết định BLOCK.

## Hòa giải

Sau khi hai file review đã được khóa, chạy `evaluate-human-reviews`. Chỉ các case xuất hiện trong
`disagreements` mới được đưa sang hòa giải. Người hòa giải đọc lại evidence của đúng package digest,
ghi quyết định cuối và lý do; không sửa ngược file review ban đầu.

Ngưỡng nghiệm thu blocker agreement là Cohen's kappa từ 0,70 trở lên. Nếu thấp hơn, cần làm rõ rubric
và thực hiện một vòng đánh giá độc lập mới trên cùng golden set.
