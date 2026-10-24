# Đánh giá và kế hoạch nâng chất lượng gói truyện

## Phạm vi và kết luận

- Gói nguồn mới nhất đã hoàn thành: `run-20260926100415-1ad1f2c1`, Stage 1, preset
  `quality`, model truyện/safety `qwen2.5-14b-q4km`.
- Lần dựng kế tiếp: `run-20260926104254-2f3dacf4`, Stage 2 local. Lần dựng này **thất
  bại**, không tạo `output/story.zip`; thư mục `work` chỉ là đầu ra trung gian.
- Baseline kiểm thử mã nguồn ngày 2026-09-26: `67 passed`.

**Không đạt điều kiện phát hành.** Stage 1 hợp lệ về schema và đủ đúng 3.000 từ nhưng chưa đạt
chất lượng biên tập. Stage 2 hết ba lượt thử ở `farewell.png` sau khi OCR phát hiện chữ giả `SSS`.
Các gate Stage 1 cùng `PASS` không chứng minh nội dung tốt: báo cáo tự ghi phương pháp là
`MVP_HEURISTIC_NOT_EDITORIAL_REVIEW`, còn `STORY_QUALITY_GATE` hiện chỉ kiểm đủ tám mục và không
có hai mục trùng nguyên văn.

## Đánh giá chi tiết

### Nội dung — không đạt

- Cả tám zone kết thúc bằng câu bị cắt, như `"dẫn đường cho chúng ta trong."`, `"để mọi
  người trong gia đình đều."` và `"Con sẽ viết."`. Pipeline cắt đúng số từ rồi tự thêm dấu chấm.
- Nội dung lặp mạnh ở cấp câu và ý: “tìm thấy niềm vui và hy vọng”, “mẹ sẽ luôn ở bên cạnh con”
  và hoạt động đọc sách lặp nhiều lần. Gate 8-gram không bắt được lặp diễn đạt hoặc lặp nội zone.
- Mạch truyện mâu thuẫn: outline yêu cầu thuyền không lành lại, nhưng OPENING cho Bo dùng băng
  dính và keo vá xong; các đoạn sau lại nói vết rách còn nguyên.
- Nhịp bị kéo dài để đạt 15 phút: DEVELOPMENT 750 từ, CLIMAX 600 từ, trong khi cốt truyện mỏng.
  GREETING/FAREWELL dài 120/150 từ, trái yêu cầu “ngắn”.
- Dải tuổi `3–18` quá rộng để kiểm từ vựng và nhịp. Giọng kể thiên về giải thích, giáo huấn và
  khái quát hơn là hành động cụ thể.
- Bo được mô tả là cậu bé nhưng ảnh tham chiếu là bé gái. Truyện có nhiều câu thoại nhưng báo cáo
  ghi `direct_dialogue_item_count=0`.
- Safety trả `PASS` đồng thời ghi `finding_count=2`; báo cáo không cho biết finding là cảnh báo hay
  lỗi đã xử lý.

### Hình ảnh — không đạt

- Bo sai giới tính trình bày. Prompt chỉ truyền tên, tuổi, vai trò và tính từ trừu tượng; không có
  giới tính trình bày, tóc, trang phục, màu sắc hoặc silhouette khóa cứng.
- Reference “mẹ của Bo” là character sheet cổ trang, có pseudo-text ở mép trái và không hợp bối
  cảnh hiện đại. Nhân vật 35 tuổi lại có `adult_visual_eligibility=NOT_ADULT`, cho thấy semantics
  của trường/chính sách đang sai.
- Cover che mắt nhân vật bằng dải chữ quá lớn và không có chiếc thuyền giấy.
- Climax/ending chủ yếu là chân dung một nhân vật trên nền mờ; thiếu mẹ, thuyền giấy, trang sách,
  căn phòng và hành động chính. Chất lượng bề mặt sạch nhưng story coverage thấp.
