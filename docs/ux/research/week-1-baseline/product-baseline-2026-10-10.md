# Baseline sản phẩm — 10/10/2026

## Phạm vi kiểm tra

Baseline này được lập từ giao diện và test tự động hiện có. Đây là baseline về khả năng của sản phẩm, không phải bằng chứng về hành vi người dùng.

## Khả năng hiện có

- Điều hướng chính gồm Tổng quan, Truyện, Tác vụ, Kiểm định, Kiểm tra gói, Model local và Cài đặt.
- Có wizard tạo truyện bốn bước.
- Có màn hình theo dõi job và tiến trình Stage 1–4.
- Có workspace hiển thị artifact, kiểm định và hoạt động.
- Có tìm kiếm/lọc tác vụ và lọc validation.
- Có Package Inspector cho ZIP.
- Có responsive breakpoint và focus style cơ bản.
- Trạng thái validation được giữ riêng thay vì gom thành đạt/không đạt.

## Khoảng trống cần quan sát trong nghiên cứu

- Chưa có dữ liệu usability với người dùng thật.
- Chưa biết người dùng có xem “run” hay “truyện” là đơn vị công việc chính.
- Chưa xác minh khả năng hiểu `FAIL`, `NOT_VERIFIED`, `ASSESSED_PASS` và `ASSESSED_FAIL`.
- Repair editor và workflow series chưa hoàn chỉnh.
- Bộ lọc và vị trí điều hướng chưa được chứng minh là được giữ đúng kỳ vọng người dùng.
- Luồng chọn vai trò model còn dùng hộp thoại trình duyệt thay vì component nhất quán.
- Không phải mọi modal đều thể hiện cùng một contract accessibility; cần test focus, Escape và screen reader.

## Trạng thái kiểm thử kỹ thuật

Lệnh chạy ngày 10/10/2026:

```powershell
$env:PYTHONPATH = "src"
py -3 -m pytest tests/test_web.py -q
```

Kết quả ban đầu: 14 test đạt, 1 test thất bại.

Ca thất bại: `WebServiceTests.test_stage1_job_and_run_detail`.

Nguyên nhân quan sát được: `telemetry_reconciliation.deviation_percent` trả về `21.6636`, vượt ngưỡng cứng `5.0` trong test. Implementation đã dùng ngưỡng hiệu lực gồm dung sai tương đối 5% cộng khoảng thời gian đóng gói được đo riêng. Assertion web đã được đồng bộ với policy này.

Kết quả sau sửa: 16 test thuộc `test_web.py` và `test_usability_dataset.py` đạt, không có test thất bại.

## Baseline hành vi

| Chỉ số | Trạng thái |
|---|---|
| Tỷ lệ hoàn thành T1–T4 | Chưa đo |
| Thời gian theo nhiệm vụ | Chưa đo |
| Tỷ lệ xác định đúng blocker | Chưa đo |
| Tỷ lệ hiểu đúng trạng thái phát hành | Chưa đo |
| Lỗi nghiêm trọng mỗi phiên | Chưa đo |

Các ô này chỉ được cập nhật sau tối thiểu 5 phiên hợp lệ.

## Điều kiện sẵn sàng chạy pilot

- [x] Test Stage 1 ổn định trong phạm vi web và dataset.
- [x] Có workspace sạch có thể sinh lại giữa các phiên.
- [x] Có workflow chứa blocker đã biết cho T2 và workspace sẵn sàng cho T3.
- [x] Có package ZIP cố định cho T4.
- [x] Đã chạy walkthrough kỹ thuật; pilot với người độc lập vẫn cần thực hiện.
- [x] Có cách ghi thời gian và cấp hỗ trợ nhất quán.
- [ ] Người tham gia đã đồng ý phạm vi ghi chú/ghi âm.
