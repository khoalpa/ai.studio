# User flows

## Quy ước

- `[Màn hình]`: điểm người dùng nhìn thấy.
- `(Hành động)`: thao tác của người dùng.
- `{Điều kiện}`: nhánh quyết định.
- `!`: trạng thái cần chú ý hoặc bị chặn.

## F1 — Tạo truyện đơn

```text
[Tổng quan]
  → (Tạo truyện mới)
  → [Chọn loại nội dung]
  → (Truyện thiếu nhi | Truyện người lớn)
  → [Nhập brief, ngôn ngữ, thời lượng]
  → {Thời lượng hợp lệ?}
      Không → ! Hiển thị khoảng hợp lệ → quay lại cấu hình
      Có
  → (Xác nhận thời lượng)
  → [Kiểm tra cấu hình]
  → (Tạo nội dung)
  → [Đang xử lý Stage 1]
  → {Kết quả?}
      Lỗi runtime → ! Xem lỗi / thử lại bằng run mới
      Hoàn thành
  → [Nội dung, nhân vật và kiểm định]
  → {Có blocker?}
      Có → mở lỗi → repair hoặc tạo lại
      Không → (Chạy Hình ảnh ngang)
```

Điểm UX bắt buộc:

- Hiển thị thời lượng được đề xuất trước khi yêu cầu xác nhận.
- Không tạo run nếu thiếu xác nhận thời lượng.
- Sau khi gửi, chống submit lặp và hiển thị run ID trong chi tiết.
- Hoàn thành pipeline không đồng nghĩa với đủ điều kiện đi tiếp; phải xét validation.

## F2 — Chạy Stage 2–4

```text
[Stage hiện tại đã đủ điều kiện]
  → (Chạy stage tiếp theo)
  → [Tóm tắt input package và cấu hình]
  → (Xác nhận chạy)
  → [Tiến trình]
  → {Package đầu vào hợp lệ?}
      Không → ! Package lỗi → mở Package Inspector
      Có
  → {Pipeline hoàn thành?}
      Không → ! Lỗi runtime → xem log / thử lại
      Có
  → [Preview output + validation]
  → {Blocker?}
      Có → repair/tạo lại
      Không → chạy stage tiếp hoặc tải package cuối
```

Stage 2 mặc định là `ZONE`; không hiển thị `SCENE` như một lựa chọn khả dụng. Stage 4 phải yêu cầu xác nhận riêng khi kế hoạch được backend xác định là lớn.

## F3 — Bắt đầu series trinh thám

```text
[Tạo truyện mới]
  → (Series trinh thám)
  → [Chọn chế độ tập]
  → (Bắt đầu series)
  → [Tên series + số tập dự kiến + brief + thời lượng]
  → [Kiểm tra cấu hình]
  → (Tạo tập đầu)
  → [Stage 1]
  → {Continuity gate đạt?}
      Không → ! Chặn đi tiếp, hiển thị vấn đề anchor
      Có → [Chi tiết series và tập đầu]
```

Điều kiện phát hành tính năng: chỉ bật sau khi trạng thái `SERIAL_DETECTIVE` giữa execution matrix và runtime đã được thống nhất.

## F4 — Tiếp tục hoặc kết thúc series

```text
[Chi tiết series]
  → (Tạo tập tiếp theo | Kết thúc series)
  → [Hiển thị revision và tập gần nhất]
  → [Brief + thời lượng]
  → (Xác nhận)
  → [Stage 1]
  → {Anchor hợp lệ và tăng đúng một revision?}
      Không → ! Không cập nhật series, giữ anchor trước đó
      Có → [Thêm tập vào series]
```

UI không yêu cầu người dùng chọn file anchor thủ công khi series đã được quản lý trong hệ thống. Việc cập nhật series chỉ diễn ra sau transaction thành công.

## F5 — Kiểm tra package có sẵn

```text
[Kiểm tra gói]
  → (Chọn hoặc kéo-thả story.zip)
  → {Định dạng ZIP đọc được?}
      Không → ! Không thể mở gói
      Có
  → {Integrity hợp lệ?}
      Không → ! Hiển thị lỗi, không đề xuất chạy stage tiếp
      Có → [Tổng quan package]
          ├── Cấu trúc tệp
          ├── Validation
          ├── Lineage
          └── Manifest
```

Không giải nén đường dẫn không an toàn. UI chỉ hiển thị kết quả từ verifier của backend.

## F6 — Repair output

```text
[Stage có lỗi hoặc cần chỉnh]
  → (Sửa đầu ra)
  → [Danh sách artifact]
  → {Artifact thuộc stage hiện tại?}
      Không → ! Chỉ đọc, dẫn về stage sở hữu
      Có → (Chỉnh sửa hoặc tạo lại artifact)
  → [Tóm tắt thay đổi]
  → (Tạo package sửa chữa)
  → {Có thay đổi thực tế?}
      Không → ! Không tạo package mới
      Có
  → {Có xóa canonical artifact hoặc sửa artifact kế thừa?}
      Có → ! Từ chối repair
      Không → [Package REPAIR mới + validation]
```

Repair không ghi đè package nguồn. UI phải giữ quan hệ parent/child và cho phép quay lại xem package trước.

## F7 — Xử lý validation

```text
[Kiểm tra]
  → [Publish blocker chưa đạt ở đầu danh sách]
  → (Mở một kiểm tra)
  → [Tác động + nguyên nhân + bằng chứng + artifact liên quan]
  → {Có hành động trong UI?}
      Có → (Mở artifact / Repair / Tạo lại)
      Không → (Xem hướng dẫn kỹ thuật)
  → [Chạy lại kiểm tra thông qua package mới]
```

Không cung cấp nút “Đánh dấu đạt” thủ công cho gate deterministic hoặc tool-measured.

