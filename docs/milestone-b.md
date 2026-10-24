# Mốc B — Runtime và provider registry

## Đã triển khai

- Contract `ModelRuntime` cho health, capability discovery, text, structured JSON, image, vision và unload.
- `ProviderRuntimeRegistry` ánh xạ `role → adapter → runtime` từ `spec/providers.json`.
- Client local `llama.cpp` qua OpenAI-compatible HTTP endpoint trên loopback.
- JSON-schema response format và parse-back validation cho subset schema canonical.
- Timeout, retry có backoff, cooperative cancellation và circuit breaker theo provider role.
- Khóa accelerator dùng chung; runtime trước được unload khi chuyển runtime để giới hạn VRAM.
- Fallback bị tắt rõ ràng. Runtime lỗi không được âm thầm thay bằng deterministic provider.
- Telemetry chỉ ghi role, runtime, operation, attempt, status và duration; không ghi prompt, response, header, request ID hoặc model path.
- Capability/health được công bố qua CLI, environment doctor và `/api/config`.
- Runtime chưa cài được biểu diễn bằng `NOT_INSTALLED`, không bị trình bày như capability khả dụng.

## CLI

```powershell
$env:PYTHONPATH = "src"
py -3.10 -m ai_story provider-status
py -3.10 -m ai_story provider-status --mode local
py -3.10 -m ai_story provider-status --mode local --no-probe
py -3.10 -m ai_story doctor
```

## llama.cpp

Endpoint mặc định là `http://127.0.0.1:8080`. Vì đây là kiến trúc local-first, client chỉ chấp nhận HTTP trên loopback. Thay endpoint, timeout và policy trong `spec/providers.json` hoặc một file riêng được chọn bằng `AI_STORY_PROVIDER_CONFIG`.

Runtime sử dụng:

- `GET /health` cho health probe.
- `POST /v1/chat/completions` cho text và structured JSON.
- `response_format.type=json_schema` khi request có schema.

## Chính sách lỗi

- Chỉ timeout và runtime-unavailable được retry.
- Lỗi capability, cancellation và configuration không được retry.
- Circuit breaker độc lập theo role.
- Cancellation được kiểm tra trước request, giữa các lần retry và sau response. Transport stdlib không cưỡng bức đóng một request đang xử lý ở server; timeout vẫn là giới hạn cuối cùng.

## Ranh giới

- Prompt orchestration chưa thuộc bản thân runtime layer; implementation sử dụng nó đã được bổ sung ở Mốc C.
- Diffusers được đăng ký dưới dạng runtime dành trước và báo `NOT_INSTALLED` cho đến mốc image provider.
- Telemetry peak VRAM thực tế chưa được thu thập.
- Runtime registry đang sống trong process; persistent model scheduler thuộc mốc job-engine.
