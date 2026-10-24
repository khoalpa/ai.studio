# Tuần 2 — Wireframes

## 1. Phạm vi

Bộ wireframe low-fidelity bao phủ năm bề mặt quan trọng nhất của MVP:

1. Dashboard và danh sách truyện.
2. Wizard tạo truyện.
3. Workspace bốn stage.
4. Validation center.
5. Package inspector.

Mục tiêu của wireframe là kiểm tra kiến trúc thông tin, thứ tự thao tác và khả năng hiểu trạng thái. Màu sắc, typography thương hiệu và hình ảnh minh họa chưa phải quyết định cuối cùng.

## 2. Quy ước bố cục

### Application shell

- Sidebar trái chứa điều hướng cấp sản phẩm: Tổng quan, Truyện, Series, Kiểm tra gói.
- Header chứa ngữ cảnh hiện tại và hành động cấp trang.
- Nội dung chính dùng chiều rộng linh hoạt; validation blocker không bị giấu trong drawer mặc định.
- Ở màn hình dưới 760 px, sidebar trở thành thanh điều hướng trên và các cột xếp dọc.

### Trạng thái và hành động

- Mỗi màn hình có tối đa một CTA chính.
- Stage stepper luôn giữ nguyên thứ tự 1–4.
- Trạng thái dùng cả nhãn và ký hiệu; không chỉ dùng màu.
- Chi tiết kỹ thuật được thu gọn mặc định.
- Hành động bị khóa có lý do hiển thị gần nút, không chỉ dùng tooltip.

## 3. WF-01 — Dashboard

### Mục tiêu

Giúp người dùng trả lời nhanh ba câu hỏi: công việc nào cần xử lý, công việc nào vừa hoàn thành và bắt đầu truyện mới ở đâu.

### Cấu trúc

```text
┌ Sidebar ─────┬ Header: Tổng quan ─────────────── [Tạo truyện mới] ┐
│ Tổng quan    │                                                     │
│ Truyện       │ Cần xử lý                                          │
│ Series       │ [Run có blocker] [Run lỗi runtime]                 │
│ Kiểm tra gói │                                                     │
│              │ Truyện gần đây                         [Bộ lọc]     │
│              │ Tên | Loại | Stage | Trạng thái | Cập nhật | →     │
└──────────────┴─────────────────────────────────────────────────────┘
```

### Nội dung mẫu

- “Một lời hứa sau mưa” — Truyện thiếu nhi — Hình ảnh ngang — Cần xử lý.
- “Căn phòng khóa kín” — Series trinh thám — Nội dung & nhân vật — Đang xử lý.
- “Người giữ đèn” — Truyện người lớn — Prompt video — Sẵn sàng phát hành.

### Acceptance notes

- “Cần xử lý” nằm trước “Gần đây”.
- Không thêm KPI không dẫn đến hành động.
- Empty state có giải thích workflow và CTA tạo truyện đầu tiên.

## 4. WF-02 — Wizard tạo truyện

### Bước 1: Loại nội dung

- Ba lựa chọn dạng radio-card: Truyện thiếu nhi, Truyện người lớn, Series trinh thám.
- Mỗi lựa chọn có đối tượng và mô tả ngắn.
- Series trinh thám bị vô hiệu hóa nếu route chưa được xác nhận enabled.

### Bước 2: Nội dung và thời lượng

- Brief bắt buộc.
- Ngôn ngữ: Tiếng Việt / English.
- Thời lượng hiển thị khoảng hợp lệ và giá trị đề xuất.
- Checkbox xác nhận thời lượng chỉ xuất hiện sau khi giá trị hợp lệ.

### Bước 3: Cấu hình series

Chỉ hiển thị với Series trinh thám:

- Bắt đầu / tiếp tục / kết thúc series.
- Tên series hoặc lựa chọn series đã tồn tại.
- Số tập dự kiến với chế độ bắt đầu.
- Revision và tập gần nhất là thông tin chỉ đọc.

### Bước 4: Kiểm tra

- Tóm tắt loại nội dung, brief, ngôn ngữ và thời lượng.
- Cảnh báo giới hạn môi trường/provider nếu có.
- CTA “Tạo nội dung”; không dùng nhãn chung chung “Hoàn tất”.

## 5. WF-03 — Run workspace

### Cấu trúc

```text
┌ Sidebar ─┬ Tên truyện | Loại | Trạng thái ────── [Tải checkpoint] ┐
│          │ ① Nội dung  ② Ảnh ngang  ③ Ảnh dọc  ④ Prompt video    │
│          ├─────────────────────────────┬───────────────────────────┤
│          │ Kết quả                     │ Kiểm tra                  │
│          │ Preview truyện/gallery      │ 2 chặn phát hành          │
│          │                             │ [Mở từng vấn đề]           │
│          ├─────────────────────────────┴───────────────────────────┤
│          │ Hoạt động gần đây                                       │
└──────────┴─────────────────────────────────────────────────────────┘
```

