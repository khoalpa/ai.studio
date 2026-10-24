# AI Story Package Specification

AI Story là đặc tả chuẩn hóa và nền tảng workflow để tạo gói truyện từ prompt. Bản hiện tại đã hoàn tất nghiệm thu local MVP qua bốn giai đoạn cho cả ba profile canonical.

Provider mặc định là `deterministic`. Hai chế độ `hybrid` và `local` dùng llama.cpp cho tác vụ sáng tác, vì vậy phải cấu hình model rõ ràng trước khi chạy.

- Trạng thái đóng MVP và bằng chứng nghiệm thu: [`docs/mvp-closure.md`](docs/mvp-closure.md)
- Nguồn đặc tả: `ChatGPT_prompt_v3.16.13.txt`
- Phiên bản: `3.16.13`
- SHA-256: `4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27`

## Thành phần chính

| Đường dẫn | Vai trò |
|---|---|
| `spec/registry.json` | Enum, artifact, file set và quy tắc chuyển stage canonical của MVP |
| `spec/execution_matrix.json` | Ma trận profile × stage × operation |
| `spec/gates.json` | Danh mục gate, owner, detector và mức ảnh hưởng đến phát hành |
| `spec/mvp_contract.json` | Phạm vi đóng băng cho MVP và các hạng mục deferred |
| `spec/providers.json` | Registry cho `deterministic`, `hybrid`, `text_local` và `local` |
| `schemas/*.schema.json` | Schema của các tài liệu chuẩn hóa |
| `fixtures/` | Fixture hợp lệ và không hợp lệ để kiểm tra contract |
| `tools/lint_spec.py` | Linter chỉ dùng Python standard library |
| `src/ai_story/` | State machine, workspace, manifest, archive và CLI |
| `docs/` | Quyết định chuẩn hóa và traceability về prompt nguồn |
| `docs/ux/` | Discovery, kiến trúc thông tin, user flow và yêu cầu UI/UX MVP |

Tài liệu triển khai theo từng mốc:

- [`docs/milestone-a.md`](docs/milestone-a.md): provider baseline, environment doctor và manifest provenance.
- [`docs/image-provider-abstraction.md`](docs/image-provider-abstraction.md): model family, capability và runtime isolation.
- [`docs/local-generator-upgrade.md`](docs/local-generator-upgrade.md): best-of-N, scheduler và benchmark SD 3.5.
- [`docs/milestone-b.md`](docs/milestone-b.md): runtime contract, provider registry và chính sách vận hành model local.
- [`docs/milestone-c.md`](docs/milestone-c.md): orchestration Stage 1 bằng LLM local và semantic safety.
- [`docs/milestone-d.md`](docs/milestone-d.md): Diffusers, IP-Adapter và QA hình ảnh Stage 1–3.
- [`docs/milestone-e.md`](docs/milestone-e.md): shot design, continuity, phụ đề, TTS local tùy chọn và gói production Stage 4.
- [`docs/milestone-f.md`](docs/milestone-f.md): job engine bền vững, progress, cancel/retry, idempotency và GPU lane.
- [`docs/milestone-g.md`](docs/milestone-g.md): release evaluation, audit binding, provenance và distribution bundle.

## Yêu cầu và cài đặt

Dự án hỗ trợ Python 3.10–3.12. `Pillow` là dependency lõi vì workflow deterministic dùng thư viện này để tạo ảnh và typography trong Stage 1–3. Extra `local-image` bổ sung Diffusers và Transformers cho provider ảnh local.

```powershell
uv sync --dev
uv run python tools/lint_spec.py
uv run pytest -q
uv run ruff check src tests tools
```

### Provider ảnh local trên Windows

Script thiết lập tự phát hiện NVIDIA GPU, cài đúng PyTorch CUDA build và xác minh runtime:

```powershell
.\tools\setup_local_image.ps1
```

Mặc định, script dùng CUDA 13.0 (`cu130`) và chạy `uv sync --locked --extra cuda`. Extra `cuda`, PyTorch CUDA index, phiên bản và wheel source đều được khai báo trong `pyproject.toml` và khóa trong `uv.lock`; không có bước cài PyTorch riêng ngoài lock.