- Nhân vật/trang phục trôi giữa reference, cover, climax và ending. CLIP toàn ảnh không đủ xác nhận
  đúng danh tính, giới tính, tuổi, đạo cụ hoặc quan hệ nhân vật.
- OCR chặn đúng lỗi `farewell.png`, nhưng retry chỉ đổi seed, không đổi prompt theo nguyên nhân;
  sau ba lần thử toàn bộ Stage 2 bị bỏ dù tám ảnh đã được commit.

### Pipeline — cần cải thiện lớn

- `run.json` Stage 2 vẫn là `INITIALIZED` trong khi job đã `FAILED`; nguồn trạng thái không nhất quán.
- Progress khi thất bại vẫn là 20% dù đã tạo 8/10 ảnh và gọi diffusion 11 lần.
- Không có checkpoint/resume theo asset; chạy lại có nguy cơ dựng lại ảnh đã đạt.
- Visual moment chỉ lấy 240 ký tự đầu zone, thường là tóm tắt/lặp lại thay vì shot có chủ thể,
  hành động, đạo cụ và bối cảnh rõ.
- 67 test bảo vệ schema/workflow nhưng chưa có golden test cho biên tập, character attributes,
  story-to-image coverage, retry/resume và đồng bộ trạng thái.

## Kế hoạch nâng chất lượng

### P0 — tính đúng đắn và khả năng hoàn tất gói

**Trạng thái 2026-09-26: đã triển khai trong mã nguồn và có regression tests.** Stage 1 nay chốt
văn bản tại ranh giới câu với dung sai ±5%, có `SENTENCE_COMPLETENESS_GATE` và
`NARRATIVE_INVARIANT_GATE`. Workspace đồng bộ trạng thái chạy theo job/CLI. Stage 2 lưu checkpoint
từng asset, xác minh lại hash khi resume và retry trong web tiếp tục đúng workspace cũ. Việc chạy
lại một gói local mới để đánh giá chất lượng đầu ra thực tế vẫn là bước xác nhận vận hành tiếp theo.

1. Không cắt ở giữa câu. Sinh trong khoảng rồi co giãn theo ranh giới câu; duration gate dùng dung
   sai đề xuất ±5% thay vì bắt đúng tuyệt đối 3.000 từ.
2. Thêm sentence-completeness gate: bắt mệnh đề kết thúc bằng giới/liên từ, nháy chưa đóng và câu
   cuối quá ngắn; bỏ cách “sửa” bằng tự nối dấu chấm.
3. Lưu invariant từ brief/outline (`thuyền vẫn rách`) và kiểm state transition mỗi zone. Critic phải
   trả evidence; `NOT_REQUIRED` chỉ hợp lệ khi cả deterministic checks và critic đều sạch.
4. Đồng bộ `run.json` với job, tính progress theo asset/attempt và checkpoint từng asset. Retry OCR
   dùng remediation prompt/crop/inpaint; resume từ asset lỗi thay vì dựng lại.
5. UI ghi rõ “Stage 2 thất bại — 8/10 asset tạm” và vô hiệu hóa tải/phát hành partial work.

Tiêu chí nghiệm thu P0:

- 0/8 zone kết thúc bằng câu cụt hoặc nháy chưa đóng trên bộ regression.
- Mọi invariant trong brief nhất quán qua các zone.
- Run/job cùng trạng thái; resume không gọi provider cho asset đã commit và hash hợp lệ.
- Test OCR fail ở asset 9 chứng minh lần tiếp theo bắt đầu từ asset 9.

### P1A — chất lượng biên tập và bám brief

**Trạng thái 2026-09-26: đã triển khai trong mã nguồn và có regression tests.**
`STORY_QUALITY_GATE` nay dùng rubric deterministic 9 chiều, thang 100, ngưỡng 80 và lưu rationale
cùng evidence locator cho từng chiều. `SEMANTIC_REPETITION_GATE` so sánh câu liên zone bằng token
Jaccard/sequence similarity; `AGE_PROFILE_GATE` áp giới hạn câu cho `KIDS_7_10`; và
`DIALOGUE_STRUCTURE_GATE` thống kê lượt thoại, scene ratio, speaker candidate và attribution ratio.
Báo cáo/quality commitment lấy điểm thật từ các gate thay cho giá trị hard-code. Chạy lại các bộ
phân tích trên baseline lỗi cho kết quả: 6 cặp lặp nghĩa, age profile fail, 29 lượt thoại (không còn
báo 0) và editorial score 71/100 — dưới ngưỡng phát hành.

