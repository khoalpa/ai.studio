# Mốc 6 — Serial và vận hành nâng cao

## Đã triển khai

- `SERIAL_DETECTIVE` dùng `series_anchor.json` schema 3.2.0.
- `START_SERIES`, `CONTINUE_SERIES`, `FINALIZE_SERIES` với duration router riêng.
- Clone-before-mutate anchor transaction.
- Revision/latest episode tăng đúng một lần và episode ledger liên tục.
- Series/story title, episode, author, channel và profile binding.
- Anchor được giữ nguyên byte trong Stage 2–4.
- Serial được phép chạy tuyến ZONE Stage 1 → Stage 4.
- `PackageRepairSession` từ chối sửa artifact kế thừa hoặc xóa artifact canonical.
- `RunIndex` tổng hợp `run.json`, event count, last event và output package.
- CLI hỗ trợ serial generation và `list-runs`.

## Vẫn deferred

- SCENE mode.
- Resume bundle Stage 2/3.
- Legacy anchor/package migration.
- External framework conformance audit.
- Dashboard web; hiện dùng run index JSON qua CLI.

Các phần deferred không được runtime tự tuyên bố PASS. Provider deterministic vẫn chỉ dành cho development/test.
