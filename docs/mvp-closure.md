# Đóng dự án MVP

Trạng thái nghiệm thu: **PASS_WITH_WARNINGS**.

MVP được xem là hoàn tất cho workflow local deterministic. Ba profile canonical đã chạy xuyên
Stage 1–4, package và release bundle đều vượt kiểm tra integrity. Gate chất lượng hoạt động theo
chính sách advisory: workflow tiếp tục, warning được giữ trong validation ledger và bundle chưa đủ
điều kiện phát hành mang nhãn `NOT_APPROVED`.

## Bằng chứng nghiệm thu

- Báo cáo máy đọc: `artifacts/mvp-acceptance-final-v2/mvp_acceptance_report.json`.
- Báo cáo người đọc: `artifacts/mvp-acceptance-final-v2/mvp_acceptance_report.md`.
- Report digest: `cef9b344e0bf741bb0e4a92e9ab6f260fb1588fa2ea67dba27bf95942a84a1a9`.
- Ruff, spec lint và 155 test cùng 11 subtest đều đạt.
- `YOUTH_SAFE`, `ADULT_STANDARD` và `SERIAL_DETECTIVE` đều hoàn thành Stage 1–4.

## Giới hạn được chấp nhận

- `hybrid`, `text_local` và `local` chưa được chạy nghiệm thu vì chưa có model local được chọn và
  chưa có đủ runtime evidence. Chúng được ghi `NOT_EXECUTED`, không được coi là production-ready.
- Ba bundle deterministic mang `NOT_APPROVED`, đúng với artifact class và visual review chưa duyệt.
- Authentication, multi-user deployment và production hosting nằm ngoài phạm vi MVP local.

## Chạy lại nghiệm thu

```powershell
uv run python tools/validate_mvp.py --output artifacts/mvp-acceptance
```

Lệnh trả mã lỗi chỉ khi lint, test, workflow hoặc integrity thất bại. Quality warning và provider
không được cấu hình vẫn được đưa vào báo cáo mà không làm dừng ma trận nghiệm thu.
