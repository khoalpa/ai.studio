# Mốc C — Stage 1 bằng model local

## Đã triển khai

- `LocalStoryProvider` chạy qua provider/runtime registry của Mốc B.
- Orchestration nhiều bước: planner → tám zone writers → consistency critic → targeted rewrite.
- Mỗi lần gọi model dùng structured JSON và parse-back schema validation.
- Word budget được phân bổ theo nhịp truyện; validator deterministic vẫn quyết định duration gate.
- Repair loop chuyển findings có locator thành yêu cầu viết lại zone tương ứng. Findings toàn cục kích hoạt viết lại toàn script.
- `LocalSafetyProvider` chạy assessment độc lập, nhiệt độ 0 và chỉ trả `PASS`/`FAIL` cùng locator.
- Web runtime kiểm tra model theo từng vai trò trước mỗi request. Khi `story` và `safety`
  dùng hai GGUF khác nhau trên cùng cổng llama.cpp, supervisor dừng process do workspace
  quản lý và nạp model kế tiếp tuần tự; process ngoài workspace không bị tự ý dừng.
- Prompt phân tách instruction với `*_DATA` không tin cậy để giảm prompt injection từ brief và nội dung truyện.
- Model output được chuẩn hóa về enum, character ID, tuổi, identity traits, root order và dấu câu trước validation.
- Runtime telemetry được ghi vào event log mà không chứa prompt hoặc response.
- CLI và web job nhận `provider_mode`: `deterministic`, `local`, hoặc `hybrid`.
- Manifest ghi `stage1-local/1.0`, provider mode, runtime và model ID thực tế.

## Cấu hình mode

| Mode | Story | Safety | Character reference | Stage 2/3 |
|---|---|---|---|---|
| `deterministic` | Deterministic | Rule-based | Deterministic | Deterministic |
| `hybrid` | Local LLM | Rule-based | Deterministic | Deterministic |
| `text_local` | Local LLM | Local LLM | Deterministic | Deterministic |
| `local` | Local LLM | Local LLM | Local Diffusers từ Mốc D | Local Diffusers từ Mốc D |

`hybrid` là đường smoke-test được khuyến nghị nếu chỉ có llama.cpp. Mốc D đã hoàn thiện image runtime cho tuyến `local`.

## Khởi chạy

Yêu cầu một GGUF instruct model có structured-output tốt và context tối thiểu 32K. Dùng script:

```powershell
.\tools\start_llama_server.ps1 -ModelPath "D:\models\model.gguf"
```

Ở terminal khác:

```powershell
$env:PYTHONPATH = "src"
py -3.10 -m ai_story provider-status --mode hybrid
py -3.10 -m ai_story generate-stage1 `
  --root .runtime `
  --profile YOUTH_SAFE `
  --brief "Hai người bạn bảo vệ khu vườn sau cơn mưa" `
  --minutes 15 `
  --confirm-duration `
  --provider-mode hybrid
```

Để dùng semantic safety local, đổi thành `--provider-mode local`.

Với GPU 16 GB, cấu hình khuyến nghị là một story model Q4 và một safety model Q4 chuyên
dụng. Hai model không được giữ đồng thời trong VRAM; web service chuyển model tại ranh giới
vai trò. CLI vẫn giả định người vận hành tự quản lý llama.cpp đang phục vụ đúng model.

## Chính sách chất lượng

- Planner không được tự đặt channel, schema version hoặc profile metadata; runtime gán các trường canonical.
- Writer chỉ sở hữu text và thuộc tính trình bày của từng zone.
- Critic không trực tiếp sửa artifact; findings được chuyển thành lần viết lại có kiểm soát.
- Model assessment không xác minh hash, package integrity hoặc lineage.
- Sau tối đa hai repair round, blocker còn lại làm Stage 1 thất bại.

## Ranh giới

- Không tự tải model vì model/license và quantization cần được người vận hành lựa chọn.
- Ở thời điểm Mốc C, character reference còn deterministic; Mốc D đã thay bằng Diffusers trong mode `local`.
- Cancellation là cooperative; timeout giới hạn request đang chạy tại transport.
- Chất lượng thực tế phải được benchmark trên model GGUF được chọn trước khi gắn nhãn production.
