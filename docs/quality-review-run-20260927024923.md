# Đánh giá chất lượng gói truyện `run-20260927024923-570cb82a`

Ngày đánh giá: 2026-09-27  
Phạm vi: Stage 1, preset `balanced`, profile `YOUTH_SAFE`, provider `deterministic`  
Đầu ra: `.runtime/run-20260927024923-570cb82a/output/story.zip`

## Kết luận

**Không nên chuyển gói này sang Stage 2 hoặc phát hành.** Package đạt yêu cầu kỹ thuật về schema,
hash, khả năng mở lại và đủ tám zone, nhưng chỉ là `WORKFLOW_CHECKPOINT` được tạo bằng fixture
deterministic. Manifest tự khai báo `artifact_class=TEST_FIXTURE`; báo cáo biên tập ghi
`editorial_status=NOT_ASSESSED_FIXTURE` và `critic_evidence_valid=false`.

Điểm tự động 98/100 không phản ánh chất lượng đọc thực tế. Lỗi trung tâm là truyện không giải quyết
đúng trở ngại trong brief: cây bút màu yêu thích bị hỏng chỉ được nhắc lại trong OPENING, rồi biến mất.
Lan chuyển thẳng sang luyện vẽ và thi mà không tìm cách sửa, thay thế, mượn hoặc thích nghi với cây
bút. Mục tiêu “giành giải nhất” cũng không có kết quả; ending chỉ nói Lan hoàn thành một placeholder
trừu tượng. Đây là lỗi bám brief và payoff cấp phát hành dù hai gate tương ứng đều chấm 100.

Đánh giá biên tập thủ công đề xuất: **42/100**. Mức sẵn sàng: **BLOCKED**.

## Bằng chứng và phát hiện

### 1. Tính toàn vẹn kỹ thuật — đạt

- `verify-package` mở lại thành công; package digest là
  `02b296c379b42595d6213da9a7c841f4f1e14bd20286764a446fed90118662c3`.
- Run và job cùng ở trạng thái `SUCCEEDED`, tiến độ 100%, có `story.zip`.
- 640 từ tương ứng 4,923 phút, nằm gần mục tiêu 5 phút; mọi zone kết thúc trọn câu.
- Hai ảnh nhân vật đúng kích thước khai báo, hash và pixel hash được ràng buộc vào package.

Điểm đạt trên chỉ chứng minh package nhất quán và chạy hết workflow, không chứng minh nội dung hay
hình ảnh đủ chất lượng xuất bản.

### 2. Bám brief và logic truyện — không đạt

- OPENING chép gần như nguyên văn brief. Cách này làm lexical coverage đạt 100% nhưng không tạo cảnh
  truyện tự nhiên và cho phép evaluator bị “game”.
- Trở ngại chính “cây bút màu yêu thích bị hỏng” không tạo quan hệ nhân quả với DEVELOPMENT,
  CLIMAX hoặc ENDING. Không có hành động khắc phục cụ thể.
- Câu “Lan hoàn thành hoàn thành mục tiêu trong đề bài” vừa lặp từ, vừa để lộ placeholder sản xuất.
  Cụm “mục tiêu trong đề bài” xuất hiện ở outline và nhiều zone nhưng gate placeholder không bắt được.
- Mục tiêu thắng giải được đặt ra nhưng không có kết quả cuộc thi. Payoff chuyển sang thông điệp
  “can đảm” mà không khép câu hỏi kịch tính ban đầu.
- Outline cũng chứa “hoàn thành hoàn thành”, cho thấy lỗi có từ bước lập dàn ý và được lan xuống kịch bản.

### 3. Chất lượng văn chương và nhịp — yếu

- Cốt truyện dùng khung mẫu “sợ thất bại → bạn động viên → chia nhỏ việc → can đảm”, thay vì khai
  thác tình huống riêng của hội họa và cây bút hỏng.
- Nhiều câu mang dấu vết padding theo template: hai câu cuối INTRODUCTION, DEVELOPMENT và FALLING
  lặp cùng cấu trúc và gần cùng ý. Bộ dò chỉ so trùng câu nên báo 0 repetition.
