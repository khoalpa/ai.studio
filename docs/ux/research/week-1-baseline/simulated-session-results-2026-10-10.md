# Kết quả năm phiên mô phỏng Codex — 10/10/2026

## Phương pháp và giới hạn

Codex thao tác trên giao diện thật bằng năm góc nhìn vai trò. Dataset được reset theo nhiệm vụ, không theo từng persona vì mọi phiên dùng cùng build và cùng trạng thái cố định. Đây là cognitive walkthrough có cấu trúc, không phải năm người dùng độc lập.

Không báo cáo thời gian nhiệm vụ: tốc độ thao tác tự động không đại diện cho con người. Tỷ lệ dưới đây chỉ mô tả kết quả heuristic của năm góc nhìn mô phỏng.

## P01

Vai trò: operator nội dung, kỹ thuật thấp.

| Nhiệm vụ | Kết quả | Quan sát chính |
|---|---|---|
| T1 | ASSISTED | Hiểu brief và thời lượng; cần giải thích provider, deterministic và preset |
| T2 | FAILURE | Blocker nằm sau 23 bản ghi đạt và dùng ID kỹ thuật; bản ghi PASS mở mặc định |
| T3 | ASSISTED | CTA bật nhưng thông điệp vẫn nói các stage tiếp theo bị khóa |
| T4 | SUCCESS | Phân biệt được integrity đạt và khuyến nghị phát hành không đạt nhờ bố cục hai cột |

## P02

Vai trò: operator nội dung, kỹ thuật trung bình.

| Nhiệm vụ | Kết quả | Quan sát chính |
|---|---|---|
| T1 | SUCCESS | Hoàn thành wizard; bước cấu hình vẫn tạo do dự không cần thiết |
| T2 | ASSISTED | Nhận ra “Có lỗi chặn” nhưng phải mở Kiểm định và lọc trạng thái đang mở |
| T3 | ASSISTED | Tìm đúng CTA nhưng cần bỏ qua microcopy mâu thuẫn |
| T4 | SUCCESS | Kết luận đúng package dùng được làm đầu vào nhưng chưa production-ready |

## P03

Vai trò: operator nội dung thường xuyên.

| Nhiệm vụ | Kết quả | Quan sát chính |
|---|---|---|
| T1 | SUCCESS | Submit rõ ràng; modal tiến trình không cho đóng để theo dõi nền |
| T2 | FAILURE | Preview truyện quá dài đẩy blocker và hành động xuống sâu |
| T3 | SUCCESS | Stage stepper và CTA giúp xác định bước tiếp theo dù status copy sai |
| T4 | SUCCESS | Tải và kiểm tra package dễ tìm |

## P04

Vai trò: biên tập/QA.

| Nhiệm vụ | Kết quả | Quan sát chính |
|---|---|---|
| T1 | SUCCESS | Bản xác nhận đủ dữ liệu đầu vào nhưng thiếu diễn giải đầu ra dự kiến |
| T2 | ASSISTED | Summary đúng nhưng danh sách không ưu tiên blocker và detail mặc định là PASS |
| T3 | SUCCESS | Dialog Stage 2 cho biết package đã vượt kiểm tra; thuật ngữ provenance là chi tiết thừa |
| T4 | SUCCESS | Các lớp thực thi, toàn vẹn và chất lượng được tách đúng; nhãn vẫn trộn Việt–Anh |

## P05

Vai trò: QA kỹ thuật và accessibility.

| Nhiệm vụ | Kết quả | Quan sát chính |
|---|---|---|
| T1 | ASSISTED | CTA sidebar “Tạo truyện mới” không có accessible name trong accessibility tree |
| T2 | ASSISTED | Có heading và filter native, nhưng record dùng gate ID làm nhãn chính |
| T3 | SUCCESS | Nút có accessible name; dialog cấu hình chưa được expose nhất quán như `dialog` |
| T4 | SUCCESS | File input có đường nút rõ và kết quả đọc được theo thứ tự DOM |

## Tổng hợp nhiệm vụ

| Nhiệm vụ | SUCCESS | SUCCESS + ASSISTED | FAILURE |
|---|---:|---:|---:|
| T1 | 3/5 | 5/5 | 0/5 |
| T2 | 0/5 | 3/5 | 2/5 |
| T3 | 3/5 | 5/5 | 0/5 |
| T4 | 5/5 | 5/5 | 0/5 |

Không dùng các tỷ lệ này làm bằng chứng về task completion của người dùng thật.

## Top 5 pain point mô phỏng

### 1. Trạng thái stage tự mâu thuẫn

Ready workspace có CTA “Chạy Hình ảnh ngang” đang bật nhưng cùng vùng nội dung lại nói “Các stage sản xuất tiếp theo đã bị khóa”. Đây là lỗi quyết định, có thể khiến người dùng dừng dù workflow cho phép tiếp tục.

### 2. Validation không ưu tiên blocker

Validation Center hiển thị 23 record đạt trước blocker. Panel chi tiết tự mở record PASS đầu tiên, trong khi summary báo có một cảnh báo mở. Người dùng phải tự lọc hoặc cuộn để tìm lỗi cần xử lý.

### 3. Preview nội dung lấn át công việc vận hành

Toàn bộ truyện dài xuất hiện trước validation rail và CTA. Với output dài, người dùng phải đi qua lượng lớn nội dung trước khi đến quyết định “đi tiếp hay sửa”.

### 4. Cấu hình kỹ thuật xuất hiện quá sớm

Provider mode, deterministic, preset, model và provenance xuất hiện trong luồng của operator. Các lựa chọn này nên dùng mặc định dự án và chỉ mở khi người dùng chọn tùy chỉnh nâng cao.

### 5. Theo dõi job chưa hỗ trợ làm việc nền

Trong lúc Stage 1 chạy, modal chỉ có “Hủy tác vụ”; không có “Đóng và tiếp tục chạy”. Điều này khiến người dùng bị giữ tại modal hoặc phải hủy nếu muốn thoát.

## Phát hiện accessibility bổ sung

- CTA tạo truyện trong sidebar không có accessible name trong cây accessibility.
- Dialog cấu hình Stage 2 không được expose nhất quán như dialog có tên.
- Các trạng thái và tiêu đề chi tiết còn trộn tiếng Việt với ID/nhãn tiếng Anh.

Các mục accessibility cần được đưa vào P0 dù tần suất trong mô phỏng thấp, vì tác động có thể là không hoàn thành được nhiệm vụ.
