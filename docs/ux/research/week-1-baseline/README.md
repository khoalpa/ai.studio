# Nghiên cứu và đo baseline — Tuần 1

## Mục tiêu nghiên cứu

Nghiên cứu này đo khả năng sử dụng hiện tại của AI Story trước khi thay đổi kiến trúc thông tin hoặc giao diện. Kết quả cần trả lời bốn câu hỏi:

1. Người dùng có tự tạo được Stage 1 mà không cần hướng dẫn không?
2. Người dùng có xác định đúng blocker cần xử lý đầu tiên không?
3. Người dùng có hiểu điều kiện để chạy stage tiếp theo không?
4. Người dùng có kiểm tra được package bên ngoài và diễn giải đúng kết quả không?

Không dùng mục tiêu trong `mvp-requirements.md` làm kết quả baseline. Chỉ công bố baseline hành vi sau khi hoàn tất các phiên có người tham gia.

## Phạm vi và mẫu nghiên cứu

- Tuyển 5–6 người tham gia.
- Có ít nhất 3 người làm vận hành hoặc sản xuất nội dung.
- Có ít nhất 2 người làm biên tập hoặc QA.
- Có thể bổ sung 1 người hiểu workflow CLI hiện tại.
- Mỗi phiên kéo dài 45–60 phút và được thực hiện riêng.
- Mọi phiên dùng cùng một build, workspace khởi tạo và bộ dữ liệu.

## Bộ tài liệu

### Chuẩn bị và điều phối

- [Kế hoạch tuyển người](./participant-recruitment.md)
- [Kịch bản usability test](./usability-test-script.md)
- [Phiếu ghi nhận phiên test](./session-notes-template.md)
- [Khung đo và cách tổng hợp](./measurement-framework.md)
- [Baseline sản phẩm](./product-baseline-2026-10-10.md)
- [Báo cáo pilot nội bộ](./internal-pilot-2026-10-10.md)
- [Sổ theo dõi năm phiên chính](./main-session-register.md)
- [Runbook điều phối P01](./p01-session-runbook.md)
- [Phiếu ghi nhận P01](./p01-session-notes.md)

### Phân tích và xác thực

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

## Quy trình thực hiện

1. Sửa hoặc cô lập lỗi kiểm thử kỹ thuật được ghi trong baseline sản phẩm.
2. Sinh dataset cố định bằng `tools/prepare_week1_usability_dataset.py`.
3. Chạy pilot nội bộ với một người không tham gia phát triển giao diện.
4. Điều chỉnh câu chữ trong kịch bản nếu cần nhưng không thay đổi bản chất nhiệm vụ.
5. Thực hiện 5 phiên chính. Chỉ dùng phiên thứ 6 khi mẫu vai trò chưa cân bằng hoặc dữ liệu chưa bão hòa.
6. Với mỗi phiên, điền một dòng CSV và một phiếu ghi nhận.
7. Tổng hợp tỷ lệ hoàn thành, thời gian, lỗi nghiêm trọng và mức độ hiểu trạng thái.
8. Ưu tiên pain point theo công thức tần suất × tác động.

## Sinh lại dataset

```powershell
$env:PYTHONPATH = "src;."
py -3 tools/prepare_week1_usability_dataset.py --output artifacts/usability-study/week1-v1
```

Script chỉ thay thế thư mục đích khi thư mục đó có marker do chính script tạo. Dataset gồm bốn tình huống: workspace sạch, workspace có blocker, workspace sẵn sàng chạy Stage 2 và package có cảnh báo.

## Nguyên tắc nghiên cứu

- Không chỉ vị trí nút hoặc giải thích thuật ngữ khi người tham gia đang thực hiện nhiệm vụ.
- Khi người tham gia bị kẹt, ghi lại thời điểm rồi dùng đúng cấp hỗ trợ được quy định trong khung đo.
- Không thu âm hoặc lưu thông tin nhận dạng nếu chưa có sự đồng ý rõ ràng.
- Không dùng dữ liệu production hoặc nội dung nhạy cảm.
- Phân biệt rõ lỗi sản phẩm, lỗi dữ liệu thử nghiệm và lỗi môi trường.

## Điều kiện hoàn thành

- Có ít nhất 5 phiên hợp lệ.
- Mỗi vai trò chính có ít nhất 2 người tham gia.
- 100% phiên có phiếu ghi nhận và dòng dữ liệu tương ứng.
- Có baseline cho cả bốn nhiệm vụ, kèm cỡ mẫu.
- Có 5 pain point quan trọng nhất cùng bằng chứng quan sát.
- Có danh sách quyết định sản phẩm được đề xuất cho Tuần 2.

## Đánh giá điều kiện hoàn thành

Đặt `session_source=HUMAN` cho phiên có người thật; dùng `role=OPERATIONS` hoặc `role=EDITORIAL_QA` theo nhóm vai trò. Không thay đổi nguồn của phiên pilot hoặc phiên mô phỏng. Sau khi có kết quả NVDA thực tế, sao chép mẫu JSON thành tệp kết quả rồi cập nhật các giá trị.

```powershell
py -3 tools/evaluate_ux_validation.py `
  --sessions docs/ux/research/week-1-baseline/validation-session-results.csv `
  --nvda docs/ux/research/week-1-baseline/nvda-validation-result.json `
  --output docs/ux/research/week-1-baseline/validation-completion-report.md
```

Mã thoát `0` nghĩa là đã hoàn thành, `2` nghĩa là còn thiếu bằng chứng, còn `1` cho biết dữ liệu đầu vào không hợp lệ. Dữ liệu `PILOT` và `SIMULATED_CODEX` luôn bị loại khỏi mẫu người thật.
