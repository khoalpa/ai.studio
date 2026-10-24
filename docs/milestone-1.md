# Mốc 1 — Nền tảng workflow

## Thành phần

- State machine kiểm tra profile, operation, stage và transition.
- Run workspace tách `input`, `work`, `output`, `logs`.
- Event log NDJSON có timestamp, run ID và payload cấu trúc.
- Artifact record gồm path chuẩn hóa, owner stage, kích thước và SHA-256.
- Manifest đúng 13 root field theo prompt 3.16.13.
- ZIP builder không cập nhật archive tại chỗ.
- Reopen verifier kiểm duplicate member, đường dẫn nguy hiểm, CRC, allowlist, hash, size, ownership và manifest.
- CLI để tạo run, build, verify và inspect package.

## Quy ước digest

`workflow_manifest.package_digest_sha256` là SHA-256 của canonical JSON projection chứa các record member không gồm manifest. Quy ước này không tự tham chiếu.

SHA-256 của chính `story.zip` được trả riêng như thông tin integrity phụ. `parent_package_digest_sha256` của stage kế tiếp hoặc của REPAIR bind canonical `package_digest_sha256` của package nguồn, không bind container ZIP vì metadata nén có thể thay đổi.

## Ranh giới

Mốc 1 không kiểm tra schema nội dung của `story.json`, chất lượng ảnh hoặc safety ngữ nghĩa. Các gate đó thuộc các mốc generation tiếp theo. Nền tảng hiện chỉ đảm bảo workflow, integrity, ownership và package lineage.
