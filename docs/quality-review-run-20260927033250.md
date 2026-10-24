# Đánh giá chất lượng gói truyện `run-20260927033250-8dceca4a`

Ngày đánh giá: 2026-09-27  
Phạm vi: Stage 1, preset `balanced`, profile `YOUTH_SAFE`, provider `deterministic`  
Đầu ra: `.runtime/run-20260927033250-8dceca4a/output/story.zip`

## Kết luận

**Không chuyển sang Stage 2 và không phát hành.** Gói đạt tính toàn vẹn kỹ thuật nhưng không đạt chất
lượng nội dung. Manifest xác nhận đây là `WORKFLOW_CHECKPOINT`, `artifact_class=TEST_FIXTURE`,
`content_quality_status=BLOCKED`, và không cho phép stage tiếp theo. `verify-package` mở lại thành công
với package digest `9ccf9bd4667c3e5b913b752abec09811c2d2f36d2246c1906718c55175989b1d`.

Điểm tự động 94/100 không đáng tin như một đánh giá biên tập: báo cáo ghi rõ
`assessment_basis=DETERMINISTIC_PREFLIGHT_ONLY`, `critic_evidence_valid=false` và
`editorial_status=NOT_ASSESSED_FIXTURE`. Đánh giá thủ công đề xuất: **28/100 — BLOCKED**.

Lỗi trung tâm là sai thể loại và sai chuỗi sự kiện. Brief yêu cầu Hà cùng mẹ bảo vệ nhà trước bão rồi
sơ tán; từ INTRODUCTION trở đi, truyện chuyển thành luyện vẽ, trình bày tranh trong phòng đông người
và trưng bày tác phẩm. Không có hành động gia cố nhà, di chuyển vật giá trị, chuẩn bị sơ tán, thời hạn
bão tới hoặc kết quả an toàn của gia đình.

## Phát hiện chính

### P0 — sai brief và logic nhân vật

- OPENING gần như chép brief, nhờ đó lexical coverage đạt 89,8%; phần còn lại không triển khai các sự
  kiện đó. Đây là false pass điển hình của `BRIEF_ADHERENCE_GATE`.
- Cốt truyện nhảy vô cớ từ nhà ven biển và bão sang thư viện, luyện nét, pha màu, trình bày tranh và
  góc trưng bày. Không có cầu nối nhân quả hoặc mục tiêu hội họa trong brief.
- ENDING dùng câu máy móc “Hà hoàn thành đảm bảo an toàn...” nhưng ngay sau đó nói trình bày ý tưởng
  và giữ bức tranh. Câu tuyên bố hoàn thành không có bằng chứng hành động trong truyện.
- “Mẹ” bị khai báo 10 tuổi, `NOT_ADULT`, vai trò người đồng hành, ngoại hình học sinh; lời kể gọi Hà
  và Mẹ là “hai bạn”, còn Mẹ xưng “cậu/tớ”. Đây là lỗi vai trò, tuổi, quan hệ và thoại.
- `NARRATIVE_INVARIANT_GATE` báo PASS với `invariant_count=0`, nên không theo dõi các trạng thái cốt
  lõi như bão đang tới, nhà cần được bảo vệ, đồ giá trị cần di chuyển, gia đình phải sơ tán.

### P0 — trạng thái chất lượng và điều phối

- Job/run là `SUCCEEDED` dù hai gate chất lượng (`AGE_PROFILE_GATE`, `STORY_QUALITY_GATE`) FAIL.
  Thành công ở đây chỉ nên có nghĩa workflow chạy xong; UI phải hiển thị rõ “tạo xong nhưng bị chặn”.
- Quality commitment vẫn lưu `quality_score=94`, dễ bị dùng sai ở downstream, dù status biên tập là
  chưa đánh giá và package bị chặn.
- Runtime thực tế khoảng 28 giây nhưng manifest ghi `duration_ms=0`, `call_count=0`; telemetry không
  phản ánh thời gian vận hành của deterministic pipeline.

### P1 — văn phong, cảnh và nhịp

- OPENING có câu rời “Khi một cơn bão lớn đang tiến tới.” và lặp thông tin Hà sống ở thị trấn ven
  biển, mục tiêu bảo vệ nhà.
- Câu “chia việc ... thành phác thảo, luyện tập và trình bày” vừa không tự nhiên vừa làm lộ template
  của một truyện thi vẽ được ghép nhầm.
- DEVELOPMENT và FALLING có padding theo mẫu: hai hành động gần tương đương được lặp để đủ dung lượng
  (“luyện nét cong”/“pha thử màu”; “ngắm lại tác phẩm”/“lau màu trên tay”).
- Environment không khớp văn bản: `school_hallway` kể “căn phòng yên tĩnh”; `garden_morning` kể hành
  lang; `bedroom_warm` kể góc trưng bày. Bối cảnh nhà ven biển gần như biến mất.
- Target metadata là `3–18 tuổi`, trong khi validator dùng `KIDS_7_10`. Ba câu vượt giới hạn 28 từ;
  dải 3–18 cũng quá rộng để thiết kế từ vựng và nhịp nhất quán.

### P1 — hình ảnh tham chiếu

- Hai ảnh là hình học deterministic tối giản, phù hợp kiểm workflow chứ không đủ làm character art
  sản xuất.
