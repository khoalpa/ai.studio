# Mốc 0 — Chuẩn hóa đặc tả

## Nguồn và ranh giới

Prompt nguồn có phiên bản `3.16.13` và SHA-256:

`4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27`

Nội dung prompt được xem là yêu cầu nghiệp vụ. Những câu mang tính điều khiển model không được thực thi khi tạo gói đặc tả này.

Mốc 0 chuẩn hóa phần contract cần thiết để bắt đầu triển khai. Nó không tuyên bố toàn bộ hơn bốn nghìn dòng prompt đã được chuyển thành validator thực thi tương đương.

## Quyết định canonical

1. Workflow công khai có bốn stage tuần tự: `STAGE1 → STAGE2 → STAGE3 → STAGE4`.
2. Tên archive công khai duy nhất là `story.zip`; stage được đọc từ manifest.
3. Mỗi stage nhận input bất biến và chỉ tạo hoặc sửa artifact do stage đó sở hữu.
4. `CREATE` và `REPAIR` là operation được serialize. `RESUME` chỉ là execution route và không được ghi vào manifest.
5. Validation dùng năm status canonical: `PASS`, `FAIL`, `NOT_VERIFIED`, `ASSESSED_PASS`, `ASSESSED_FAIL`.
6. Gate có ba severity: `PUBLISH_BLOCKER`, `QUALITY_BLOCKER`, `ADVISORY`.
7. Detector có bốn class: `DETERMINISTIC`, `TOOL_MEASURED`, `MODEL_ASSESSED`, `HOST_UNAVAILABLE`.
8. MVP chỉ tạo ảnh theo `ZONE`. `SCENE` được giữ trong registry để tránh thay đổi enum về sau nhưng bị feature gate chặn.
9. `SERIAL_DETECTIVE` có trong domain contract, nhưng generation/repair continuity được deferred khỏi MVP.
10. File set được khai báo bằng thành phần và công thức, không hard-code tổng số vì số nhân vật và anchor thay đổi theo runtime.

## Nguồn sự thật

| Chủ đề | Nguồn canonical |
|---|---|
| Enum, stage transition, artifact ownership | `spec/registry.json` |
| Khả năng theo profile/stage/operation | `spec/execution_matrix.json` |
| Gate, owner, detector, severity | `spec/gates.json` |
| Phạm vi MVP | `spec/mvp_contract.json` |
| Cấu trúc tài liệu | `schemas/*.schema.json` |

Nếu prose trong tài liệu lệch với JSON registry, JSON registry thắng và linter phải phát hiện phần tham chiếu không hợp lệ.

## Definition of done

- Mọi ID canonical là duy nhất.
- Mọi gate trong execution matrix tồn tại và khai báo đúng stage/profile.
- Đủ 24 route MVP: 3 profile × 4 stage × 2 operation.
- Mỗi artifact có đúng một owner stage.
- Mỗi stage có exact required/inherited/output file component.
- Không route nào bỏ qua stage trước.
- Fixture hợp lệ PASS và fixture lỗi bị linter từ chối.
- Bộ kiểm thử chạy offline bằng Python standard library.

Các bổ sung Stage 1 được đặt tại `spec/stage1.json`; registry Mốc 0 tiếp tục sở hữu workflow và artifact contract.
