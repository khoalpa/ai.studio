# Mốc A — Chuẩn hóa baseline

## Đã triển khai

- Đồng bộ trạng thái `SERIAL_DETECTIVE` trong execution matrix với runtime Mốc 6.
- Chuyển tài liệu và launcher Windows sang Python 3.10 qua `py -3.10`.
- Thêm lệnh `ai-story doctor` để kiểm tra Python, provider config, local text runtime và GPU.
- Thêm registry `spec/providers.json` cho ba chế độ `deterministic`, `local` và `hybrid`.
- Pipeline lấy provider mặc định qua provider factory thay vì khởi tạo trực tiếp trong từng stage.
- Tại thời điểm Mốc A, `local` và `hybrid` fail-fast khi adapter chưa được cài. Mốc C đã bổ sung adapter text/safety local; nguyên tắc không tự hạ cấp provider vẫn giữ nguyên.
- Manifest schema 1.1 ghi provider mode, provider ID, runtime, model ID, model digest, quantization, generation parameters, prompt-template version, thời gian tạo và thông tin Python host.
- Spec linter kiểm tra coverage provider role và trạng thái serial.

## Ranh giới

- Chỉ adapter `deterministic` và `rule_based` được triển khai trong Mốc A.
- Model local, llama.cpp, diffusion và vision adapter thuộc mốc tích hợp tiếp theo.
- `peak_memory_bytes` được dành chỗ trong provenance nhưng hiện là `null`.
- Package manifest 1.0 không được runtime 1.1 nhận như package authoritative; migration vẫn deferred.

## Cấu hình

Chọn mode bằng biến môi trường:

```powershell
$env:AI_STORY_PROVIDER_MODE = "deterministic"
py -3.10 -m ai_story doctor
```

Có thể dùng file cấu hình khác bằng `AI_STORY_PROVIDER_CONFIG`. File phải khai báo đủ năm role canonical và mọi adapter được tham chiếu.
