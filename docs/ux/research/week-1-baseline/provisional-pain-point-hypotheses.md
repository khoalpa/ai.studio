# Năm giả thuyết pain point cần xác thực

Danh sách này được tổng hợp từ walkthrough kỹ thuật, code audit và tài liệu QA. Đây chưa phải top 5 pain point của người dùng. Không gán điểm tần suất trước khi hoàn thành năm phiên chính.

## H1 — Đơn vị công việc chưa rõ

Giao diện đồng thời dùng các khái niệm truyện, run, stage, workflow và package. Người vận hành có thể không biết đối tượng nào đại diện cho toàn bộ công việc của họ.

Quan sát cần tìm: người dùng gọi đối tượng đang mở là gì và họ tìm lịch sử của cùng một truyện ở đâu.

Hướng Tuần 2 nếu được xác thực: lấy “Truyện” làm thực thể chính, nhóm các run theo workflow và đưa run ID vào lớp chi tiết kỹ thuật.

## H2 — Hoàn thành xử lý dễ bị hiểu là sẵn sàng phát hành

Một package có thể qua integrity, pipeline hoàn thành và vẫn có release status `BLOCKED`. Nhiều trạng thái đúng nhưng đặt gần nhau có thể dẫn đến kết luận sai.

Quan sát cần tìm: kết luận của người dùng trong T2 và T4 trước khi người điều phối giải thích.

Hướng Tuần 2 nếu được xác thực: dùng một khối “Quyết định tiếp theo” tổng hợp, giữ chi tiết integrity và execution ở lớp mở rộng.

## H3 — Blocker chưa dẫn thẳng tới hành động

Validation Center hiển thị trạng thái, evidence và chi tiết kỹ thuật nhưng repair editor còn chưa hoàn chỉnh. Người dùng có thể hiểu lỗi mà vẫn không biết phải đi đâu tiếp.

Quan sát cần tìm: hành động đầu tiên sau khi người dùng chọn đúng blocker.

Hướng Tuần 2 nếu được xác thực: gắn mỗi blocker với CTA theo ngữ cảnh như mở artifact, quay về stage sở hữu hoặc tạo lại.

## H4 — Chuyển đổi giữa workspace và Tác vụ làm mất ngữ cảnh

Tác vụ dài được theo dõi ở màn hình riêng trong khi quyết định nội dung diễn ra trong workspace. Người dùng có thể không biết nên ở lại modal, đóng modal hay mở Tác vụ.

Quan sát cần tìm: sau khi submit T1, người dùng đi đâu và dấu hiệu nào khiến họ tin tác vụ đã được gửi.

Hướng Tuần 2 nếu được xác thực: duy trì job status trong workspace và dùng Tác vụ như lịch sử hoặc trung tâm chẩn đoán.

## H5 — Cấu hình kỹ thuật xuất hiện quá sớm

Provider, preset và model hữu ích cho quản trị kỹ thuật nhưng có thể tăng tải nhận thức trong luồng tạo truyện của operator nội dung.

Quan sát cần tìm: thời gian dừng, câu hỏi và lựa chọn sai ở bước cấu hình T1/T3.

Hướng Tuần 2 nếu được xác thực: dùng mặc định dự án và đặt cấu hình kỹ thuật trong “Tùy chọn nâng cao”.