- Hà và Mẹ có cùng khuôn mặt, tóc, tỷ lệ cơ thể và silhouette; chỉ khác màu áo. Không có dấu hiệu
  tuổi trưởng thành hoặc quan hệ mẹ–con.
- Ảnh Mẹ không khớp identity lock “tóc nâu gọn”, “ba lô màu đất”, “trẻ em năng động”; tóc hiển thị
  đen dài và không có ba lô. Gate hiện chỉ xác nhận file/hash, không xác nhận đặc điểm thị giác.

## Kế hoạch nâng chất lượng

### Sprint 1 — chặn false pass và lỗi vai trò (P0)

1. Thay lexical brief coverage bằng event graph: mỗi sự kiện bắt buộc có `setup → action → outcome`
   và locator ở các zone khác nhau; đoạn chép brief không được tính là triển khai.
2. Trích entity/role constraints từ brief. Với ca này: `Hà=10`, `Mẹ=adult,parent`, quan hệ mẹ–con,
   xưng hô phù hợp; từ chối character record mâu thuẫn.
3. Trích invariant/state bắt buộc: bão đang đến, nhà chưa an toàn, đồ giá trị cần di chuyển, gia đình
   sẽ sơ tán. Gate phải FAIL nếu invariant count bằng 0 cho brief có sự kiện/trạng thái rõ.
4. Tách `workflow_status`, `technical_status`, `editorial_status` và `release_status`; không đưa điểm
   preflight vào quality commitment như điểm biên tập.
5. Sửa telemetry deterministic bằng wall-clock thực và thống nhất ý nghĩa call/attempt count.

Tiêu chí nghiệm thu:

- Gói hiện tại FAIL vì `OFF_BRIEF_EVENT_CHAIN`, `ROLE_AGE_CONTRADICTION`,
  `RELATIONSHIP_DIALOGUE_MISMATCH` và `MISSING_REQUIRED_OUTCOMES`.
- Không có critic/human evidence thì editorial score là `null`, không phải 94.
- UI hiển thị “Workflow hoàn tất — nội dung bị chặn”, không chỉ `SUCCEEDED`.

### Sprint 2 — sửa generator và dựng lại câu chuyện (P1)

1. Lập outline mới hoàn toàn quanh đồng hồ đếm ngược trước bão: Hà cất giấy tờ/đồ kỷ niệm, cùng mẹ
   chằng cửa hoặc đưa vật nhẹ vào nhà, sợ tiếng gió, hoàn thành danh sách rồi sơ tán đúng lúc.
2. Cho Hà agency phù hợp tuổi: tự chọn một việc an toàn, báo mẹ khi nguy hiểm, không tự xử lý điện,
   mái nhà hay cửa kính trong bão.
3. Giữ xung đột tăng dần qua dấu hiệu cụ thể của thời tiết; climax là quyết định hoàn tất việc cuối
   cùng và rời nhà, ending xác nhận cả gia đình đến nơi trú an toàn.
4. Chọn audience canonical `7–10`; rút câu dài, bỏ khái quát giáo huấn và mọi chi tiết hội họa.
5. Đồng bộ environment với text và kiểm entity/location coverage ở từng scene.

Tiêu chí nghiệm thu:

- Ba cold reader đều trả lời đúng: Hà cần làm gì, điều gì khiến em sợ, mẹ giúp thế nào, gia đình có
  sơ tán an toàn hay không.
- 100% sự kiện bắt buộc có locator và quan hệ nhân quả; không xuất hiện hội họa/trường học nếu brief
  không yêu cầu.
- Human editorial score tối thiểu 80/100, không chiều nào dưới 3/5.

### Sprint 3 — tham chiếu nhân vật và visual gate (P1)

1. Sinh character sheet production riêng biệt: Hà 10 tuổi; Mẹ là người trưởng thành, khác chiều cao,
   vóc dáng, khuôn mặt, tóc và trang phục; thêm đạo cụ/bối cảnh ven biển phù hợp.
2. Kiểm visual traits bằng VLM hoặc human review; file tồn tại và hash đúng không được xem là identity
   PASS.
3. Cấm asset deterministic đi vào production và gắn nhãn fixture rõ trong UI/package.

Tiêu chí nghiệm thu:

- Reviewer phân biệt đúng Hà/Mẹ và quan hệ mẹ–con khi che tên.
- 100% trait bắt buộc được xác nhận; không asset fixture nào được dùng làm bằng chứng production.

### Sprint 4 — regression và hiệu chỉnh rubric (P2)

1. Giữ run này làm negative fixture `storm-brief-hijacked-by-art-template`.
2. Thêm adversarial cases: brief được chép nguyên văn ở opening nhưng phần còn lại thuộc domain khác;
   nhân vật quan hệ gia đình bị ép vào template bạn bè; ending chỉ tuyên bố hoàn thành mà không có hành
   động chứng minh.
3. Theo dõi false-pass precision/recall dựa trên nhãn người đọc; chỉ promote rubric khi blocker
   precision đạt ít nhất 95% và mọi lỗi P0 đã gắn nhãn đều bị bắt.

## Thứ tự xử lý đề xuất

Không sửa trực tiếp package hiện tại. Giữ nó làm regression fixture. Hoàn tất Sprint 1, sau đó tạo run
Stage 1 mới bằng generator đã sửa; chỉ chuyển Stage 2 khi Sprint 2 đạt cold-reader review và Sprint 3
có reference nhân vật production đã được duyệt.