1. Dùng beat budget: GREETING/FAREWELL tối đa 30–50 từ; nếu brief mỏng thì đề xuất thời lượng ngắn
   hơn thay vì bơm chữ.
2. Rubric critic gồm hook, causality, state consistency, agency, dialogue, repetition, age-fit, tone
   và payoff; thang 0–100 có evidence locator, ngưỡng phát hành 80.
3. Phát hiện lặp nội/liên zone bằng sentence embedding + fuzzy matching, không chỉ overlap 8-gram.
4. Tách `editorial_status` khỏi technical status; heuristic không được cấp `EDITORIAL_PASS`.
5. Thu hẹp audience thành dải tuổi rõ, ví dụ 7–10, và kiểm từ vựng/độ dài câu theo profile.
6. Chuẩn hóa dialogue thành turn có speaker hoặc bổ sung quote/speaker parser thực.

Tiêu chí nghiệm thu P1A:

- Editorial score ≥80/100, không chiều nào dưới 3/5 và mọi điểm có locator.
- Greeting/farewell đúng brief; không thêm bài học khi brief cấm nhắc lại bài học.
- Cold-reader review xác nhận đúng diễn biến “thuyền không lành lại”.

### P1B — nhận dạng và kể chuyện bằng hình

**Trạng thái 2026-09-26: đã triển khai trong mã nguồn và có regression tests.** Character record
nay mang visual identity lock gồm presentation, tóc, trang phục, palette, silhouette và cultural
context; trạng thái người lớn được suy từ tuổi thay vì profile khán giả. Visual Plan 1.2 chứa shot
spec cấu trúc cho từng asset với subject/action/emotion/prop/location/time, required/forbidden
elements và composition. Local QA ghi structured element checks, dùng identity reference cho nhân
vật, CLIP probe cho đạo cụ, OCR cho chữ cấm và đánh dấu rõ các mục cần VLM. Cover typography được
thu nhỏ vào vùng 3–19% chiều cao. Visual review gồm toàn bộ character sheet cùng cover, climax và
ending; khi operator xác nhận, Stage 4 tạo `visual_review.json` ràng buộc hash của từng ảnh.

**Bổ sung Giai đoạn 3 (2026-09-29):** Visual Bible 2.2 khóa character master theo view
`full_body_front`, `face_closeup`, `three_quarter`, outfit và palette. Shot spec khóa tọa độ chuẩn hóa,
scale, pose, gaze của từng subject cùng vị trí/trạng thái đạo cụ. Reference conditioning chỉ nhận nhân
vật có trong cảnh, gắn `character_id`/`view_id`, và dùng cast sheet lưới cố định khi một IP-Adapter
phải nhận nhiều ảnh. Runtime có contract ControlNet theo capability với thứ tự ưu tiên depth,
openpose, canny, segmentation; khi không có control map, prompt dùng coordinate layout làm fallback.

**Bổ sung Giai đoạn 4 (2026-09-29):** portrait không còn crop landscape trực tiếp. Profile có
outpainting dựng canvas 9:16, đặt dải ảnh nguồn theo focal point của subject, khóa dải nguồn bằng
mask feather và chỉ tái tạo phần mở rộng. Profile không có outpainting dùng recompose canvas với nền
mở rộng rồi img2img. Cover đẩy focal point xuống dưới để giữ title-safe area; character master của
đúng nhân vật trong cảnh được dùng làm identity reference khi pipeline outpaint hỗ trợ IP-Adapter.
Mỗi portrait lưu `portrait_transform` evidence gồm mode, source region, focal point và mask feather.

