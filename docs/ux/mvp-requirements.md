# Yêu cầu MVP

## 1. Phạm vi

MVP cung cấp web dashboard local cho workflow đã tồn tại. UI không thay đổi quy tắc canonical của package và không tự tuyên bố kết quả kiểm định.

### Trong phạm vi

- Danh sách và chi tiết lần chạy.
- Tạo truyện với `YOUTH_SAFE` và `ADULT_STANDARD`.
- Tuyến tuần tự Stage 1–4.
- `ZONE` image mode.
- Preview artifact và tải package.
- Validation center.
- Package inspector.
- Repair có kiểm soát ownership.
- Series trinh thám sau khi giải quyết mâu thuẫn đặc tả.

### Ngoài phạm vi

- `SCENE` image mode.
- Resume bundle Stage 2/3.
- Legacy migration.
- Cộng tác realtime và phân quyền nhiều vai trò.
- Chỉnh sửa ảnh/video chuyên sâu.
- Billing hoặc dự báo chi phí provider.
- Tự xác nhận framework release audit.

## 2. Ưu tiên

### P0 — Bắt buộc cho MVP

| ID | Yêu cầu | Acceptance criteria |
|---|---|---|
| R01 | Hiển thị danh sách run | Có profile, thời gian tạo, last event, output package và empty state |
| R02 | Tạo Stage 1 bằng wizard | Bắt buộc brief, profile, ngôn ngữ và xác nhận thời lượng hợp lệ |
| R03 | Điều hướng workflow tuần tự | Stage sau bị khóa khi chưa có package hợp lệ từ stage trước |
| R04 | Khởi chạy Stage 2–4 | Backend luôn verify input package trước khi chạy |
| R05 | Hiển thị trạng thái tác vụ | Có ít nhất queued/running/succeeded/failed và thời điểm cập nhật |
| R06 | Hiển thị validation | Giữ nguyên năm trạng thái; sắp blocker chưa đạt lên đầu |
| R07 | Phân biệt hoàn thành và phát hành được | Pipeline succeeded không tự động tạo nhãn “Sẵn sàng phát hành” |
| R08 | Preview artifact | Hỗ trợ nội dung truyện, ảnh, visual plan, quality report và video prompt ở mức đọc |
| R09 | Tải package | Tải đúng checkpoint/release package và hiển thị stage/purpose |
| R10 | Package inspector | Verifier kiểm ZIP trước; UI hiển thị manifest, file set và integrity |
| R11 | Repair ownership | Không cho sửa/xóa artifact kế thừa hoặc canonical artifact trái quy tắc |
| R12 | Xử lý lỗi | Mọi lỗi có thông điệp người dùng, mã/chi tiết kỹ thuật và hành động tiếp theo |

### P1 — Nên có ngay sau lõi

| ID | Yêu cầu | Acceptance criteria |
|---|---|---|
| R13 | Tìm kiếm và lọc | Tìm theo run ID/tên truyện; lọc profile, stage, status |
| R14 | Activity log | Hiển thị event theo thời gian; payload kỹ thuật được thu gọn |
| R15 | Series workspace | Series chứa danh sách tập và revision anchor hiện tại |
| R16 | Tạo/tiếp tục/kết thúc series | Chỉ bật khi route được xác định là enabled trong nguồn sự thật |
| R17 | Dẫn về stage sở hữu | Khi artifact chỉ đọc, UI chỉ ra nơi có thể repair |
| R18 | Giữ bộ lọc và trạng thái điều hướng | Quay lại danh sách không làm mất context |

### P2 — Sau MVP

- So sánh package trước/sau repair.
- Thông báo desktop khi job hoàn thành.
- Batch operations.
- Dashboard analytics.
- Vai trò reviewer và approval workflow.

## 3. Yêu cầu phi chức năng

### Accessibility

- WCAG 2.1 AA cho luồng chính.
- Toàn bộ thao tác khả dụng bằng bàn phím.
- Focus không bị mất khi job cập nhật trạng thái.
- Màu không phải tín hiệu trạng thái duy nhất.
- Ảnh có alt hoặc được đánh dấu decorative phù hợp.

### Hiệu năng cảm nhận

- Skeleton chỉ dùng khi thực sự đang tải dữ liệu.
- Phản hồi thao tác trong 100 ms bằng trạng thái cục bộ.
- Không hiển thị phần trăm tiến độ giả.
- Gallery dùng lazy loading và thumbnail.

### Tin cậy và an toàn

- Không ghi đè package nguồn khi repair hoặc chạy lại.
- Các CTA phát hành dựa trên gate state từ backend.
- Không cho UI tự đổi kết quả validation.
- Escape nội dung log và JSON trước khi render.
- Không tin đường dẫn hoặc tên file trong ZIP.

### Quốc tế hóa

- MVP có giao diện tiếng Việt; kiến trúc chuỗi sẵn sàng cho tiếng Anh.
- Nội dung truyện `vi` và `en` không phụ thuộc ngôn ngữ giao diện.
- Không nối chuỗi thủ công làm vỡ ngữ pháp khi dịch.

## 4. Chỉ số thành công ban đầu

- 90% người thử nghiệm hoàn thành tạo Stage 1 mà không được hướng dẫn.
- Median time từ dashboard đến khi submit Stage 1 dưới 5 phút.
- 90% người thử nghiệm xác định đúng blocker cần xử lý đầu tiên.
- 100% thử nghiệm repair artifact kế thừa bị ngăn trước khi tạo package.
- Không có trường hợp nhãn “Sẵn sàng phát hành” khi tồn tại publish blocker `FAIL` hoặc `NOT_VERIFIED`.
- Giảm ít nhất 50% thao tác sao chép đường dẫn/package so với CLI trong tuyến Stage 1–4.

## 5. Dữ liệu backend/UI còn thiếu

Trước implementation, cần contract bổ sung:

- Story/workflow ID liên kết nhiều run.
- Job state và timestamps chuẩn hóa.
- Current stage và next allowed action.
- Validation summary theo severity/status.
- Tên hiển thị hoặc title lấy từ `story.json`.
- Quan hệ input/output/parent package.
- Cơ chế đọc preview artifact an toàn.
- API repair với danh sách đường dẫn được phép thay đổi.