Nếu không phát hiện NVIDIA GPU, script đồng bộ extra CPU `local-image`. Hai extra được đánh dấu xung đột để tránh trộn CPU và CUDA trong cùng một môi trường.

Kiểm tra lock mà không thay đổi môi trường:

```powershell
uv lock --check
uv sync --locked --extra cuda --dry-run
```

## Kiểm tra chất lượng và CI

GitHub Actions chạy lint và toàn bộ test trên Python 3.10/3.12, áp ngưỡng branch coverage 70%, rồi chạy workflow Stage 1–4 deterministic hai lần để phát hiện semantic drift.

```powershell
uv run ruff check .
uv run pytest --cov=ai_story --cov-report=term-missing --cov-report=xml --cov-fail-under=70
uv run python tools/deterministic_smoke_gate.py --root artifacts/deterministic-smoke
```

Mọi dependency trực tiếp đều có upper bound theo major version; riêng cặp Torch/Torchvision được pin chính xác. CI chạy `uv lock --check`, do đó việc nâng major version phải là thay đổi chủ động và có kiểm thử.

Linter kiểm tra schema cơ bản, tính duy nhất của ID, tham chiếu gate, độ phủ đủ 24 tổ hợp profile × stage × operation của MVP, file set, ownership và chuỗi chuyển stage.

## Sử dụng CLI

```powershell
$env:PYTHONPATH = "src"
```

### Chẩn đoán, provider và model

```powershell
py -3.10 -m ai_story doctor
py -3.10 -m ai_story smoke-workflow --root .runtime-smoke
py -3.10 -m ai_story provider-status --mode local --no-probe
py -3.10 -m ai_story prepare-image-models
py -3.10 -m ai_story prepare-image-models --mode local_sd35
py -3.10 -m ai_story models --root .runtime list
py -3.10 -m ai_story models --root .runtime register --id story-q4 --name "Story Q4" --kind text --path D:\project\ai.studio\models\story-q4.gguf --quantization Q4_K_M
py -3.10 -m ai_story models --root .runtime activate story-q4 --role story
py -3.10 -m ai_story models --root .runtime remove story-q4
py -3.10 -m ai_story provider-status --mode local_sd35 --no-probe
py -3.10 -m ai_story models --root .runtime register --id sd35-medium --kind image --model-id D:\project\ai.studio\models\stable-diffusion-3.5-medium --model-profile sd35_medium
```

`prepare-image-models` kiểm tra hoặc tải diffusion model SD 3.5, semantic QA và learned latent upscaler. IP-Adapter và SDXL ControlNet không còn nằm trong tập model được hỗ trợ.

Khi learned upscaler đã bật nhưng không tải được hoặc inference thất bại, chế độ local không âm thầm chuyển sang Lanczos. Lanczos chỉ được dùng khi cấu hình `upscaler.enabled=false`.

### Workflow Stage 1–4

```powershell
py -3.10 -m ai_story init-run --root .runtime --profile YOUTH_SAFE
py -3.10 -m ai_story verify-package path\to\story.zip
py -3.10 -m ai_story inspect-package path\to\story.zip
py -3.10 -m ai_story suggest-duration --profile YOUTH_SAFE
py -3.10 -m ai_story generate-stage1 --root .runtime --profile YOUTH_SAFE --brief "Một lời hứa sau mưa" --confirm-duration
py -3.10 -m ai_story generate-stage1 --root .runtime --profile YOUTH_SAFE --brief "Một lời hứa sau mưa" --confirm-duration --provider-mode hybrid
py -3.10 -m ai_story generate-stage2 --root .runtime --input-package path\to\stage1\story.zip --mode ZONE
py -3.10 -m ai_story generate-stage3 --root .runtime --input-package path\to\stage2\story.zip
py -3.10 -m ai_story generate-stage4 --root .runtime --input-package path\to\stage3\story.zip --confirm-large-plan --approve-visual-review
py -3.10 -m ai_story generate-stage4 --root .runtime --input-package path\to\stage3\story.zip --confirm-large-plan --render-tts --piper-voice-model path\to\vi_voice.onnx
py -3.10 -m ai_story generate-stage1 --root .runtime --profile SERIAL_DETECTIVE --episode-mode START_SERIES --series-title "Hồ Sơ Mưa Đêm" --brief "Một căn phòng khóa kín" --minutes 42 --confirm-duration
py -3.10 -m ai_story list-runs --root .runtime
py -3.10 -m ai_story list-jobs --root .runtime
```

