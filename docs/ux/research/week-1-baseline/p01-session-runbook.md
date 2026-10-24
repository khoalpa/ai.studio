# Runbook phiên P01 — Vận hành nội dung

## Trạng thái sẵn sàng

- Dataset cố định đã được sinh tại `artifacts/usability-study/week1-v1`.
- Manifest: `artifacts/usability-study/week1-v1/study-manifest.json`.
- Vai trò cần tuyển: vận hành nội dung, mức kỹ thuật thấp hoặc trung bình.
- Thời lượng dự kiến: 45–60 phút.
- Chưa được phép ghi phiên là hợp lệ trước khi có người tham gia độc lập và phiếu đồng ý.

## Trước khi người tham gia vào phiên

1. Xác nhận người tham gia chưa phát triển giao diện và chưa xem kịch bản nhiệm vụ.
2. Gán mã `P01`; không ghi tên, email hoặc thông tin nhận dạng vào tài liệu nghiên cứu.
3. Ghi build hoặc commit đang kiểm thử.
4. Mở `study-manifest.json` và dùng đúng đường dẫn trong manifest.
5. Tắt thông báo, đóng màn hình đích và đặt zoom trình duyệt ở 100%.
6. Khởi động workspace sạch cho T1:

```powershell
$env:PYTHONPATH = "src;."
py -3 -m ai_story serve `
  --root artifacts/usability-study/week1-v1/clean-workspace `
  --host 127.0.0.1 --port 8765
```

7. Mở `http://127.0.0.1:8765` và xác nhận trang Tổng quan tải được.

## Điều phối bốn nhiệm vụ

- Đọc nguyên văn phần mở đầu và từng nhiệm vụ trong `usability-test-script.md`.
- Bấm giờ từ lúc đọc xong yêu cầu đến khi người tham gia tuyên bố hoàn tất.
- Không chỉ vị trí nút hoặc giải thích thuật ngữ khi nhiệm vụ đang chạy.
- Nếu phải hỗ trợ, ghi đúng cấp hỗ trợ và thời điểm trước khi can thiệp.
- Với T2, dừng server và khởi động lại bằng `blocked-workspace`; mở run có ID trong
  trường `blocked_run_id` của manifest.
- Với T3, chuyển sang `ready-workspace`; không tính thời gian chuyển workspace vào nhiệm vụ.
- Với T4, chọn package tại đường dẫn `warning_package` trong manifest.

## Ngay sau phiên

1. Hoàn thành `p01-session-notes.md` trước phiên kế tiếp.
2. Chỉ đặt `session_valid=TRUE` khi không có lỗi môi trường làm sai kết quả.
3. Thêm đúng một dòng vào `validation-session-results.csv` với
   `session_source=HUMAN` và `role=OPERATIONS`.
4. Không chép tên hoặc nội dung nhận dạng vào CSV, telemetry hay ghi chú.
5. Chạy cổng hoàn thành:

```powershell
py -3 tools/evaluate_ux_validation.py `
  --sessions docs/ux/research/week-1-baseline/validation-session-results.csv `
  --nvda docs/ux/research/week-1-baseline/nvda-validation-result.json `
  --output docs/ux/research/week-1-baseline/validation-completion-report.md
```

Mã thoát `2` là bình thường khi chưa đủ năm phiên hoặc chưa có phiên NVDA thật.

## Điều kiện hoàn tất riêng cho P01

- Có đồng ý tham gia và ghi chú.
- Hoàn thành hoặc thử thực hiện đủ bốn nhiệm vụ.
- Mỗi nhiệm vụ có kết quả, thời gian, mức hỗ trợ, lỗi nghiêm trọng và độ tự tin.
- Có câu trả lời cho ba kiểm tra mức hiểu và điểm dễ sử dụng tổng thể.
- Có phiếu ghi nhận hoàn chỉnh và đúng một dòng CSV tương ứng.
- Không có thông tin nhận dạng trong artifact nghiên cứu.
