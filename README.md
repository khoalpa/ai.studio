# AI Story Package Specification

Đây là đặc tả chuẩn hóa và nền tảng workflow cho hệ thống tạo gói truyện từ prompt. 
Phiên bản hiện tại đã nghiệm thu workflow local MVP qua Stage 1–4 cho cả ba profile canonical. 
Provider mặc định vẫn là deterministic; chế độ `hybrid` hoặc `local` dùng llama.cpp cho sáng tác nhưng cần model được cấu hình rõ ràng.

Trạng thái đóng MVP và bằng chứng nghiệm thu nằm tại [`docs/mvp-closure.md`](docs/mvp-closure.md).

Nguồn đặc tả: `ChatGPT_prompt_v3.16.13.txt`, phiên bản `3.16.13`, SHA-256 `4c021a2e61df611a566c83c22fdf4378617314147de8dd6eaa9693160205ce27`.

## Nội dung

- `spec/registry.json`: enum, artifact, file set và quy tắc chuyển stage canonical cho MVP.
- `spec/execution_matrix.json`: ma trận profile × stage × operation.
- `spec/gates.json`: danh mục gate, owner, detector và mức độ chặn publish.
- `spec/mvp_contract.json`: phạm vi được đóng băng cho MVP và phần deferred.
- `spec/providers.json`: registry các chế độ provider `deterministic`, `hybrid`,
  `text_local` và `local`.
- `schemas/*.schema.json`: schema của các tài liệu chuẩn hóa.
- `fixtures/`: fixture hợp lệ và không hợp lệ dùng để kiểm contract.
- `tools/lint_spec.py`: linter chỉ dùng Python standard library.
- `src/ai_story/`: state machine, workspace, manifest, archive và CLI.
- `docs/`: quyết định chuẩn hóa và traceability về prompt nguồn.
- `docs/milestone-a.md`: baseline provider, environment doctor và manifest provenance.
- `docs/image-provider-abstraction.md`: model family, capability và runtime isolation.
- `docs/local-generator-upgrade.md`: best-of-N, scheduler và benchmark SD 3.5.
- `docs/milestone-b.md`: runtime contract, provider registry và chính sách vận hành model local.
- `docs/milestone-c.md`: orchestration Stage 1 bằng LLM local và semantic safety.
- `docs/milestone-d.md`: Diffusers, IP-Adapter và QA hình ảnh Stage 1–3.
- `docs/milestone-e.md`: shot design, continuity, phụ đề, TTS local tùy chọn và gói production Stage 4.
- `docs/milestone-f.md`: job engine bền vững, progress, cancel/retry, idempotency và GPU lane.
- `docs/milestone-g.md`: release evaluation, audit binding, provenance và distribution bundle.
- `docs/ux/`: discovery, kiến trúc thông tin, user flows và yêu cầu UI/UX MVP.

## Kiểm tra

```powershell
uv sync --dev
uv run python tools/lint_spec.py
uv run pytest -q
uv run ruff check src tests tools
```

Python 3.10–3.12 được hỗ trợ. 
`Pillow` là dependency lõi vì workflow deterministic dùng nó để tạo ảnh và typography từ Stage 1–3. Extra `local-image` chỉ bổ sung stack Diffusers/Transformers cho provider ảnh local. 
Trên Windows, dùng script thiết lập để tự nhận diện NVIDIA GPU, cài PyTorch CUDA build tương ứng và xác minh runtime:

```powershell
.\tools\setup_local_image.ps1
```

Mặc định script dùng CUDA 13.0 (`cu130`). Extra `cuda` và PyTorch CUDA index được khai báo trong `pyproject.toml`; phiên bản cùng wheel source được khóa trong `uv.lock`. 
Script dùng `uv sync --locked --extra cuda`, nên không còn bước cài PyTorch nằm ngoài lock. Nếu không phát hiện NVIDIA GPU, script đồng bộ extra CPU `local-image`. 
Hai extra được khai báo xung đột để không thể vô tình trộn CPU và CUDA trong cùng môi trường.

Có thể xác minh lock mà không thay đổi môi trường:

```powershell
uv lock --check
uv sync --locked --extra cuda --dry-run
```

## CI và quality gates

GitHub Actions chạy lint và toàn bộ test trên Python 3.10/3.12, áp ngưỡng branch coverage 70%, rồi chạy Stage 1–4 deterministic hai lần để phát hiện semantic drift. 
Chạy tương đương ở máy local bằng:

