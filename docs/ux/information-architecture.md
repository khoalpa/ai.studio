# Kiến trúc thông tin

## 1. Mô hình đối tượng

```text
Series (tùy chọn)
└── Tập truyện
    └── Workflow
        ├── Stage 1 run → checkpoint package
        ├── Stage 2 run → checkpoint package
        ├── Stage 3 run → audio release package
        └── Stage 4 run → video production package
```

Trong MVP, runtime hiện quản lý `run` và package. Khái niệm “Tập truyện” và “Workflow” là lớp sản phẩm cần bổ sung để người dùng không phải tự ghép nhiều run độc lập.

## 2. Sitemap MVP

```text
Tổng quan
├── Lần chạy gần đây
├── Cần xử lý
└── Tạo truyện mới

Truyện
├── Tất cả truyện
├── Chi tiết truyện
│   ├── Tổng quan workflow
│   ├── Nội dung & nhân vật
│   ├── Hình ảnh ngang
│   ├── Hình ảnh dọc
│   ├── Prompt video
│   └── Lịch sử hoạt động
└── Tạo truyện mới

Series
├── Tất cả series
└── Chi tiết series
    ├── Tổng quan
    ├── Các tập
    └── Continuity

Kiểm tra gói
├── Tải gói lên
└── Kết quả kiểm tra
    ├── Tổng quan
    ├── Cấu trúc tệp
    ├── Kiểm định
    └── Chi tiết kỹ thuật

Cài đặt
├── AI provider (placeholder cho tích hợp sau)
├── Lưu trữ
└── Ngôn ngữ
```

## 3. Điều hướng trong một truyện

Header:

- Tên truyện hoặc “Chưa đặt tên”.
- Loại nội dung.
- Trạng thái tổng hợp.
- Menu tải checkpoint, mở thư mục và xem chi tiết kỹ thuật.

Stage stepper:

1. Nội dung & nhân vật.
2. Hình ảnh ngang.
3. Hình ảnh dọc.
4. Prompt video.

Mỗi stage có ba vùng thông tin:

- **Kết quả:** preview nội dung và asset.
- **Kiểm tra:** blocker, cảnh báo và bằng chứng.
- **Hoạt động:** tiến trình, event và lỗi kỹ thuật.

Trên desktop có thể dùng tab hoặc panel. Trên màn hình nhỏ, ba vùng được xếp dọc; không ẩn blocker trong drawer mặc định.

## 4. Progressive disclosure

### Mặc định hiển thị

- Tên truyện, profile, stage và thời gian cập nhật.
- Preview đầu ra.
- Số blocker và trạng thái tổng hợp.
- Hành động tiếp theo.

### Khi mở rộng

- Tên artifact canonical.
- Gate ID và detector class.
- Package purpose và operation.
- Digest, manifest, file size và lineage.
- Event payload và đường dẫn filesystem.

## 5. Tìm kiếm và lọc

Danh sách truyện/lần chạy:

- Tìm theo tên truyện, series hoặc run ID.
- Lọc theo loại nội dung, stage, trạng thái và khoảng ngày.
- Sắp xếp theo cập nhật gần nhất mặc định.

Danh sách validation:

- Lọc theo mức tác động, kết quả, stage và owner.
- Mặc định đưa publish blocker chưa đạt lên đầu.

## 6. Quyền và khả năng sửa

MVP có thể chưa cần đăng nhập/phân quyền, nhưng UI vẫn phải tuân thủ ownership của artifact:

| Ngữ cảnh | Artifact stage hiện tại | Artifact kế thừa |
|---|---|---|
| Xem | Có | Có |
| Tải | Có | Có |
| Repair | Có | Không |
| Xóa canonical artifact | Không | Không |

Khi người dùng muốn sửa artifact kế thừa, UI dẫn về stage sở hữu và cảnh báo rằng các stage phía sau cần chạy lại.

## 7. Empty states

- Chưa có truyện: giải thích workflow bốn stage và CTA “Tạo truyện đầu tiên”.
- Stage chưa chạy: hiển thị điều kiện đầu vào và CTA nếu đã đủ điều kiện.
- Không có lỗi: “Không có vấn đề cần xử lý” thay vì để vùng trống.
- Không tìm thấy kết quả: giữ bộ lọc hiện tại và cung cấp “Xóa bộ lọc”.
- Chưa có provider thật: giải thích giới hạn môi trường development, không giả vờ rằng production generation đã sẵn sàng.

