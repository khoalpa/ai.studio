# AI Story web MVP

## Khởi chạy

```powershell
$env:PYTHONPATH = "src"
python -m ai_story serve --root .runtime --host 127.0.0.1 --port 8765
```

Mở `http://127.0.0.1:8765` trong trình duyệt. Server mặc định chỉ bind localhost.

## Phạm vi đã triển khai

- Dashboard và danh sách lần chạy.
- Wizard tạo Stage 1 cho ba profile.
- Job chạy nền với trạng thái `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`.
- Job history bền vững, idempotency, progress, cooperative cancel/retry và GPU lane tuần tự.
- Workspace và preview artifact theo stage.
- Chạy tuần tự Stage 2, Stage 3 và Stage 4 từ package của run trước.
- Validation center cho gate record có trong package.
- Tải checkpoint hoặc release package.
- Package inspector bằng kéo-thả hoặc chọn file ZIP.
- Responsive navigation và semantic state labels.

## Giới hạn MVP

- Frontend và API chạy trong cùng một local process; chưa có authentication.
- Chỉ nên bind `127.0.0.1` trừ khi đã đặt reverse proxy và kiểm soát truy cập.
- Job history được giữ trên đĩa; job đang chạy khi server restart được đánh dấu `FAILED/SERVER_RESTARTED`, không tự resume.
- `REPAIR` đã có contract runtime nhưng chưa có editor chuyên dụng trong web MVP.
- Series continuation/finalization cần chọn anchor; wizard hiện chỉ bật `START_SERIES`.
- Validation Stage 2–4 chỉ hiển thị record có trong artifact hiện tại; chưa có normalized validation ledger chung.
- Provider mặc định vẫn là deterministic development provider.

## API nội bộ

| Method | Endpoint | Mục đích |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/config` | Profile, duration và image mode |
| GET | `/api/runs` | Danh sách run đã tổng hợp trạng thái |
| GET | `/api/runs/{run_id}` | Chi tiết, artifact, validation và event |
| GET | `/api/runs/{run_id}/artifact?path=...` | Preview artifact an toàn |
| GET | `/api/runs/{run_id}/package` | Tải `story.zip` |
| POST | `/api/jobs/stage1` | Khởi chạy Stage 1 |
| POST | `/api/jobs/stage2` | Khởi chạy Stage 2 từ `input_run_id` |
| POST | `/api/jobs/stage3` | Khởi chạy Stage 3 từ `input_run_id` |
| POST | `/api/jobs/stage4` | Khởi chạy Stage 4 từ `input_run_id` |
| GET | `/api/jobs` | Danh sách job và progress |
| GET | `/api/jobs/{job_id}` | Theo dõi job |
| POST | `/api/jobs/{job_id}/cancel` | Yêu cầu hủy cooperative |
| POST | `/api/jobs/{job_id}/retry` | Tạo attempt mới từ job lỗi/hủy |
| POST | `/api/packages/inspect` | Kiểm tra raw ZIP body, tối đa 100 MB |

API là contract nội bộ của MVP, chưa cam kết ổn định cho client bên ngoài.

## An toàn dữ liệu

- Run ID và artifact path được chuẩn hóa trước khi truy cập filesystem.
- Package upload được verifier kiểm tra CRC, traversal, symlink, kích thước, manifest và digest.
- Package được upload cho inspector bị xóa sau khi kiểm tra.
- Repair hoặc chạy stage mới không ghi đè package nguồn.
- Unknown `/api/*` trả về lỗi thay vì SPA fallback.

## Kiểm thử

```powershell
$env:PYTHONPATH = "src"
python tools/lint_spec.py
python -m unittest discover -s tests -v
```

`tests/test_web.py` bao phủ config, Stage 1 job, run detail, path traversal, health check và static app. `tests/test_job_engine.py` bao phủ persistence, idempotency, progress, cancel, retry và restart recovery.
