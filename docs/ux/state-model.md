# Mô hình trạng thái UI

## 1. Tách riêng các lớp trạng thái

UI không dùng một trường `status` duy nhất cho mọi mục đích. Có bốn lớp độc lập:

1. **Job state:** tác vụ kỹ thuật đang chạy đến đâu.
2. **Stage state:** stage đã sẵn sàng và có output hay chưa.
3. **Validation state:** từng kiểm tra đạt, không đạt hoặc chưa xác minh.
4. **Release readiness:** package có đủ điều kiện cho mục đích phát hành hay không.

Ví dụ: job có thể `SUCCEEDED`, nhưng release readiness vẫn là `BLOCKED` vì một quality gate không đạt.

## 2. Job state

| State | Nhãn UI | Hành động chính |
|---|---|---|
| `QUEUED` | Đang chờ | Hủy nếu backend hỗ trợ |
| `RUNNING` | Đang xử lý | Xem hoạt động |
| `SUCCEEDED` | Đã tạo đầu ra | Xem kết quả |
| `FAILED` | Xử lý thất bại | Xem lỗi, thử lại bằng run mới |
| `CANCELLED` | Đã hủy | Tạo run mới |

Runtime hiện chưa cung cấp đầy đủ state này; đây là contract cần bổ sung, không được suy diễn chỉ từ việc file output có tồn tại.

## 3. Stage state

| State | Điều kiện | Nhãn UI |
|---|---|---|
| `LOCKED` | Stage trước chưa có package đủ điều kiện | Bị khóa |
| `READY` | Có input hợp lệ, chưa khởi chạy | Sẵn sàng |
| `IN_PROGRESS` | Job hiện tại queued/running | Đang xử lý |
| `OUTPUT_AVAILABLE` | Job succeeded và có package | Có kết quả |
| `NEEDS_ATTENTION` | Có lỗi runtime hoặc blocker cần xử lý | Cần xử lý |

Không dùng `COMPLETED` nếu chưa nói rõ đó là hoàn thành pipeline hay hoàn thành kiểm định.

## 4. Validation roll-up

Thứ tự ưu tiên hiển thị:

1. `FAIL` trên `PUBLISH_BLOCKER`.
2. `NOT_VERIFIED` trên `PUBLISH_BLOCKER`.
3. `ASSESSED_FAIL` hoặc `FAIL` trên `QUALITY_BLOCKER`.
4. `NOT_VERIFIED` trên `QUALITY_BLOCKER`.
5. Advisory chưa đạt.
6. Các kiểm tra đạt.

`ASSESSED_PASS` không được nâng cấp thành `PASS`. Detector class luôn có thể xem trong chi tiết.

## 5. Release readiness

| State | Điều kiện | CTA |
|---|---|---|
| `BLOCKED` | Có publish blocker `FAIL` hoặc `NOT_VERIFIED` | Mở vấn đề cần xử lý |
| `QUALITY_REVIEW` | Không có publish blocker nhưng có quality blocker chưa đạt/chưa xác minh | Xem lại chất lượng |
| `READY` | Tất cả blocker bắt buộc đạt theo release rule | Tải gói phát hành |
| `NOT_APPLICABLE` | Package chỉ là checkpoint hoặc chưa có output | Tải checkpoint nếu có |

Quy tắc chính thức trong MVP contract vẫn có quyền ưu tiên nếu bảng trên chưa bao phủ một trường hợp.

## 6. Quy tắc mở stage tiếp theo

Stage tiếp theo chỉ mở khi:

- job hiện tại đã tạo package;
- package vượt qua verifier;
- source stage đúng với transition canonical;
- profile được giữ nguyên;
- route đó được enable;
- các publish blocker cần thiết cho transition không ở `FAIL` hoặc `NOT_VERIFIED`.

Chính sách với quality blocker trước transition cần được product owner xác nhận. Trong lúc chưa chốt, UI hiển thị cảnh báo và không gắn nhãn “đã duyệt”.

## 7. Ma trận hành động

| Tình huống | Xem | Tải checkpoint | Chạy stage tiếp | Publish | Repair |
|---|---:|---:|---:|---:|---:|
| Job đang chạy | Có | Không | Không | Không | Không |
| Job thất bại, chưa có output | Có | Không | Không | Không | Không |
| Package integrity lỗi | Có | Có cảnh báo | Không | Không | Không |
| Publish blocker fail | Có | Có cảnh báo | Không | Không | Nếu artifact thuộc stage |
| Publish blocker not verified | Có | Có cảnh báo | Không | Không | Tùy nguyên nhân |
| Quality blocker fail | Có | Có | Chờ quyết định policy | Không | Nếu artifact thuộc stage |
| Tất cả blocker đạt | Có | Có | Có | Theo package purpose | Có, tạo package mới |

## 8. Trạng thái lỗi và phục hồi

- Mất kết nối UI không đồng nghĩa job thất bại; khi kết nối lại phải lấy state từ backend.
- Refresh trang không tạo job mới.
- Submit lặp dùng idempotency key hoặc bị vô hiệu hóa cho đến khi nhận job ID.
- Thử lại tạo run/package mới và giữ liên kết với lần thất bại.
- Repair không sửa tại chỗ package nguồn.
- Nếu event log hỏng một dòng, UI vẫn hiển thị các event đọc được và cảnh báo dữ liệu không đầy đủ.

