# Mốc G — Đánh giá và đóng gói release

## Release evaluator

Evaluator mở lại và xác minh package nguồn trước khi đánh giá. Báo cáo `release_report.json` tổng hợp:

- integrity và Stage 4 completeness;
- story gates, image quality và production-plan validation;
- provider-mode lineage và model inventory tích lũy xuyên Stage 1–4;
- dependency inventory của runtime đang đóng gói;
- external framework audit cho production;
- blocker, readiness và nhãn release rõ ràng.

Hai channel được hỗ trợ:

- `development`: cho phép provider deterministic nhưng luôn gắn nhãn `LOCAL_DEVELOPMENT`, không phải chứng nhận production;
- `production`: bắt buộc toàn bộ lineage là `local`, image assessment là `LOCAL_TECHNICAL_OCR_CLIP` và có audit ngoài hệ thống hợp lệ.

Runtime không tự tạo framework audit. Audit production phải do công cụ/người đánh giá độc lập cung cấp dưới dạng JSON:

```json
{
  "schema_version": "1.0",
  "status": "PASS",
  "auditor": "independent-auditor-id",
  "framework": "release-policy-name",
  "version": "2026.09",
  "evidence_sha256": "<64 lowercase hex characters>"
}
```

## CLI

Đánh giá mà chưa đóng gói:

```powershell
$env:PYTHONPATH = "src"
py -3.10 -m ai_story evaluate-release path\to\stage4\story.zip `
  --channel development `
  --output release_report.json
```

Tạo và xác minh distribution bundle:

```powershell
py -3.10 -m ai_story build-release path\to\stage4\story.zip `
  --channel development `
  --output dist\ai-story-release.zip

py -3.10 -m ai_story verify-release dist\ai-story-release.zip
```

Production thêm `--framework-audit path\to\audit.json`. Nếu có blocker, `build-release` thất bại và không tạo bundle.
Production cũng bắt buộc `--benchmark-evidence path\to\benchmark-evaluation.json`. Evidence phải
dùng đúng toàn bộ corpus canonical hiện hành, có digest hợp lệ, verdict `PROMOTE`, mọi promotion
check đều đạt, completion/outcome/editorial assessment đạt 100%, không có forbidden outcome/P0
defect và required-element recall đạt 100%. Kết quả từ corpus rút gọn chỉ dùng chẩn đoán, không thể
mở release gate.

## Bundle canonical

Release ZIP chỉ chứa bốn member:

- `story.zip` — package Stage 4 đã được verifier kiểm tra;
- `release_report.json` — evidence và quyết định readiness;
- `release_manifest.json` — version, channel, label và hash binding;
- `checksums.sha256` — checksum bàn giao.

ZIP writer dùng metadata timestamp cố định và thứ tự member ổn định. Verifier kiểm CRC, exact member set, report digest, ba hash binding và mở lại `story.zip` bằng package verifier gốc.

## Ranh giới

Mốc này triển khai contract tiếp nhận audit độc lập, không thực hiện audit bên ngoài. Với máy hiện tại chưa có đầy đủ model local production, package deterministic chỉ đủ điều kiện phát hành dưới nhãn development.