Chọn provider bằng biến `AI_STORY_PROVIDER_MODE=deterministic|hybrid|text_local|local` hoặc đối số `--provider-mode` cho Stage 1–3:

| Chế độ | Story | Safety | Image |
|---|---|---|---|
| `deterministic` | Deterministic | Deterministic | Deterministic |
| `hybrid` | LLM local | Deterministic | Deterministic |
| `text_local` | LLM local | LLM local | Deterministic |
| `local` | LLM local | Local | Diffusers SD 3.5 |

Hệ thống không tự hạ cấp provider. Stage 2 local dựng ảnh bằng Stable Diffusion 3.5 Medium theo shot spec; các capability SDXL như Depth ControlNet và IP-Adapter đã bị vô hiệu hóa.

Stage 3 luôn tạo visual-review sample cho cover và climax. Stage 4 tạo `production_plan.json`, SRT và WebVTT. Piper TTS là tùy chọn, chỉ chạy khi có cả `--render-tts` và voice model hợp lệ; pipeline không tự chọn voice hoặc chuyển sang dịch vụ khác.

### Benchmark nội dung và hình ảnh

```powershell
py -3.10 -m ai_story benchmark-plan
py -3.10 -m ai_story generate-benchmark-case --root .runtime-benchmark --case-id youth-promise-rain --provider-mode local
py -3.10 -m ai_story record-benchmark-case --case-id youth-promise-rain --package path\to\story.zip --output benchmark-records\youth-promise-rain.json
py -3.10 -m ai_story summarize-benchmark --records benchmark-records --output baselines\baseline-v4.json
py -3.10 -m ai_story run-benchmark-suite --output benchmark-runs\baseline-v4 --provider-mode deterministic
py -3.10 -m ai_story create-human-review-template --records benchmark-records --reviewer-id reviewer-a --output reviews\reviewer-a.json
py -3.10 -m ai_story evaluate-human-reviews --review-a reviewer-a.json --review-b reviewer-b.json --output baselines\human-agreement-v4.json
py -3.10 -m ai_story evaluate-benchmark --candidate candidate.json --baseline baseline.json

# Baseline chất lượng hình ảnh Stage 2–3: 8 golden case, có resume
py -3.10 -m ai_story image-baseline-plan
py -3.10 -m ai_story run-image-baseline-suite --source-packages stage1-packages --output artifacts\benchmarks\image-baseline-sdxl-v1 --provider-mode local --quality-preset balanced --resume
py -3.10 -m ai_story create-image-review-template --records artifacts\benchmarks\image-baseline-sdxl-v1\records --reviewer-id reviewer-a --output reviews\image-reviewer-a.json
py -3.10 -m ai_story evaluate-image-reviews --review-a reviews\image-reviewer-a.json --review-b reviews\image-reviewer-b.json --output reviews\image-agreement.json
py -3.10 -m ai_story evaluate-image-benchmark --baseline baselines\image-v1.json --candidate baselines\image-v2.json --human-review reviews\image-agreement.json --output baselines\image-promotion-v2.json
```

Mỗi stage hỗ trợ `--quality-preset fast|balanced|quality`. Provenance lưu preset, số lần gọi và retry, thời gian chạy, peak memory và cost basis. Chính sách benchmark không tự nâng model mặc định: candidate chỉ được đề xuất `PROMOTE` khi thỏa mọi điều kiện trong `spec/benchmark.json`.

Kế hoạch cải thiện chất lượng nằm tại [`docs/package-quality-improvement-plan.md`](docs/package-quality-improvement-plan.md). Quy trình khóa baseline thực tế, gồm corpus nội dung, hình ảnh và hai reviewer độc lập, nằm tại [`docs/real-baseline.md`](docs/real-baseline.md).

