# Điều kiện hoàn thành và trạng thái hiện tại

## Kết luận

Phần triển khai kỹ thuật của vòng cải tiến đã hoàn thành. Vòng validation UX chưa hoàn thành vì chưa có năm phiên với người tham gia và chưa có phiên NVDA thật. Không dùng kiểm thử tự động hoặc phiên mô phỏng để thay thế hai điều kiện này.

Trạng thái này được kiểm tra bằng `tools/evaluate_ux_validation.py`. Công cụ chỉ tính các
dòng có `session_source=HUMAN` và tự động loại phiên pilot, phiên mô phỏng hoặc phiên
không hợp lệ.

## Điều kiện hoàn thành

| Nhóm | Điều kiện | Trạng thái |
|---|---|---|
| Chức năng | Blocker đứng trước kiểm tra đã đạt; không thể chạy stage tiếp theo khi còn blocker | Đạt |
| Ngôn ngữ | 100% gate trong dataset nghiên cứu có tên thân thiện; ID kỹ thuật chỉ xuất hiện trong phần chi tiết | Đạt |
| Điều hướng | Bộ lọc, tab và vị trí cuộn được giữ trong cùng phiên trình duyệt | Đạt |
| Accessibility kỹ thuật | Thành phần có accessible name; nhóm tab hỗ trợ Left, Right, Home và End; không có bẫy focus đã biết | Đạt qua accessibility tree |
| Responsive | Không tràn ngang hoặc che CTA tại 390, 768 và 1280 px | Đạt |
| Hồi quy | Toàn bộ kiểm thử tự động vượt qua | Đạt |
| Telemetry | Ghi được lượt xem kiểm định, mở blocker, đổi bộ lọc, chọn CTA và quay lại workspace | Đạt |
| Quyền riêng tư | Không ghi nội dung truyện, tiêu đề, run ID, gate ID, session ID hoặc dữ liệu nhận dạng | Đạt qua schema allowlist |
| Validation hành vi | Ít nhất 4/5 người tìm đúng blocker và hành động tiếp theo trong 30 giây, không cần gợi ý | Chưa thực hiện |
| Mẫu nghiên cứu | Có đủ 5 phiên hợp lệ, gồm ít nhất hai người vận hành và hai người biên tập/QA | Chưa thực hiện |
| NVDA | Hoàn thành checklist Browse/Focus, không có phần tử không tên hoặc bẫy focus nghiêm trọng | Chưa thực hiện |
| Lỗi nghiêm trọng | Không có lỗi làm người dùng không thể hoàn thành luồng blocker | Chờ xác nhận từ phiên thật |

## Telemetry cục bộ

Sự kiện được lưu trong `.ux-events.ndjson` bên trong runtime workspace. Endpoint chỉ chấp nhận năm loại sự kiện định trước và các giá trị enum đã khóa. Payload có trường ngoài schema sẽ bị từ chối.

Endpoint tổng hợp:

```text
GET /api/ux-events/summary
```

Kết quả tổng hợp gồm số sự kiện theo loại, số mẫu thời gian mở blocker và trung vị thời gian mở blocker. Endpoint không trả lại nội dung sự kiện thô.

## Quy tắc ra quyết định

Chỉ đánh dấu vòng validation là hoàn thành khi tất cả điều kiện trong bảng đều đạt. Nếu một người gặp lỗi nghiêm trọng, sửa lỗi và chạy lại ít nhất phiên đó. Nếu dưới 4/5 người đạt mục tiêu 30 giây, tiếp tục cải tiến hierarchy rồi chạy một vòng validation mới.

## Việc còn lại cần con người thực hiện

1. Tuyển và chạy năm phiên validation theo mẫu vai trò.
2. Chạy checklist NVDA thật trên Windows.
3. Điền kết quả vào sổ phiên và đối chiếu telemetry cục bộ.
4. Ghi nhận lỗi nghiêm trọng, mức hỗ trợ và thời gian tìm blocker cho từng phiên.

## Điều kiện chuyển trạng thái sang hoàn thành

Cổng tự động chỉ trả về `COMPLETE` khi đồng thời có đủ năm phiên người thật hợp lệ,
ít nhất hai người vận hành, ít nhất hai người biên tập/QA, tối thiểu 80% và không dưới
bốn người tìm blocker trong 30 giây mà không cần gợi ý, không có lỗi nghiêm trọng và
một phiên NVDA người thật đạt đầy đủ checklist.