**Bổ sung Giai đoạn 5 (2026-09-29):** output Diffusers ở work resolution đi qua
`stabilityai/sd-x2-latent-upscaler` trước khi resize phần tỷ lệ dư về kích thước canonical. Hậu kỳ chỉ
dùng unsharp mask, contrast và color adjustment biên độ nhỏ để tránh đổi identity hoặc tạo halo mạnh.
Model upscaler tham gia `prepare-image-models` và cache readiness. Mỗi character, landscape và
portrait lưu `upscale_postprocess` evidence với model ID, source/learned/output sizes, residual resize
và toàn bộ tham số hậu kỳ. Nếu upscaler bị tắt có chủ ý, evidence ghi `LANCZOS_FALLBACK`; lỗi tải hoặc
inference của learned upscaler không bị âm thầm hạ cấp.

**Bổ sung Giai đoạn 6 (2026-09-29):** image QA phát hành evidence theo tầng `TECHNICAL`,
`OCR_SAFETY`, `SEMANTIC`, `PARITY`, `IDENTITY`, `COMPOSITION_ELEMENTS` và
`CHARACTER_IDENTITY`. Failure không còn chỉ là exception text mà mang defect code, layer, score và
threshold. Repair planner ánh xạ defect sang `REGENERATE`, `RECOMPOSE` hoặc `ABORT`, tạo prompt
correction, negative-prompt additions và điều chỉnh denoise strength. Parity/identity repair giảm
strength để giữ nguồn; lỗi chữ siết negative prompt; assessor thiếu dừng sớm thay vì retry vô ích.
Mọi failed attempt và repair plan được lưu trong `repair_history`; candidate thành công ghi
`repair_plan_applied`, giúp audit quá trình hội tụ của best-of-N.

**Bổ sung Giai đoạn 7 (2026-09-29):** GPT Image Web Assist là cầu nối thủ công tùy chọn, không dùng
API, cookie hoặc automation đăng nhập. Stage 2 package xuất prompt, current landscape và role-bound
character references trong bundle khóa bằng source-package digest và manifest digest. Kết quả chỉ
được import khi người vận hành xác nhận review, tên file canonical, PNG đúng 3840×2160 và đạt QA kỹ
thuật. Import tạo same-stage `REPAIR`, cập nhật image hash, Visual Plan/Bible digest và provenance
`MANUAL_OPTIONAL_NO_API`; pipeline local không thay đổi nếu người dùng bỏ qua bước assist.

**Bổ sung Giai đoạn 8 (2026-09-29):** image benchmark có promotion evaluator riêng, so candidate với
baseline trên đủ golden set và bắt buộc human-review agreement. Gate bao gồm required-element recall,
identity, landscape/portrait parity, semantic non-regression, layered-QA failures, upscale fallback,
OCR, unmeasured elements, visual blocker, latency và peak VRAM. Chỉ report có verdict `PROMOTE`, mọi
check PASS và digest hợp lệ mới thỏa `IMAGE_BENCHMARK_PROMOTION` ở production release. Release gate
còn kiểm layered QA, learned-upscale provenance, repair audit và Web Assist disclosure. Dashboard
Stage 2–4 hiển thị QA layer, repair, learned upscale, Web Assist và snapshot release gates.

1. Mở rộng character schema bằng `presentation`, khuôn mặt/tóc, trang phục, palette, silhouette và
   bối cảnh văn hóa; không suy giới tính từ tên. Sửa nghĩa của `adult_visual_eligibility`.
2. Character sheet dùng layout có kiểm soát/hậu kỳ, cấm chữ từ diffusion, và duyệt đúng tuổi,
   presentation, trang phục, số người và pseudo-text.
3. Mỗi zone có shot spec: subject, action, emotion, prop, location, time, required/forbidden elements.
   Prompt ảnh dùng shot spec, không dùng 240 ký tự văn xuôi đầu zone.