### Đánh giá và đóng gói bản phát hành

```powershell
py -3.10 -m ai_story evaluate-release path\to\stage4\story.zip --channel development --output release_report.json
py -3.10 -m ai_story evaluate-release path\to\stage4\story.zip --channel production --benchmark-evidence baselines\story-promotion.json --image-benchmark-evidence baselines\image-promotion-v2.json --framework-audit audits\framework.json --output release_report.json
py -3.10 -m ai_story build-release path\to\stage4\story.zip --channel development --output dist\ai-story-release.zip
py -3.10 -m ai_story verify-release dist\ai-story-release.zip
```

## Chính sách gate advisory

Gate nội dung, an toàn, biên tập và chất lượng hình ảnh không dừng workflow. Package vẫn chuyển qua Stage 1–4 theo transition canonical; kết quả không đạt được lưu trong `story_validation.json`, `quality_decision.json`, `package_quality_report.json` và release report.

`release_status=BLOCKED` hoặc `distribution_status=NOT_APPROVED` là cảnh báo phát hành, không phải lỗi thực thi. Lệnh chỉ thất bại khi đầu ra không thể tạo hoặc không còn đáng tin cậy về cấu trúc, chẳng hạn package hỏng, thiếu artifact, sai hash, provider lỗi hoặc không ghi được tệp.

Stage 4 không bắt buộc hoàn tất visual review. Nếu chưa duyệt, `visual_review.json` ghi quyết định `PENDING`; `--approve-visual-review` ghi nhận xác nhận rõ ràng của người vận hành.

Mỗi package có `validation_ledger.json`, báo cáo tích lũy xuyên suốt Stage 1–4. Mỗi record chứa stage, category, severity, status, resolution status, evidence, locator và release impact. Ledger được khóa bằng SHA-256; release report nhúng summary, digest và toàn bộ warning chưa xử lý để người vận hành không phải tổng hợp thủ công từ nhiều sidecar.

Dashboard tách trạng thái workflow khỏi khuyến nghị phát hành. Màn **Kiểm định** cho phép lọc ledger theo trạng thái xử lý, stage và severity. Trước khi chạy stage tiếp theo, hộp cấu hình hiển thị số cảnh báo kế thừa nhưng không buộc người vận hành override hoặc xác nhận gate. Package chưa đạt vẫn có thể tải xuống với nhãn “kèm cảnh báo”.

## Dashboard web

```powershell
py -3.10 -m ai_story serve --root .runtime --host 127.0.0.1 --port 8765
```

Trên Windows, chạy [`open_app.bat`](open_app.bat) để khởi động server và mở dashboard trong trình duyệt mặc định. Tài liệu dashboard MVP nằm tại [`docs/mvp-web.md`](docs/mvp-web.md).

Mục **Model local** quản lý catalog model riêng của workspace. Người vận hành có thể đăng ký file local hoặc Hugging Face Model ID, xem trạng thái, gán model theo vai trò và gỡ đăng ký. Lệnh `remove` chỉ xóa bản ghi catalog, không xóa weights trên đĩa. Runtime như llama.cpp vẫn phải được khởi động với weights tương ứng.

Wizard và nút chạy stage tiếp theo cho phép chọn model riêng cho từng giai đoạn. Lựa chọn chỉ áp dụng cho job hiện tại, không sửa cấu hình global, và được ghi vào provenance bằng `catalog_id`, model path hoặc ID, quantization và digest nếu có. Stage 4 cũng cho phép chọn voice ONNX và bật Piper ngay trong hộp cấu hình.

GPT Image Web Assist là tùy chọn thủ công, không dùng API. Xem [`docs/gpt-image-web-assist.md`](docs/gpt-image-web-assist.md).

## Nghiệm thu MVP

```powershell
uv run python tools/validate_mvp.py
```

Lệnh chạy lint, toàn bộ regression test, ba profile deterministic qua Stage 1–4, xác minh package và release bundle, sau đó ghi báo cáo JSON/Markdown kèm digest. Provider local thiếu model được ghi là `NOT_EXECUTED`: trạng thái này không làm dừng nghiệm thu và không đồng nghĩa với production-ready.
