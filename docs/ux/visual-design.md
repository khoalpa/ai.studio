# Tuần 3 — Visual design

## 1. Hướng thiết kế

AI Story dùng ngôn ngữ thị giác “Editorial workspace”: tập trung vào nội dung, trạng thái kiểm định và tiến trình sản xuất. Giao diện tránh phong cách dashboard KPI dày đặc; mỗi bề mặt ưu tiên một quyết định hoặc hành động chính.

Ba đặc tính thương hiệu:

- **Điềm tĩnh:** nền trung tính, khoảng trắng rõ, chuyển động có mục đích.
- **Tin cậy:** trạng thái có nhãn và biểu tượng; không dùng màu làm tín hiệu duy nhất.
- **Sáng tạo có cấu trúc:** màu tím chàm cho hành động chính, màu xanh ngọc cho trạng thái đã xác minh.

## 2. Design tokens

Nguồn machine-readable: [`design-tokens.json`](./design-tokens.json).

### Màu sắc

| Vai trò | Light | Dark | Dùng cho |
|---|---|---|---|
| Canvas | `#F5F6F8` | `#101216` | Nền ứng dụng |
| Surface | `#FFFFFF` | `#181B21` | Card, sidebar, panel |
| Surface subtle | `#F0F1F4` | `#20242B` | Vùng phụ, selected neutral |
| Text | `#171A21` | `#F4F5F7` | Nội dung chính |
| Text secondary | `#68707D` | `#A7AFBB` | Metadata |
| Border | `#DDE0E6` | `#343A45` | Phân tách cấu trúc |
| Brand | `#5B4AE8` | `#8D82FF` | CTA và focus |
| Success | `#168A61` | `#52C99A` | Đã xác minh — đạt |
| Warning | `#B56A16` | `#F0AA55` | Cần xem lại |
| Danger | `#C54747` | `#FF8585` | Lỗi hoặc blocker |

Không dùng brand color để biểu thị trạng thái validation. `PASS`, warning và blocker có semantic token riêng.

### Typography

- UI font: `Inter`, fallback `Segoe UI`, `system-ui`, sans-serif.
- Nội dung truyện: `Source Serif 4`, fallback `Georgia`, serif.
- Base: 14 px / 1.5.
- Caption: 12 px / 1.4; không nhỏ hơn 11 px.
- Page title: 24 px / 1.25, weight 600 trong implementation; prototype dùng mức gần tương đương.
- Chỉ dùng ba mức nhấn: regular, medium và semibold.

### Spacing và hình dạng

- Base spacing: 4 px.
- Chuỗi ưu tiên: 4, 8, 12, 16, 24, 32, 48.
- Control height: 36 px desktop, tối thiểu 44 px trên coarse pointer.
- Radius: 8 px cho control, 12 px cho card, 16 px cho modal lớn.
- Shadow chỉ dùng cho overlay hoặc card nổi có tương tác; structural panel dùng border.

## 3. Application shell

- Sidebar 220 px ở desktop; thu gọn 76 px khi không đủ không gian.
- Content max-width 1.440 px nhưng không cố định chiều rộng trong màn hình nhỏ.
- Header cấp trang không sticky trong MVP.
- CTA chính nằm ở bên phải page title trên desktop và xuống dòng trên mobile.
- Navigation selected dùng surface subtle + text brand; không dùng một dải màu lớn.

## 4. Component inventory

### Buttons

- Primary: một hành động chính trong một vùng.
- Secondary: thao tác an toàn, không phải đường chính.
- Ghost: hành động ít quan trọng hoặc trong navigation.
- Destructive: chỉ dùng cho hành động không thể phục hồi; MVP gần như không cần.
- Disabled luôn đi kèm lý do gần control nếu điều kiện không hiển nhiên.

### Status badge

Badge gồm icon/dot + label; semantic color chỉ là tín hiệu bổ sung.

