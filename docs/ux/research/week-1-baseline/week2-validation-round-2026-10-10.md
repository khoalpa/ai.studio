# Vòng validation UI/UX — 10/10/2026

## Kết luận

Năm kịch bản kiểm tra nội bộ đều đạt. Đây là validation kỹ thuật và heuristic do Codex thực hiện trên dataset cố định, không thay thế phiên usability test với người tham gia hoặc phiên NVDA thật.

## Kết quả năm kịch bản

| Kịch bản | Tiêu chí đạt | Kết quả | Bằng chứng |
|---|---|---|---|
| Nhận diện blocker | Tên, trạng thái và hành động sửa được đọc rõ | Đạt | Accessibility tree đọc “Thiếu kết quả bắt buộc của brief”, “Đã xác minh — không đạt” và “Mở workspace để xử lý”. |
| Hiểu điều kiện chuyển stage | Không có CTA chạy tiếp khi còn blocker | Đạt | Stage 2 hiển thị “Bị chặn bởi kiểm định”; nút chạy Stage 2 không xuất hiện. |
| Hiểu danh sách kiểm định | Không còn ID kỹ thuật trong tên 24 gate của fixture | Đạt | 24/24 bản ghi có tên thân thiện; ID vẫn có trong phần “Chi tiết kỹ thuật”. |
| Điều hướng bằng bàn phím | Mũi tên chuyển tab và cập nhật panel tương ứng | Đạt | Arrow Right chuyển từ “Kết quả” sang “Tệp đầu ra”; trạng thái selected và tên panel được cập nhật. |
| Responsive | Không tràn ngang; tiêu đề và CTA nằm trong viewport | Đạt | Ma trận CDP 390 × 844, 768 × 1024 và 1280 × 900 đều đạt. 390 px dùng hai cột thống kê; hai mốc còn lại dùng bốn cột. |

## Kết quả đo responsive

| Chiều rộng | Tràn ngang | Tiêu đề | CTA quay lại | Điều hướng compact | Cột thống kê |
|---:|---|---|---|---|---:|
| 390 px | Không | Trong viewport | Trong viewport | Có | 2 |
| 768 px | Không | Trong viewport | Trong viewport | Không | 4 |
| 1280 px | Không | Trong viewport | Trong viewport | Không | 4 |

Có thể chạy lại bằng lệnh:

```powershell
node tools/audit_responsive.mjs http://127.0.0.1:9223 http://127.0.0.1:8770/#/validation 390,768,1280
```

## Checklist NVDA thủ công

Thực hiện với NVDA ở chế độ Browse và Focus. Ghi Pass/Fail cùng câu NVDA đọc được nếu khác kỳ vọng.

1. Mở “Trung tâm kiểm định”; xác nhận NVDA đọc heading cấp 1 và khuyến nghị phát hành.
2. Dùng phím `H` và `B` để đi qua heading và button; xác nhận blocker đầu tiên đứng trước các kiểm tra đã đạt.
3. Mở blocker; xác nhận tên thân thiện, trạng thái, vấn đề và CTA được đọc theo đúng thứ tự.
4. Mở “Chi tiết kỹ thuật”; xác nhận Gate ID chỉ được đọc sau khi người dùng chủ động mở.
5. Chọn “Mở workspace để xử lý”; xác nhận focus chuyển vào vùng nội dung chính.
6. Dùng Tab tới nhóm tab workspace; dùng Left/Right/Home/End và xác nhận tên panel thay đổi.
7. Quay lại Trung tâm kiểm định; xác nhận bộ lọc và vị trí trước đó được giữ trong cùng phiên.

## Ngưỡng quyết định

- Không có lỗi nghiêm trọng ngăn hoàn thành luồng blocker.
- 100% tên gate trong dataset nghiên cứu có nhãn thân thiện.
- 100% mốc viewport không tràn ngang hoặc che CTA.
- Phiên NVDA thật không có phần tử không tên và không có bẫy focus.
- Trong validation với người tham gia, ít nhất 4/5 người xác định đúng blocker và hành động tiếp theo trong 30 giây mà không cần gợi ý.

## Chưa hoàn thành

- Chưa có phiên NVDA thật; checklist trên đã sẵn sàng để người kiểm thử chạy.
- Chưa có 3–5 người tham gia cho vòng validation sau thay đổi; không suy diễn kết quả hành vi từ kiểm tra tự động.
