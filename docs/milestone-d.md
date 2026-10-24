# Mốc D — Stage 2/3 hình ảnh production

## Đã triển khai

- Diffusers runtime nạp lười, hỗ trợ CUDA float16, model CPU offload, VAE slicing/tiling và unload VRAM.
- Stable Diffusion 3.5 Medium text-to-image cho character reference và landscape assets.
- Seed ổn định theo story, basename và attempt; retry chỉ thay seed của asset thất bại.
- Stage 3 dùng image-to-image với center-aware 9:16 crop và strength có cấu hình, không resize landscape đơn thuần.
- Ảnh được sinh ở working resolution phù hợp GPU 16 GB, upscale bằng learned latent x2 rồi chỉ
  resize phần tỷ lệ dư bằng Lanczos trước hậu kỳ có giới hạn để về kích thước canonical:
  - character: 1536 × 2048;
  - landscape: 3840 × 2160;
  - portrait: 1080 × 1920.
- QA trước commit gồm decode/dimensions, variance, luminance, Tesseract OCR, CLIP semantic score và CLIP cross-orientation parity.
- Asset không đạt QA được regenerate trong transaction budget; asset đã commit không bị tạo lại.
- Visual Plan lưu quality assessment cho từng landscape.
- Package Quality Report lưu landscape/portrait assessment ledger và chỉ dùng nhãn `LOCAL_TECHNICAL_OCR_CLIP` khi toàn bộ portrait đi qua production QA.
- Mode `local` dùng diffusion xuyên suốt character → landscape → portrait. Mode `hybrid` tiếp tục dùng ảnh deterministic để smoke-test text workflow nhẹ.

## Model mặc định

- Diffusion: local `D:\models\stable-diffusion-3.5-medium`.
- Identity: CLIP QA trên character reference; SD 3.5 không nạp IP-Adapter SDXL.
- Semantic QA: `openai/clip-vit-base-patch32`.
- Learned upscale: `stabilityai/sd-x2-latent-upscaler`.
- OCR: executable `tesseract` trên PATH, language `eng`.

Các model được nạp qua Hugging Face cache ở lần chạy đầu. Có thể thay `model_id`, IP-Adapter hoặc semantic model trong `spec/providers.json`, hoặc dùng file cấu hình riêng qua `AI_STORY_PROVIDER_CONFIG`. Model gated phải được người vận hành chấp nhận license và đăng nhập trước.

## Cài runtime

PyTorch CUDA phải được cài đúng driver trước. Sau đó:

```powershell
py -3.10 -m pip install -e ".[local-image]"
py -3.10 -m ai_story provider-status --mode local
py -3.10 -m ai_story prepare-image-models
```

Lệnh trên chỉ kiểm tra cache. Việc tải nhiều GB model phải được yêu cầu rõ ràng:

```powershell
py -3.10 -m ai_story prepare-image-models --download
```

Lệnh tải có thể yêu cầu đăng nhập Hugging Face hoặc chấp nhận license của model. Không ghi token vào `spec/providers.json`.

Tạo Stage 2/3 local:

```powershell
py -3.10 -m ai_story generate-stage2 `
  --root .runtime `
  --input-package path\to\stage1\story.zip `
  --mode ZONE `
  --provider-mode local

py -3.10 -m ai_story generate-stage3 `
  --root .runtime `
  --input-package path\to\stage2\story.zip `
  --provider-mode local
```

## Cấu hình GPU 16 GB

Working sizes mặc định là 1024 × 576 cho landscape, 704 × 1216 cho portrait và 768 × 1024 cho character. Learned upscaler chạy x2; landscape còn một residual resize nhỏ để đạt đúng 3840 × 2160. `model_cpu_offload=true` giảm peak VRAM nhưng tăng thời gian. Không chạy nhiều Diffusers job song song trên cùng GPU; runtime registry giữ accelerator lock trong process.

Nếu llama.cpp và Diffusers dùng chung GPU 16 GB, nên dùng LLM 7–8B Q4 hoặc offload phần lớn LLM sang CPU. `llama-server` là process ngoài nên runtime registry không thể tự giải phóng VRAM của nó khi chuyển sang Diffusers.

## Điều kiện publish

- OCR hoặc semantic assessor thiếu: asset local bị chặn.
- Ảnh gần như trống, quá tối/sáng, có text ngoài ý muốn hoặc semantic score thấp: regenerate.
- Portrait không đạt parity với landscape: regenerate.
- Hết attempt budget: stage thất bại và không tạo package release.

Model assessment không thay thế kiểm tra hash, dimension, lineage hoặc package integrity.

## Ranh giới

- Chưa chạy benchmark mỹ thuật trên bộ 30–50 brief vì model weights chưa được tải vào workspace.
- OCR mặc định có `eng`; nên cài thêm traineddata `vie` nếu artwork chủ động chứa tiếng Việt.
- Accelerator lock hiện chỉ bảo vệ trong một process; multi-process GPU scheduler thuộc mốc job engine.
