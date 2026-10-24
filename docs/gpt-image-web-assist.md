# GPT Image Web Assist tùy chọn

Đây là cầu nối thủ công, không dùng GPT Image API, không đọc cookie và không tự động đăng nhập.
Pipeline local vẫn là mặc định; assist chỉ thay những landscape mà người vận hành chủ động cung cấp.

## 1. Xuất bundle

```powershell
py -3.10 -m ai_story export-gpt-image-web-assist `
  --input-package path\to\stage2\story.zip `
  --output artifacts\gpt-image-assist `
  --asset cover.png `
  --asset climax.png
```

Nếu bỏ `--asset`, bundle chứa cả mười ảnh. Mỗi asset có prompt, landscape hiện tại, character
references, kích thước bắt buộc và đường dẫn kết quả. Bundle được khóa với digest của Stage 2 package.

## 2. Tạo ảnh trên GPT Image Web

Mở GPT Image Web thủ công, tải các reference được liệt kê, dán prompt tương ứng và tải PNG cuối cùng
vào `results/<basename>`. Không đưa API key, session cookie hoặc thông tin đăng nhập vào bundle.

Người vận hành phải kiểm tra identity, tuổi, tóc, wardrobe, palette, đạo cụ, bố cục, chữ ngoài ý muốn
và watermark. Web assist không được xem là model-assessed QA.

## 3. Xác minh và áp dụng

```powershell
py -3.10 -m ai_story apply-gpt-image-web-assist `
  --root .runtime `
  --input-package path\to\stage2\story.zip `
  --assist-bundle artifacts\gpt-image-assist `
  --confirm-human-reviewed
```

Import chỉ nhận kết quả có tên canonical, PNG 3840×2160, decode được và đạt variance/luminance gate.
Lệnh tạo package Stage 2 `REPAIR`; Visual Plan, Visual Bible, image hash và provenance được cập nhật.
Stage 3 sau đó tạo portrait từ landscape đã duyệt.

`--confirm-human-reviewed` là bắt buộc. Không có kết quả nào được tự lấy từ website và không có ảnh
web nào được tự động thay thế asset local.