- Không gian thiếu liên tục: `school_hallway` được dùng cho cảnh luyện vẽ và phòng thi; FALLING khai
  báo `garden_morning` nhưng văn bản nói hành lang; ENDING khai báo `bedroom_warm` nhưng văn bản nói
  góc trưng bày.
- Minh chỉ làm chức năng động viên, không có động cơ hoặc nét riêng. Lan có agency ở climax nhưng lựa
  chọn của cô không gắn với vấn đề cây bút.
- Meta ghi target `3–18 tuổi`, trong khi gate áp profile `KIDS_7_10`. Một gói không nên đồng thời tuyên
  bố dải độc giả quá rộng và chấm theo một dải hẹp khác.

### 4. Chất lượng hình ảnh — chỉ đạt mức fixture

- Hai ảnh là hình học phẳng tối giản, dùng để kiểm workflow chứ chưa phải character art sẵn sàng cho
  sách/truyện video.
- Lan và Minh có khuôn mặt, tóc, cơ thể và silhouette gần như giống hệt; khác biệt chủ yếu là màu áo.
  Điều này làm identity lock yếu và khó giữ nhận dạng khi sinh cảnh sau.
- Minh được mô tả `ANDROGYNOUS`, “tóc nâu gọn”, “ba lô màu đất”, nhưng ảnh có tóc đen dài và không có
  ba lô. Gate chỉ xác nhận file ảnh tồn tại/nội dung deterministic, không kiểm visual traits thực tế.
- Ảnh không thể hiện rõ tuổi lớp 5, bối cảnh Việt Nam đương đại, biểu cảm hoặc đạo cụ đặc trưng.

### 5. Khoảng trống trong hệ thống chấm điểm — nghiêm trọng

- `BRIEF_ADHERENCE_GATE` đo tỷ lệ từ khóa, nên đoạn chép brief đủ để đạt 100% dù sự kiện không được
  triển khai hoặc giải quyết.
- `NARRATIVE_INVARIANT_GATE` báo `invariant_count=0`; hệ thống chưa rút ra invariant/state quan trọng
  từ brief này như `pencil=broken` rồi yêu cầu một chuyển trạng thái hợp lệ.
- `STORY_QUALITY_GATE` cho 98 nhưng đồng thời ghi `assessment_basis=DETERMINISTIC_PREFLIGHT_ONLY`,
  `critic_evidence_valid=false`. Điểm preflight không được trình bày như điểm biên tập.
- `concrete_scene_craft=95` không đối chiếu environment metadata với địa điểm được kể trong câu.
- `repetition_and_style=100` bỏ lọt lặp từ, placeholder và padding có cùng cấu trúc.
- Runtime thực tế mất gần 29 giây, trong khi provenance ghi `duration_ms=0`, `call_count=0`; telemetry
  deterministic hiện không phản ánh chi phí vận hành thật.

## Kế hoạch nâng chất lượng

### P0 — chặn false pass trước khi sinh ảnh

1. Tách `technical_preflight_score` khỏi `editorial_score`. Khi không có critic/human evidence,
   `editorial_score` phải là `null`, trạng thái `NOT_ASSESSED`, và release/next-stage bị chặn.
2. Thêm kiểm placeholder sau serialize cho các cụm như “trong đề bài”, “mục tiêu trong đề bài”, từ
   lặp liền nhau và câu mô tả thao tác sinh nội dung.
3. Rút state graph từ brief: đối tượng, trạng thái ban đầu, hành động khắc phục và trạng thái cuối.
   Với ca này tối thiểu phải theo dõi `bút màu: hoạt động → hỏng → sửa/thay/mượn/tái sử dụng`.
4. Bám brief theo event coverage, không theo lexical coverage: mỗi sự kiện phải có locator ở setup,
   consequence và resolution; không tính đoạn chép nguyên brief là bằng chứng độc lập.
5. Bắt buộc khép goal ở ending: thắng, không thắng, hoặc kết quả chưa công bố đều phải được nói rõ và
   phù hợp với payoff.

Tiêu chí nghiệm thu:

- Gói hiện tại phải bị đánh `BLOCKED` bởi placeholder, unresolved obstacle và missing goal outcome.
- Một bản sửa phải có evidence locator cho đủ setup → consequence → response → resolution.
- Không có critic/human review thì UI không hiển thị “98/100 chất lượng biên tập”.

### P1 — nâng chất lượng câu chuyện

1. Viết lại outline quanh lựa chọn cụ thể: Lan thử sửa bút, phát hiện không cứu được, rồi chọn phối màu
   bằng bộ bút còn lại/mượn có giới hạn/tạo kỹ thuật mới. Quyết định của Lan phải làm thay đổi bức tranh.
2. Cho cuộc thi một kết quả rõ. Không nhất thiết Lan thắng; kết quả cần trả lời goal ban đầu và làm
   thông điệp trưởng thành thuyết phục hơn.
3. Loại padding và câu khái quát. Mỗi zone phải thêm một beat mới, một chi tiết cảm giác/hội họa và
   một thay đổi trạng thái có thể quan sát.
4. Đồng bộ `environment` với nội dung; thêm gate so khớp location entities giữa metadata và text.
5. Chọn một audience canonical, đề xuất `7–10`, rồi đồng bộ `meta.target`, từ vựng, câu dài và rubric.

Tiêu chí nghiệm thu:

- Cold-reader 3 người đều trả lời đúng: bút hỏng ra sao, Lan xử lý thế nào, kết quả cuộc thi là gì.
- Không còn placeholder/lặp từ; không zone nào chỉ diễn đạt lại ý của zone trước.
- Mọi location metadata khớp cảnh kể; điểm human editorial tối thiểu 80/100, không chiều nào dưới 3/5.

### P1 — nâng chất lượng hình ảnh và identity

1. Không dùng ảnh deterministic làm evidence hình ảnh ngoài test. Gắn watermark/nhãn fixture trong UI
   và chặn Stage 2 production khi reference asset là deterministic.
2. Sinh character sheet thực với front/three-quarter/expression, khóa rõ tóc, trang phục, vóc dáng và
   đạo cụ. Minh phải có hình thái phân biệt Lan và khớp toàn bộ identity traits.
3. Thêm visual-trait assessment độc lập cho hair, wardrobe, palette, silhouette, age, presentation và
   required prop; file/hash hợp lệ không được xem là identity PASS.
4. Human review hai reference trước Stage 2, sau đó dùng chúng làm identity reference cho các shot.

Tiêu chí nghiệm thu:

- 100% trait bắt buộc được VLM/human xác nhận; không trait khai báo nào vắng trong ảnh.
- Người đánh giá phân biệt Lan/Minh khi che tên với tỷ lệ 100% trên bộ review.
- Asset fixture không thể đi vào package production.

### P2 — regression và quan sát vận hành

1. Thêm chính brief này vào corpus như ca `broken-tool-resolution`; expected failure gồm obstacle biến
   mất, chép brief, missing competition result và placeholder.
2. Thêm adversarial cases trong đó toàn bộ từ khóa xuất hiện nhưng quan hệ nhân quả sai hoặc không có.
3. Ghi wall-clock duration và số lần gọi provider cho cả deterministic adapter; kiểm chênh lệch giữa
   job duration và manifest runtime metrics.
4. Theo dõi tỷ lệ false pass qua human review. Không promote rubric nếu precision của blocker dưới
   95% hoặc nếu bất kỳ lỗi P0 đã gắn nhãn nào vẫn PASS.

## Thứ tự thực hiện đề xuất

- Sprint 1: P0 evaluator + regression cho chính gói này.
- Sprint 2: sửa generator/outline và sinh lại Stage 1; review lạnh trước khi tiếp tục.
- Sprint 3: character references thật + visual-trait gate; chỉ sau đó mới chạy Stage 2.
- Sprint 4: hiệu chỉnh rubric bằng corpus/human labels và sửa telemetry.

Không nên sửa trực tiếp package hiện tại. Hãy giữ nó làm negative regression fixture và tạo run Stage 1
mới sau khi hoàn tất P0–P1.