### Stage 1

- Tab Kịch bản, Nhân vật, Outline.
- Preview kịch bản ở chế độ đọc.
- Tên file và digest nằm trong chi tiết kỹ thuật.
- CTA tiếp theo chỉ bật khi transition policy cho phép.

### Stage 2 và 3

- Gallery là nội dung chính.
- Có lựa chọn danh sách/grid nhưng không thêm bộ lọc khi chỉ có 10 ảnh ZONE.
- Mỗi ảnh hiển thị basename, trạng thái và hành động xem lớn.
- Stage 3 cho phép đối chiếu ảnh ngang/dọc theo cùng basename.

### Stage 4

- Danh sách clip/prompt theo thứ tự câu chuyện.
- Aspect ratio và coverage mode là metadata của run.
- Tải gói sản xuất video chỉ bật theo release readiness.

## 6. WF-04 — Validation center

### Cấu trúc

- Summary bar: số chặn phát hành, chưa đạt chất lượng và khuyến nghị.
- Bộ lọc nhỏ theo mức tác động và kết quả.
- Danh sách sắp theo mức ưu tiên trong `state-model.md`.
- Detail panel gồm: tác động, kết quả, giải thích, bằng chứng, artifact và hành động.

### Quy tắc

- `NOT_VERIFIED` không dùng icon đồng hồ hoặc nhãn “đang chờ”.
- `ASSESSED_PASS` luôn có nhãn “AI đánh giá”.
- Không có nút đánh dấu PASS thủ công.
- Khi artifact kế thừa gây lỗi, CTA dẫn về stage sở hữu.

## 7. WF-05 — Package inspector

### Trước khi chọn tệp

- Drop zone có label rõ và nút chọn file.
- Chỉ chấp nhận `.zip`; validation phía backend vẫn là nguồn sự thật.
- Giải thích ngắn rằng thao tác không thay đổi package.

### Sau khi kiểm tra

- Header: stage, profile, purpose và integrity.
- Tab Tổng quan, Tệp, Kiểm định và Kỹ thuật.
- Cây tệp hiển thị artifact theo nhóm, không mô phỏng folder nếu package không có.
- Nếu integrity lỗi, không hiển thị CTA chạy stage tiếp.

## 8. Trạng thái bắt buộc cho prototype

| Màn hình | Default | Loading | Empty | Error/blocked |
|---|---:|---:|---:|---:|
| Dashboard | Có | Có | Có | Có |
| Wizard | Có | Không | Không | Validation field |
| Workspace | Có | Có | Không | Có |
| Validation | Có | Có | Có | Có |
| Package inspector | Có | Có | Có | Có |

## 9. Kịch bản usability test

### T1 — Tạo truyện thiếu nhi

“Bạn có ý tưởng ‘Một lời hứa sau mưa’, muốn truyện tiếng Việt dài 12 phút. Hãy bắt đầu tạo nội dung.”

Quan sát: người dùng có hiểu profile, tìm được khoảng thời lượng và nhận ra bước xác nhận không.

### T2 — Xác định lý do chưa phát hành được

“Một lời hứa sau mưa đã tạo xong hình ngang nhưng chưa thể đi tiếp. Hãy tìm nguyên nhân quan trọng nhất.”

Quan sát: người dùng có phân biệt pipeline completed với publish-ready và hiểu `NOT_VERIFIED` không.

### T3 — Sửa artifact

“Ảnh nhân vật cần sửa khi bạn đang ở Stage 2. Hãy tìm cách xử lý.”

Kỳ vọng: người dùng nhận ra ảnh nhân vật thuộc Stage 1 và quay về stage sở hữu.

### T4 — Kiểm tra package ngoài hệ thống

“Bạn nhận một file `story.zip`. Hãy kiểm tra xem có thể dùng làm đầu vào cho Stage 3 hay không.”

Quan sát: người dùng tìm được Package inspector, hiểu integrity và source stage.

### T5 — Hiểu kết quả AI đánh giá

“Kiểm tra hình ảnh hiển thị ‘AI đánh giá — đạt’. Điều này có giống kiểm tra integrity đã đạt không?”

Kỳ vọng: người dùng trả lời không và tìm được detector trong chi tiết.

## 10. Tiêu chí chuyển sang Tuần 3

- 5/5 người thử nghiệm hoàn thành T1.
- Ít nhất 4/5 người hoàn thành T2 và T4 không cần gợi ý.
- 5/5 người không cố sửa artifact kế thừa trực tiếp trong T3.
- Ít nhất 4/5 người phân biệt được `PASS` và `ASSESSED_PASS`.
- Không còn vấn đề P0 về điều hướng hoặc thuật ngữ.
- Các thay đổi sau test được ghi thành decision log trước visual design.