```powershell
uv run ruff check .
uv run pytest --cov=ai_story --cov-report=term-missing --cov-report=xml --cov-fail-under=70
uv run python tools/deterministic_smoke_gate.py --root artifacts/deterministic-smoke
```

Tất cả dependency trực tiếp đều có upper bound theo major version (hoặc exact pin cho cặp Torch/Torchvision). 
`uv lock --check` trong CI bắt buộc mọi thay đổi constraint phải được phản ánh trong `uv.lock`; việc nâng major version vì vậy phải là một thay đổi chủ động và được kiểm thử.

## CLI

```powershell
$env:PYTHONPATH = "src"
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
py -3.10 -m ai_story benchmark-plan
py -3.10 -m ai_story generate-benchmark-case --root .runtime-benchmark --case-id youth-promise-rain --provider-mode local
py -3.10 -m ai_story record-benchmark-case --case-id youth-promise-rain --package path\to\story.zip --output benchmark-records\youth-promise-rain.json
py -3.10 -m ai_story summarize-benchmark --records benchmark-records --output baselines/baseline-v4.json
py -3.10 -m ai_story run-benchmark-suite --output benchmark-runs/baseline-v4 --provider-mode deterministic
py -3.10 -m ai_story create-human-review-template --records benchmark-records --reviewer-id reviewer-a --output reviews/reviewer-a.json
py -3.10 -m ai_story evaluate-human-reviews --review-a reviewer-a.json --review-b reviewer-b.json --output baselines/human-agreement-v4.json
py -3.10 -m ai_story evaluate-benchmark --candidate candidate.json --baseline baseline.json

# Baseline chất lượng hình ảnh Stage 2-3 (8 case golden, có resume)
py -3.10 -m ai_story image-baseline-plan
py -3.10 -m ai_story run-image-baseline-suite --source-packages stage1-packages --output artifacts/benchmarks/image-baseline-sdxl-v1 --provider-mode local --quality-preset balanced --resume
py -3.10 -m ai_story create-image-review-template --records artifacts/benchmarks/image-baseline-sdxl-v1/records --reviewer-id reviewer-a --output reviews/image-reviewer-a.json
py -3.10 -m ai_story evaluate-image-reviews --review-a reviews/image-reviewer-a.json --review-b reviews/image-reviewer-b.json --output reviews/image-agreement.json
py -3.10 -m ai_story evaluate-image-benchmark --baseline baselines/image-v1.json --candidate baselines/image-v2.json --human-review reviews/image-agreement.json --output baselines/image-promotion-v2.json
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
py -3.10 -m ai_story evaluate-release path\to\stage4\story.zip --channel development --output release_report.json
py -3.10 -m ai_story evaluate-release path\to\stage4\story.zip --channel production --benchmark-evidence baselines/story-promotion.json --image-benchmark-evidence baselines/image-promotion-v2.json --framework-audit audits/framework.json --output release_report.json
py -3.10 -m ai_story build-release path\to\stage4\story.zip --channel development --output dist\ai-story-release.zip
py -3.10 -m ai_story verify-release dist\ai-story-release.zip
py -3.10 -m ai_story serve --root .runtime --host 127.0.0.1 --port 8765
```

`prepare-image-models` kiểm tra/tải diffusion model SD 3.5, semantic QA và learned latent upscaler. 
IP-Adapter và SDXL ControlNet không còn thuộc tập model được hỗ trợ. Chế độ local không âm thầm thay learned upscale bằng Lanczos khi model đã được bật nhưng không tải hoặc
inference thất bại; Lanczos fallback chỉ được dùng khi cấu hình `upscaler.enabled=false`.

Stage 2 local dựng ảnh bằng Stable Diffusion 3.5 Medium theo shot spec. Các capability SDXL như Depth ControlNet và IP-Adapter đã bị vô hiệu hóa.

Đặt `AI_STORY_PROVIDER_MODE=deterministic|hybrid|text_local|local` hoặc truyền `--provider-mode` cho Stage 1–3. 
`hybrid` dùng LLM local cho truyện và giữ image/safety deterministic; `text_local` dùng LLM local riêng cho story và safety nhưng giữ ảnh deterministic; `local` dùng thêm Diffusers SD 3.5 và image QA local. 
Hệ thống không tự hạ cấp provider.

Stage 4 tạo `production_plan.json`, SRT và WebVTT. 
TTS Piper là tùy chọn và chỉ chạy khi truyền cả `--render-tts` lẫn một voice model hợp lệ; pipeline không tự chọn voice hoặc hạ cấp sang dịch vụ khác.
Stage 3 luôn tạo visual-review sample cho cover và climax; Stage 4 ghi nhận phê duyệt bằng UI hoặc `--approve-visual-review`, hoặc tiếp tục với trạng thái review `PENDING`.