4. Cover có safe area, không che mắt/mặt; required element gồm Bo và paper boat.
5. Dùng detector/VLM output cấu trúc để chấm presence. CLIP là tín hiệu phụ; face/identity embedding
   được đo theo từng nhân vật.
6. Bắt buộc visual review với character sheet, cover, climax và ending trước Stage 3.

Tiêu chí nghiệm thu P1B:

- 100% required elements của bốn ảnh duyệt mẫu; 0 chữ ngoài vùng typography.
- Bo đúng presentation/age trên mọi cảnh; mẹ không thành nhân vật cổ trang trong bối cảnh hiện đại.
- Cover không che facial landmarks, tiêu đề trong safe area, motif thuyền giấy dễ nhận biết.
- Climax có tối thiểu Bo + mẹ + thuyền rách + trang sách/dòng sông tưởng tượng.

### P2 — benchmark và quản trị chất lượng

**Trạng thái 2026-09-26: đã triển khai nền tảng corpus, KPI và release gate trong mã nguồn.**
Benchmark v2 có 24 brief phủ đủ ba profile, brief mỏng, cấm bài học, invariant/state âm, hội thoại,
nhiều nhân vật và bối cảnh Việt Nam; mỗi ca có expected outcome, required elements và forbidden
outcomes. Bộ tổng hợp benchmark tính completion/blocker/P0 defect, mean và median editorial,
consistency, required-element recall, retry/asset, thời gian và peak memory. Promotion là fail-closed:
completion phải đạt 100%, P0 defect bằng 0, editorial tăng thực sự, còn consistency, recall và retry
không được xấu hơn baseline. Manifest nay lưu operational metrics cùng lineage từng stage.

Production release kiểm từng bằng chứng độc lập: editorial threshold, structured visual QA cho cả hai
orientation, độ phủ human visual review, provenance/telemetry, benchmark promotion, local provider,
production image assessment và external audit. Thiếu bất kỳ bằng chứng bắt buộc nào đều trả
`BLOCKED`; development vẫn tạo bundle nhưng công khai các check chưa đạt.

1. Tạo corpus 20–30 brief đại diện, gồm brief mỏng, cấm bài học, invariant phủ định, nhiều nhân vật
   và bối cảnh Việt Nam; lưu human labels cho nội dung/hình.
2. Theo dõi completion rate, retry/asset, sentence defect, invariant violation, editorial score,
   required-element recall, identity consistency, thời gian và VRAM.
3. So sánh preset/model/prompt bằng cùng brief/seed. Chỉ promote khi completion không giảm, P0 defect
   bằng 0 và median editorial/visual score tăng.
4. Production cần package hoàn chỉnh + technical pass + editorial pass + visual-review pass +
   provenance; thiếu một phần phải là `BLOCKED`, không phải `ASSESSED_PASS`.

Tiêu chí nghiệm thu P2:

- Corpus có ít nhất 20 case ID duy nhất, đủ ba profile và có cả negative cases.
- Mọi kết quả benchmark thiếu evidence bị từ chối; promotion không thể bỏ qua P0/recall/retry.
- Manifest có runtime và operational lineage; production thiếu lineage hoặc benchmark v2 bị chặn.
- Human review phải bao phủ toàn bộ sample ID; structured QA `PARTIALLY_ASSESSED` không đủ production.

## Thứ tự triển khai

1. Sprint 1: P0 và regression tests — tạo được gói hoàn chỉnh, resume được, không còn câu cụt.
2. Sprint 2: rubric biên tập, invariant/state model, repetition và audience profile.
3. Sprint 3: character schema, shot spec, structured visual QA và visual review.
4. Sprint 4: corpus benchmark, dashboard và release policy.

Không tiếp tục Stage 3/4 từ run hiện tại. Sau Sprint 1 cần chạy lại từ Stage 1 vì lỗi cắt câu và mâu
thuẫn nằm trong gói nguồn; chỉ chạy lại Stage 2 sẽ giữ nguyên nội dung hỏng.
