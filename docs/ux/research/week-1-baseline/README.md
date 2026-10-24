# Tuần 1 — Nghiên cứu và đo baseline

## Mục tiêu

Tuần nghiên cứu này đo khả năng sử dụng hiện tại của AI Story trước khi thay đổi kiến trúc thông tin hoặc giao diện. Kết quả phải trả lời bốn câu hỏi:

1. Người dùng có tạo được Stage 1 mà không cần hướng dẫn hay không?
2. Người dùng có xác định đúng blocker cần xử lý đầu tiên hay không?
3. Người dùng có hiểu điều kiện để chạy stage tiếp theo hay không?
4. Người dùng có kiểm tra được một package bên ngoài và diễn giải đúng kết quả hay không?

Không dùng các mục tiêu trong `mvp-requirements.md` như kết quả baseline. Baseline hành vi chỉ được công bố sau khi hoàn thành các phiên có người tham gia.

## Phạm vi và mẫu nghiên cứu

- 5–6 người tham gia.
- Ít nhất 3 người làm vận hành hoặc sản xuất nội dung.
- Ít nhất 2 người làm biên tập hoặc QA.
- Có thể bổ sung 1 người hiểu workflow CLI hiện tại.
- Mỗi phiên kéo dài 45–60 phút, thực hiện riêng từng người.
- Dùng cùng một build, workspace khởi tạo và bộ dữ liệu cho mọi phiên.

## Tài liệu sử dụng

- [Kế hoạch tuyển người](./participant-recruitment.md)
- [Kịch bản usability test](./usability-test-script.md)
- [Phiếu ghi nhận phiên test](./session-notes-template.md)
- [Khung đo và cách tổng hợp](./measurement-framework.md)
- [Baseline sản phẩm](./product-baseline-2026-10-10.md)
- [Báo cáo pilot nội bộ](./internal-pilot-2026-10-10.md)
- [Sổ theo dõi năm phiên chính](./main-session-register.md)
- [Runbook điều phối P01](./p01-session-runbook.md)
- [Phiếu ghi nhận P01](./p01-session-notes.md)
- [Năm giả thuyết pain point](./provisional-pain-point-hypotheses.md)
- [Kiểm tra accessibility và responsive](./week2-accessibility-responsive-audit-2026-10-10.md)
- [Vòng validation UI/UX và checklist NVDA](./week2-validation-round-2026-10-10.md)
- [Cải tiến hierarchy của Validation Center](./week2-information-hierarchy-iteration.md)
- [Điều kiện hoàn thành và trạng thái hiện tại](./completion-criteria-and-status.md)
- [Kết quả năm phiên mô phỏng Codex](./simulated-session-results-2026-10-10.md)
- [Dữ liệu phiên mô phỏng](./session-results-simulated.csv)
- [Mẫu dữ liệu phiên test](./session-results-template.csv)
- [Dữ liệu validation người thật](./validation-session-results.csv)
- [Mẫu kết quả NVDA](./nvda-validation-result.template.json)
- [Báo cáo cổng hoàn thành hiện tại](./validation-completion-report.md)

## Trình tự thực hiện

1. Sửa hoặc cô lập lỗi test kỹ thuật ghi trong baseline sản phẩm.
2. Sinh dataset cố định bằng `tools/prepare_week1_usability_dataset.py`.
3. Chạy pilot nội bộ với một người không tham gia phát triển giao diện.
4. Điều chỉnh câu chữ của kịch bản, không thay đổi bản chất nhiệm vụ.
5. Thực hiện 5 phiên chính; phiên thứ 6 dùng khi mẫu vai trò chưa cân bằng hoặc dữ liệu chưa bão hòa.
6. Điền một dòng trong CSV và một phiếu ghi nhận cho từng phiên.
7. Tổng hợp tỷ lệ hoàn thành, thời gian, lỗi nghiêm trọng và mức hiểu trạng thái.
8. Tổ chức buổi ưu tiên pain point theo tần suất × tác động.

## Sinh lại dataset

```powershell
$env:PYTHONPATH = "src;."
py -3 tools/prepare_week1_usability_dataset.py --output artifacts/usability-study/week1-v1
```

Script chỉ thay thế thư mục đích khi thư mục đó có marker do chính script tạo. Dataset gồm workspace sạch, workspace có blocker, workspace sẵn sàng chạy Stage 2 và package có cảnh báo.

## Quy tắc nghiên cứu

- Không hướng dẫn vị trí nút hoặc giải thích thuật ngữ trong lúc người dùng đang làm nhiệm vụ.
- Nếu người tham gia bị kẹt, ghi thời điểm rồi dùng đúng cấp hỗ trợ trong khung đo.
- Không thu âm hoặc lưu thông tin nhận dạng khi chưa có đồng ý rõ ràng.
- Không dùng dữ liệu production hoặc nội dung nhạy cảm.
- Phân biệt lỗi sản phẩm, lỗi dữ liệu thử nghiệm và lỗi môi trường.

## Definition of done

- Có ít nhất 5 phiên hợp lệ.
- Mỗi vai trò chính có ít nhất 2 người tham gia.
- 100% phiên có phiếu ghi nhận và dòng dữ liệu tương ứng.
- Có baseline cho bốn nhiệm vụ, kèm cỡ mẫu.
- Có top 5 pain point với bằng chứng quan sát.
- Có danh sách quyết định sản phẩm đề xuất cho Tuần 2.

## Kiểm tra điều kiện hoàn thành

Điền `session_source=HUMAN` cho phiên người thật, `role=OPERATIONS` hoặc
`role=EDITORIAL_QA` theo nhóm vai trò. Không đổi nguồn của phiên pilot hay phiên mô phỏng.
Sau khi có kết quả NVDA thật, sao chép mẫu JSON sang tệp kết quả và cập nhật các giá trị.

```powershell
py -3 tools/evaluate_ux_validation.py `
  --sessions docs/ux/research/week-1-baseline/validation-session-results.csv `
  --nvda docs/ux/research/week-1-baseline/nvda-validation-result.json `
  --output docs/ux/research/week-1-baseline/validation-completion-report.md
```

Mã thoát `0` nghĩa là hoàn thành, `2` nghĩa là còn thiếu bằng chứng và `1` nghĩa là dữ
liệu đầu vào không hợp lệ. Dữ liệu `PILOT` và `SIMULATED_CODEX` luôn bị loại khỏi mẫu
người thật.
