# Baseline chất lượng thực tế

Baseline thực tế khóa bốn nguồn bằng chứng: benchmark nội dung 27 case, benchmark hình ảnh 8 case,
đánh giá nội dung của hai người và đánh giá hình ảnh của hai người. Báo cáo cuối chỉ có trạng thái
`READY` khi toàn bộ nguồn có digest hợp lệ, đủ case, cùng corpus và đạt ngưỡng agreement. Thiếu hoặc
sửa tay bất kỳ báo cáo nguồn nào làm quá trình tổng hợp thất bại hoặc trả blocker.

## Phạm vi đã đóng băng

- Ba profile: `YOUTH_SAFE`, `ADULT_STANDARD`, `SERIAL_DETECTIVE`.
- 27 brief gồm brief mỏng, điều kiện phủ định, nhiều nhân vật và bối cảnh Việt Nam.
- 8 case hình ảnh đại diện; review cover, climax và ending ở cả hai hướng ảnh.
- Provider ảnh local và preset `quality`; mỗi case dùng seed cố định.
- Hai reviewer độc lập. Nội dung yêu cầu Cohen's kappa tối thiểu 0,70; hình ảnh yêu cầu agreement
  vượt gate hiện hành và điểm trung bình tối thiểu 4/5.

Xem scope và digest hiện hành:

```powershell
uv run python -m ai_story real-baseline-plan
```

## Quy trình tạo baseline

Kiểm tra model và môi trường trước. Không dùng provider `deterministic` cho baseline thực tế.

```powershell
uv run python -m ai_story doctor
uv run python -m ai_story provider-status --mode local --no-probe
```

### 1. Chạy corpus nội dung

```powershell
uv run python -m ai_story run-benchmark-suite `
  --output artifacts/baselines/real-v1/story `
  --provider-mode local `
  --quality-preset quality `
  --resume
```

Lệnh tạo `baseline.json`, record từng case, package Stage 1 có tên ổn định trong `packages/` và hai
form độc lập trong `reviews/`. Baseline và record là immutable; `--resume` chỉ bỏ qua case khi cả
record lẫn package đã tồn tại và có identity canonical hợp lệ.

### 2. Chạy corpus hình ảnh

```powershell
uv run python -m ai_story run-image-baseline-suite `
  --source-packages artifacts/baselines/real-v1/story/packages `
  --output artifacts/baselines/real-v1/image `
  --provider-mode local `
  --quality-preset quality `
  --resume
```

Lệnh tạo Stage 2–3, record machine QA, baseline hình ảnh và hai form review. Không sửa trực tiếp
`baseline.json`; muốn chạy cấu hình khác phải dùng thư mục output mới.

### 3. Hai người đánh giá độc lập

Reviewer điền riêng các file `reviewer-a.json` và `reviewer-b.json`, không xem quyết định của nhau.
Sau khi điền đủ:

```powershell
uv run python -m ai_story evaluate-human-reviews `
  --review-a artifacts/baselines/real-v1/story/reviews/reviewer-a.json `
  --review-b artifacts/baselines/real-v1/story/reviews/reviewer-b.json `
  --output artifacts/baselines/real-v1/story/human-agreement.json

uv run python -m ai_story evaluate-image-reviews `
  --review-a artifacts/baselines/real-v1/image/reviews/reviewer-a.json `
  --review-b artifacts/baselines/real-v1/image/reviews/reviewer-b.json `
  --output artifacts/baselines/real-v1/image/human-agreement.json
```

Nếu agreement không đạt, hai reviewer hòa giải ngoài các form gốc. Không thay quyết định cũ để làm
đẹp kappa; chạy review vòng mới bằng reviewer/run ID mới.

### 4. Khóa hồ sơ baseline thống nhất

```powershell
uv run python -m ai_story assemble-real-baseline `
  --story-baseline artifacts/baselines/real-v1/story/baseline.json `
  --image-baseline artifacts/baselines/real-v1/image/baseline.json `
  --story-review artifacts/baselines/real-v1/story/human-agreement.json `
  --image-review artifacts/baselines/real-v1/image/human-agreement.json `
  --provider-mode local `
  --quality-preset quality `
  --run-label real-v1-2026-10-01 `
  --output artifacts/baselines/real-v1/real-baseline.json
```

`real-baseline.json` chứa metric nội dung, hình ảnh, human agreement, môi trường chạy, digest nguồn
và blocker. File được tạo theo chế độ create-only nên không thể vô tình ghi đè baseline cũ.

## Quy tắc đọc kết quả

- `READY`: đủ bốn nguồn evidence, digest hợp lệ và human review đạt ngưỡng.
- `INCOMPLETE`: báo cáo được tạo nhưng còn check không đạt; không dùng làm mốc promotion.
- Lỗi digest/schema: dừng ngay vì nguồn đã bị sửa hoặc không thuộc suite canonical.

Không dùng một điểm trung bình để che blocker. Defect taxonomy, p10/p90, completion, retry, latency,
VRAM, required-element recall, OCR và identity vẫn được giữ trong hai báo cáo baseline nguồn.