- Ready: “Sẵn sàng”.
- Running: “Đang xử lý”.
- Attention: “Cần xử lý”.
- Blocked: “Bị khóa”.
- Verified: “Đã xác minh — đạt”.
- AI assessed: “AI đánh giá — đạt/chưa đạt”.

### Cards và rows

- Card dùng cho nhóm nội dung có ranh giới rõ.
- Danh sách lặp dùng row + divider, không biến mỗi hàng thành card.
- Card không được lồng quá một cấp.

### Validation item

Thứ tự thông tin:

1. Tên kiểm tra dễ hiểu.
2. Kết quả và mức tác động.
3. Artifact liên quan.
4. Gate ID và detector trong chi tiết.
5. Hành động tiếp theo.

### Asset thumbnail

- Tỷ lệ thumbnail theo artifact thực tế: 16:9 hoặc 9:16.
- Basename luôn hiển thị.
- Trạng thái overlay dùng icon + label và không che nội dung chính.
- Skeleton giữ đúng aspect ratio để tránh layout shift.

## 5. Responsive behavior

### ≥ 1.024 px

- Sidebar đầy đủ.
- Workspace hai cột: output chính + validation rail.
- Gallery 3–4 cột tùy chiều rộng.

### 760–1.023 px

- Sidebar thu gọn chỉ còn icon và accessible label.
- Workspace xếp validation dưới output.
- Gallery 2–3 cột.

### < 760 px

- Navigation chuyển thành top rail có thể xuống dòng.
- Page action chiếm toàn chiều rộng khi cần.
- Stage navigation thành danh sách 2×2 hoặc cuộn ngang có label đầy đủ.
- Table chuyển thành list row; không ẩn trạng thái hoặc CTA chính.
- Gallery 1–2 cột.

## 6. Motion

- Transition 120–180 ms cho hover, selected và mở panel.
- Không animate lần tải đầu.
- Progress không chạy loop nếu không phản ánh tiến độ thật.
- Tôn trọng `prefers-reduced-motion`.
- Khi job đổi trạng thái, cập nhật `aria-live="polite"`; không đọc liên tục event log.

## 7. Accessibility review

- Text thường đạt tối thiểu 4.5:1; text lớn tối thiểu 3:1.
- Focus ring 2 px với offset 2 px, không bị clipping.
- Interactive target tối thiểu 44×44 px trên touch.
- Keyboard order theo thứ tự thị giác.
- Tabs, stage navigation và filter chips dùng semantic button/ARIA phù hợp.
- Hình ảnh có alt mô tả mục đích; hình trang trí dùng alt rỗng.
- Validation error liên kết trực tiếp đến trường hoặc artifact gây lỗi.

## 8. Màn hình high-fidelity

Prototype bao phủ:

- Dashboard với vùng “Cần xử lý” và danh sách truyện gần đây.
- Workspace Stage 2 với gallery ảnh ngang và validation rail.
- Validation center với summary, filter và detail panel.
- Wizard tạo truyện bốn bước.
- Package inspector trước và sau khi kiểm tra.

## 9. Quyết định cần kiểm tra bằng usability test

- Người dùng có hiểu “Cần xử lý” khác “Thất bại” không.
- Validation rail có đủ nổi bật mà không lấn át output chính không.
- CTA “Tạo nội dung” có rõ hơn “Hoàn tất” không.
- Stage navigation có truyền đạt đúng trạng thái bị khóa không.
- Nhãn “AI đánh giá” có ngăn người dùng hiểu nhầm thành deterministic verification không.

## 10. Definition of done

- Có token màu, type, spacing, radius và semantic status.
- Có component states: default, hover, focus, disabled, loading và error.
- Có prototype high-fidelity cho năm bề mặt MVP.
- Layout được kiểm tra ở desktop và breakpoint hẹp.
- Tương tác chính sử dụng keyboard-accessible native controls.
- Các điểm cần test được đưa vào checklist trước implementation.

