# Mốc F — Job engine và trải nghiệm vận hành

## Job engine

Web workflow dùng job engine bền vững trong process, với snapshot JSON atomic tại `<runtime-root>/.jobs`. Contract trạng thái gồm `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED` và `CANCELLED`; mỗi record có timestamp, operation, run ID, attempt, progress, resource class, error code và quan hệ `retry_of`.

- Submit có `idempotency_key`, scoped theo operation, để request lặp không tạo thêm job.
- CPU job dùng worker pool; Stage 2/3 local dùng lane `GPU` có semaphore một slot để tránh hai Diffusers job tranh VRAM.
- Hủy là cooperative: queued job được hủy trước khi chạy; running job dừng ở điểm kiểm tra an toàn trước/sau pipeline.
- Retry tạo job mới, tăng `attempt`, giữ job nguồn bất biến và ghi `retry_of`.
- Snapshot của job chưa kết thúc được đánh dấu `FAILED/SERVER_RESTARTED` khi server khởi động lại. Engine không tuyên bố tiếp tục một process đã mất.
- Payload và trạng thái trả về là bản sao; client không thể sửa state nội bộ.

## Trải nghiệm vận hành

Dashboard có trang **Tác vụ** để xem hàng đợi, resource class, progress, trạng thái, run liên quan và thao tác hủy/thử lại. Modal workflow hiển thị phần trăm, phase message và tiếp tục polling từ backend, nên refresh không submit lại công việc.

Stage submit từ UI luôn sinh idempotency key. API hỗ trợ:

| Method | Endpoint | Mục đích |
|---|---|---|
| `GET` | `/api/jobs` | Danh sách job mới nhất |
| `GET` | `/api/jobs/{job_id}` | Trạng thái và progress |
| `POST` | `/api/jobs/{job_id}/cancel` | Yêu cầu hủy cooperative |
| `POST` | `/api/jobs/{job_id}/retry` | Tạo attempt mới |

Có thể xem snapshot khi không mở dashboard:

```powershell
$env:PYTHONPATH = "src"
py -3.10 -m ai_story list-jobs --root .runtime --limit 50
```

## Ranh giới vận hành

Job engine là local single-process, không phải distributed queue. Restart bảo toàn lịch sử nhưng không phục hồi stack Python hoặc tiến trình model đang chạy. Hủy trong lúc một lời gọi thư viện native đang chạy chỉ có hiệu lực ở điểm dừng kế tiếp; timeout của provider vẫn là hàng rào cuối. Việc bind web ra ngoài localhost vẫn cần authentication và reverse proxy riêng.
