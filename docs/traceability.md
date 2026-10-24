# Traceability với prompt 3.16.13

| Thành phần chuẩn hóa | Khu vực nguồn |
|---|---|
| Profile | `MODULE:HEADER`, `MODULE:ROUTING_KERNEL` |
| Enum và constant nền | `MODULE:CANONICAL_REGISTRY` |
| Stage/file set/manifest | `MODULE:WORKFLOW_CONTRACT` |
| Story artifact và validation | `MODULE:STORY_ARTIFACT_VALIDATION_KERNEL` |
| Image mode và visual plan | `MODULE:VISUAL_PLANNING_DUAL_MODE` |
| Image transaction | `MODULE:IMAGE_TRANSACTION_KERNEL` |
| Safety | `MODULE:PROFILE_SAFETY` |
| Gate nội dung | `MODULE:STORY_GATES` |
| Landscape/portrait/package | các module gate tương ứng |
| Video prompt | `MODULE:VIDEO_PROMPT_GATES` |
| Repair | `MODULE:REPAIR_KERNEL` |

## Phân loại phạm vi

- `implemented_in_spec`: được biểu diễn trong registry/matrix/gates và được linter kiểm.
- `reserved`: enum hoặc artifact được giữ để bảo toàn thiết kế nhưng runtime MVP chưa được phép dùng.
- `deferred`: chưa thuộc MVP; phải có ADR và fixture trước khi kích hoạt.
- `external_audit_only`: không được runtime tự tuyên bố PASS.

Các phần deferred chính: `SCENE`, resume bundle, legacy migration, việc thực hiện framework release audit bên ngoài, semantic scoring chi tiết và provider-specific capability checks. Runtime đã hỗ trợ bind và kiểm tra provenance của kết quả audit độc lập nhưng không tự phát hành kết quả audit đó.