## Chính sách gate advisory

Gate nội dung, an toàn, biên tập và chất lượng hình ảnh không dừng workflow. 
Package vẫn chuyển qua Stage 1–4 theo transition canonical; các kết quả không đạt được giữ trong `story_validation.json`, `quality_decision.json`, `package_quality_report.json` và release report.
`release_status=BLOCKED` hoặc release bundle `distribution_status=NOT_APPROVED` là cảnh báo phát hành, không phải lỗi thực thi. Chỉ lỗi làm đầu ra không thể tạo hoặc không thể tin cậy về mặt cấu trúc—package hỏng, thiếu artifact, hash sai, provider lỗi, hoặc không ghi được file—mới làm lệnh thất bại.

Stage 4 không còn yêu cầu visual review để tiếp tục. Nếu chưa duyệt, `visual_review.json` được ghi với quyết định `PENDING`; `--approve-visual-review` ghi nhận xác nhận rõ ràng của người vận hành.

Mỗi package còn chứa `validation_ledger.json`, là báo cáo tích lũy xuyên Stage 1–4. Mỗi record có stage, category, severity, status, resolution status, evidence, locator và release impact. Ledger được khóa bằng SHA-256; release report nhúng summary, digest và toàn bộ warning còn mở để người vận hành không phải tổng hợp thủ công từ các sidecar riêng lẻ.

Dashboard hiển thị riêng trạng thái workflow và khuyến nghị phát hành. Màn Kiểm định hỗ trợ lọc ledger theo trạng thái xử lý, stage và severity. 
Trước khi chạy stage tiếp theo, hộp cấu hình công khai số cảnh báo được kế thừa nhưng không buộc người vận hành phải override hoặc xác nhận gate.
Package chưa đạt vẫn tải được với nhãn “kèm cảnh báo”.

Nghiệm thu MVP có thể chạy lại bằng `uv run python tools/validate_mvp.py`. 
Lệnh chạy lint, toàn bộ regression test, ba profile deterministic qua Stage 1–4, verify package/release bundle và ghi báo cáo JSON/Markdown có digest. Provider local thiếu model được ghi `NOT_EXECUTED`, không làm dừng nghiệm thu và không được suy diễn là production-ready.

Web dashboard MVP: xem [`docs/mvp-web.md`](docs/mvp-web.md).

GPT Image Web Assist thủ công, không dùng API và hoàn toàn tùy chọn: xem
[`docs/gpt-image-web-assist.md`](docs/gpt-image-web-assist.md).

Mục **Model local** trên dashboard quản lý catalog model riêng của workspace. Có thể đăng ký file local hoặc Hugging Face Model ID, xem trạng thái, chọn theo vai trò và gỡ đăng ký. Lệnh `remove` chỉ xóa bản ghi catalog, không xóa weights trên đĩa. Việc chọn model ghi nhận lựa chọn

Wizard và nút chạy stage tiếp theo cho phép chọn model riêng cho từng giai đoạn. 
Lựa chọn này chỉ áp dụng cho job hiện tại (không sửa cấu hình global) và được ghi vào provenance của package bằng `catalog_id`, model path/id, quantization và digest khi có. 
Stage 4 có thể chọn voice ONNX và bật render Piper ngay trong hộp cấu hình.

Đánh giá baseline và lộ trình chất lượng nằm tại `docs/package-quality-improvement-plan.md`.
Quy trình khóa baseline thực tế gồm corpus nội dung, hình ảnh và hai reviewer độc lập nằm tại
[`docs/real-baseline.md`](docs/real-baseline.md).

Mỗi stage hỗ trợ `--quality-preset fast|balanced|quality`. Provenance lưu preset, call/retry, thời gian runtime, peak memory và cost basis. Chính sách benchmark không tự nâng model mặc định:
candidate chỉ được đề xuất `PROMOTE` khi vượt baseline theo toàn bộ điều kiện trong `spec/benchmark.json`.
vận hành; runtime như llama.cpp vẫn cần được khởi động với weights tương ứng.

Trên Windows, có thể chạy trực tiếp [`open_app.bat`](open_app.bat) để khởi động server và mở dashboard bằng trình duyệt mặc định.

Linter kiểm tra schema cơ bản, tính duy nhất của ID, tham chiếu gate, coverage đủ 24 tổ hợp profile × stage × operation MVP, file set, ownership và chuỗi chuyển stage.
