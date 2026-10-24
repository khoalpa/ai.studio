# Kế hoạch nâng cao chất lượng tạo truyện

## Trạng thái triển khai ngày 2026-09-27

Lát cắt P0 đầu tiên đã hoàn tất:

- Stage 1 tạo và đóng gói `story_contract.json`; artifact này được giữ xuyên Stage 2–4.
- Stage 1 tạo `outline_evidence.json`, liên kết requirement với zone và anchor trong dàn ý; requirement
  không được outline triển khai sẽ bị chặn trước khi viết tiếp.
- Stage 1 tạo `quality_decision.json`, tách riêng workflow, kỹ thuật, an toàn, biên tập, release và
  quyền chuyển stage; mỗi lý do chặn dẫn về gate/evidence tương ứng.
- `STORY_CONTRACT_GATE` kiểm entity, tuổi/vai trò, quan hệ, chuỗi sự kiện bắt buộc và tuyên bố hoàn
  thành thiếu bằng chứng.
- Run lỗi `run-20260927033250-8dceca4a` nay bị bắt bởi sai tuổi của Mẹ, hai action lệch brief, sai
  xưng hô/quan hệ và completion claim không có diễn biến chứng minh.
- Deterministic generator có nhánh chống bão riêng, tạo đúng chuỗi chuẩn bị nhà, di chuyển vật dụng,
  nhờ người lớn và sơ tán; Mẹ được mô hình hóa là người trưởng thành.
- Corpus có thêm negative case `youth-negative-storm-template-hijack`.
- Contract đã bao phủ thêm tình huống chim non bị lạc trước mưa: bắt buộc nhờ người lớn và cấm trẻ
  tự trèo cây trong mưa.
- Điểm heuristic được xuất dưới tên `preflight_story_quality_score`. Khi không có critic evidence,
  `final_story_quality_score` và quality commitment là `null`, còn package mang trạng thái
  `NOT_ASSESSED` và không được chuyển stage.
- UI coi mọi trạng thái chất lượng khác `PASS` là chưa đủ điều kiện.
- Package verifier bắt buộc ba sidecar chất lượng, kiểm digest giữa contract–outline, digest của quyết
  định và sự thống nhất `artifact_class`; UI hiển thị riêng từng lớp trạng thái.
- Refinement report lưu defect map ban đầu, digest trước/sau, lịch sử từng vòng sửa và closure record
  `OPEN`/`CLOSED`; UI hiển thị số lỗi đã đóng và còn mở.
- Audience `YOUTH_SAFE` đã được chuẩn hóa thành `7–10` trong generator, registry, prompt safety và UI;
  `AGE_PROFILE_GATE` chặn metadata không khớp rubric. Generator deterministic dùng xưng hô mẹ–con
  khi quan hệ phụ huynh xuất hiện trong brief.
- Telemetry Stage 1 nay ghi wall-clock thực cho mọi provider mode. Deterministic fixture có số
  call/attempt theo thao tác logic thay vì toàn số 0; local runtime vẫn giữ provider duration riêng,
  đồng thời dùng wall-clock thống nhất cho operational duration.
- Benchmark summary đã có median, p10/p90 cho điểm biên tập và latency, cùng bảng lỗi theo taxonomy.
  Record tự lấy latency và peak memory từ manifest. Lệnh `summarize-benchmark` tạo baseline có digest
  ổn định và từ chối ghi đè file cũ; promotion evaluator đọc trực tiếp định dạng report này và chặn
  report bị sửa sau khi tạo.
- Benchmark report có Wilson 95% confidence interval cho completion, expected outcome, assessed
  editorial, advancement, blocker và required-element recall. Promotion policy hiện yêu cầu tăng ít
  nhất 2 điểm biên tập, tổng latency không quá 115% baseline và peak memory không quá 110%; các ngưỡng
  nằm trong `spec/benchmark.json` và được ghi lại trong evidence đã ký digest.
- Corpus canonical đã nâng lên `canonical-story-quality-v4`. `corpus_digest_sha256` bao phủ schema,
  metric list, promotion policy, brief, seed và toàn bộ labels; baseline và promotion evidence đều
  mang digest này. Sửa nội dung corpus nhưng giữ nguyên case ID/seed vẫn bị release gate phát hiện.
- Benchmark record đọc trực tiếp `story_contract.json`, `outline_evidence.json` và
  `quality_decision.json`. Outcome compliance nay yêu cầu contract gate đạt, mọi requirement có
  script evidence và outline binding; lexical required-element match chỉ còn là chỉ số phụ.
  `contract_requirement_recall` được báo cáo riêng và phải đạt 100% để promotion canonical hợp lệ.
- `summarize-benchmark` nay fail-closed trước khi tạo baseline: bắt buộc đúng toàn bộ case ID, không
  trùng hoặc thừa case, seed khớp canonical plan và từng record mang đúng corpus digest. Baseline
  không đầy đủ không còn được ghi xuống đĩa rồi chờ release gate phát hiện muộn.
- Lệnh `record-benchmark-case` tạo evidence immutable cho từng Stage 1 package và chặn package sai
  stage, profile, language hoặc seed. `summarize-benchmark` nhận trực tiếp thư mục record JSON, giúp
  quy trình case → evidence → baseline chạy bằng CLI mà không cần ghép JSON thủ công.
- Lệnh `generate-benchmark-case` tạo run trực tiếp từ canonical case và đóng `benchmark_context` vào
  manifest, gồm case ID, seed, corpus digest và cách seed được áp dụng. Local text/safety runtime nhận
  seed qua generation parameters; record evidence từ package không tự chứng minh context này sẽ bị
  từ chối.
- Canonical plan đã khóa golden set 8 case. Schema `human_story_review` và lệnh
  `evaluate-human-reviews` kiểm hai reviewer độc lập, đủ case, blocker decision hợp lệ, tính Cohen's
  kappa với ngưỡng 0,70 và ghi report immutable có digest. Đây là hạ tầng sẵn sàng; chưa có dữ liệu
  review thật của hai người nên điều kiện agreement của Giai đoạn 0 chưa được tuyên bố hoàn tất.
- Lệnh `create-human-review-template` tạo phiếu chấm từ record canonical và bind từng case với đúng
  package digest. Evaluator chặn hai reviewer chấm khác phiên bản package. Rubric reviewer có ví dụ
  PASS/BLOCK, quy tắc độc lập và quy trình hòa giải tại `docs/human-story-review-rubric.md`.
- API validation summary và màn Kiểm định hiển thị coverage của từng brief requirement: trạng thái
  `SATISFIED`, `SCRIPT_MISSING`, `OUTLINE_UNBOUND` hoặc `MISSING`, cùng outline zone và script locator.
  Người vận hành không còn phải suy requirement thiếu chỉ từ tên gate tổng quát.
- Mỗi Stage 1 run ghi event `STAGE1_TELEMETRY_RECONCILED` và lưu reconciliation trong `run.json`, so
  sánh wall-clock toàn job với thời gian manifest, tính deviation và đánh dấu PASS/FAIL ở ngưỡng 5%.
  Test end-to-end bắt buộc reconciliation PASS; theo dõi dài hạn vẫn cần dữ liệu từ benchmark full.
- UI tab Kỹ thuật hiển thị trạng thái reconciliation, độ lệch và hai mốc wall-clock. Run có telemetry
  vượt 5% được chuyển sang `NEEDS_ATTENTION` và hiện banner cảnh báo, thay vì vẫn trình bày như một
  lần chạy hoàn toàn bình thường.
- Golden set có machine annotation cho đủ 8/8 case, gồm severity, expected decision,
  required/forbidden events, role, relationship và state transition; plan validator fail-closed nếu
  annotation thiếu hoặc sai kiểu. Ca chống bão được sửa kỳ vọng thành `PASS`: brief này hợp lệ và mục
  tiêu regression là buộc generator bám chuỗi sơ tán, không phải từ chối brief.
- Lệnh `run-benchmark-suite` đã khép kín luồng tạo package, ghi evidence và khóa baseline canonical
  trong một lần chạy. Lệnh hỗ trợ resume sau gián đoạn, xác minh lại seed/corpus digest của record cũ
  và không ghi đè baseline đã hoàn tất. Baseline deterministic đầu tiên đã chạy đủ 27/27 case tại
  `artifacts/benchmarks/baseline-v4-deterministic`: completion 100%, expected outcome 22,22%, required
  element recall 94,12%, contract requirement recall 71,43%, blocker rate 40,74% và assessed editorial
  0%. Điểm editorial được giữ `null`, đúng với việc chưa có critic hoặc human evidence.
- Baseline deterministic v2 đã sửa cách đo expected outcome: content acceptance được đánh giá độc lập
  với quyền chuyển stage, vì fixture luôn bị chặn phát hành theo thiết kế. Expected outcome tăng từ
  22,22% lên 55,56%, còn advancement vẫn 0% và editorial vẫn `null`. Record nay tách rõ
  `content_accepted`, `expected_decision`, `preflight_story_quality_score` và `editorial_score`.
  Promotion evaluator trả `HOLD` khi thiếu điểm editorial thay vì lỗi số học. Detector câu tiếng Việt
  cũng nhận đúng cụm kết thúc “công bằng”, loại false positive từng làm hỏng năm case adult; smoke test
  `adult-central-storm` hiện không còn blocker và đạt expected outcome.
- `BRIEF_POLICY_GATE` nay chặn ngay tại `request.brief` các yêu cầu bạo lực đồ họa giữa trẻ em, chọn
  hung thủ không có manh mối, làm tang vật đổi trạng thái không lời giải, hồi sinh nhân vật không giải
  thích và cố ý bỏ dấu người nói trong đối thoại nhiều nhân vật. Evidence ghi disposition `REJECT` hoặc
  `REPAIR_BRIEF`. Baseline v3 đã đo ba intent đầu trên đủ 27 case: expected outcome tăng từ 55,56% lên
  74,07% và blocker rate giảm từ 40,74% xuống 25,93%. Hai intent sau đã có test hồi quy nhưng chưa được
  tính vào baseline v3; chúng sẽ xuất hiện trong lần chạy full tiếp theo.
- Baseline v4 đã tính đủ năm brief policy, sửa grounding cho brief 1–3 từ và chuẩn hóa xưng hô mẹ–con:
  expected outcome đạt 96,30%, required-element recall 100% và chỉ còn case chim non chưa đạt. Nhánh
  `LOST_BIRD_RETURN` sau đó đã được triển khai với outline và event chain phát hiện chim lạc → nhờ
  người lớn → đưa chim về tổ; smoke benchmark đạt contract 3/3, outline binding 3/3, preflight 91 và
  không còn blocker. Contract thuyền rách cũng đã được nâng thành bốn requirement theo zone, nên việc
  chép toàn bộ brief vào opening không còn tạo false pass. Chưa tuyên bố full-corpus 100% cho đến lần
  chạy canonical tiếp theo.
- Nhánh `TORN_BOAT_GRIEF` nay sinh outline, dialogue và prose theo bốn requirement có zone binding,
  dùng filler cùng domain thay cho template hội họa. Negative fragment được chặn bởi
  `DELIBERATE_FRAGMENT_STYLE_REQUEST` và không còn bị lặp cụm “câu cụt” vào output. Baseline canonical
  v6 đã khóa đủ 27/27 case với completion 100%, expected outcome 100%, forbidden outcome 0%,
  required-element recall 100%, contract-requirement recall 100% và P0 defect 0. Đây là baseline máy
  đo/fixture; assessed editorial và advancement vẫn 0%, `editorial_score` vẫn `null`, nên chưa thay thế
  model critic hoặc human review.
- Hai template review độc lập đã được tạo từ đúng tám package golden của baseline v6, khóa theo package
  digest tại `artifacts/benchmarks/baseline-v4-deterministic-v6/reviews`. Chúng vẫn mang trạng thái
  `UNREVIEWED`; hệ thống không tự điền quyết định thay người chấm. Smoke `text_local` với Qwen2.5 14B
  chạy fail-closed sau khoảng 26 phút: model critic có evidence nhưng output còn 29 ký tự Hán, outline
  không bind bốn storm requirement và preflight chỉ đạt 78. Repair làm blocker tăng từ 3 lên 5 nên
  pipeline giữ bản trước rồi dừng. Vì vậy chưa chạy full local corpus.
- Lát cắt sửa lỗi local đầu tiên đã hoàn tất. Planner có language lock rõ ràng; outline được gắn đủ
  contract anchor vào zone hợp lệ bằng xử lý xác định, không gọi thêm model. Pipeline nay dọn lỗi ngôn
  ngữ và câu chưa hoàn chỉnh trước vòng repair lớn, kể cả khi đồng thời còn blocker contract hoặc chất
  lượng; chỉ nhận candidate khi số blocker bề mặt giảm và tổng blocker không tăng. Lần smoke local tiếp
  theo vẫn cần xác nhận hiệu quả thực tế trước khi mở rộng ra toàn corpus.
- Smoke `text_local` v2 xác nhận hai mục tiêu chính: `STORY_CONTRACT_GATE` đã PASS ngay từ bản đầu và
  pre-repair cleanup xóa 111 ký tự Hán cùng lỗi câu, giảm blocker từ 4 xuống 2. Run vẫn fail-closed do
  cleanup làm số từ tăng từ 659 lên 697, vượt trần 682, và model critic còn hai finding; generic repair
  làm blocker tăng từ 2 lên 3 nên bản trước được giữ lại. Runtime thực hiện 44 event model, gồm một lỗi
  retryable đã phục hồi. Sau kết quả này, cleanup đã được giới hạn theo số từ gốc, tự cân lại duration;
  prompt zone cũng buộc hiện thực hóa contract anchor và agency rõ trong development/climax. Cần chạy
  smoke v3 trước khi xem xét full local corpus.
- Smoke `text_local` v3 loại được `WORD_DURATION_GATE` và `STORY_QUALITY_GATE`; repair vòng đầu giảm
  blocker từ 6 xuống 4. Tuy nhiên, hai zone repair còn 106 ký tự Hán và làm rơi outcome sơ tán, nên run
  vẫn fail-closed với bốn blocker bề mặt/contract. Run phát sinh 72 event model, trong đó bốn lỗi
  retryable đều phục hồi. Cleanup nay chấm điểm từng candidate bằng detector xác định, thử tối đa hai
  lần mỗi zone và chỉ nhận bản tốt hơn. Targeted rewrite cũng có bước khôi phục requirement domain-
  specific bị rơi vào zone hợp lệ mà không gọi thêm model. Smoke v4 là cổng kế tiếp trước full local.
- Smoke `text_local` v4 đã đạt 0 blocker nội dung: pre-repair cleanup giảm blocker 4→3 và xóa toàn bộ
  surface blocker; repair vòng 2 giảm 3→0. Benchmark evidence đạt required element 6/6, contract 4/4,
  outline binding 4/4, forbidden outcome 0, preflight 82 và `outcome_compliant=true`. Run gốc dừng ở
  bước đóng gói vì `work/repairs` chưa có artifact owner, không phải vì gate chất lượng. Repair snapshot
  nay được ghi vào `logs/repairs`, ngoài package source; work product v4 sau khi tách diagnostic đã đóng
  thành package 8 artifact, reopen verifier PASS và tạo benchmark record digest hợp lệ. Cần một smoke
  end-to-end sạch sau bản sửa ownership trước khi bắt đầu full local corpus.
- Smoke `text_local` v5 đã hoàn tất end-to-end qua CLI với trạng thái run `SUCCEEDED`, package Stage 1
  gồm 8 artifact và verifier PASS. Benchmark record đạt 0 blocker/P0, required element 6/6, contract
  requirement 4/4, outline binding 4/4, forbidden outcome 0, preflight 93 và
  `outcome_compliant=true`. Run dùng hai vòng repair, không có retry; telemetry reconciliation PASS với
  độ lệch 0,0037%. Sáu repair snapshot nằm tại `logs/repairs`, không xuất hiện trong package source.
  Lát cắt chống bão local đã qua cổng smoke; bước tiếp theo là canary nhiều scenario trước khi cân nhắc
  full local corpus 27 case.
- Canary local đầu tiên ngoài kịch bản chống bão đã chạy case chim non. Pre-repair cleanup giảm blocker
  7→6, repair vòng đầu giảm 6→2; run dừng fail-closed ở dialogue attribution và hai chiều craft
  opening-hook/agency. Diagnostic đồng thời phát hiện false negative quan trọng: câu “Mẹ trèo lên cây,
  Phương và An theo sau” chưa bị contract gate xem là trẻ trèo cây. Detector nay chặn trẻ xuất hiện
  trong climbing context; hậu xử lý gắn người nói cho thoại, củng cố hook/agency và loại chuỗi rescue
  phụ kiểu “bỗng có tiếng kêu cứu”. Canary chim non cần chạy lại trước khi chuyển sang scenario thuyền
  rách.
- Canary chim non v2 xác nhận contract, safety, dialogue attribution, opening hook, agency và surface
  đều đã qua; repair vòng đầu giảm blocker 4→1. Run chỉ còn `WORD_DURATION_GATE` vì đạt 615 từ, thiếu
  ba từ so với sàn 618. Vòng repair model tiếp theo làm blocker tăng nên bị loại đúng policy. Bộ cân
  bằng duration nay bù underfill nhỏ bằng câu hoàn chỉnh, xác định trong FALLING và không gọi model.
  Cần chạy lại chim non lần cuối để xác nhận package end-to-end trước khi chuyển sang thuyền rách.
- Canary chim non v3 đã chạy end-to-end, tạo package hợp lệ và verifier PASS; contract 3/3, outline
  binding 3/3, 0 blocker/P0, forbidden outcome 0 và preflight 90. Tuy vậy, benchmark chưa chấp nhận
  vì chỉ khớp 4/5 required element: bản kể có Phương và An nhưng làm rơi cụm quan hệ “hai chị em”.
  Việc đọc lại output còn phát hiện câu “Mẹ đỡ Phương và An lên cây” lọt qua detector cùng tình tiết
  sóc xuất hiện bất ngờ ở ending. Hậu xử lý nay giữ rõ cụm “hai chị em”, thay mọi câu có tên trẻ trong
  climbing context bằng hành động đứng dưới an toàn, loại subplot động vật bất ngờ; contract gate cũng
  chặn cả cụm tổng quát “lên cây”. Run này còn lộ timeout suy diễn 2.078 giây cho request 8.192 token,
  khiến một attempt treo gần 78 phút. Runtime đã có trần cứng 600 giây cho generation timeout. Cần
  chạy canary v4 để xác nhận toàn bộ thay đổi trên model thật trước khi chuyển sang thuyền rách.
- Canary v4 xác nhận contract, safety và quality nhưng fail-closed do sáu ký tự Hán xen tiếng Việt và
  một câu có khoảng trắng sai trước ngoặc kép. Bộ cleanup xác định nay loại token trộn chữ Hán, đổi dấu
  câu CJK và chuẩn hóa kết câu trước khi gọi model. Canary v5 chứng minh cleanup giảm blocker 5→1 và
  xóa surface blocker 2→0; blocker còn lại là `character_agency=55`, dưới ngưỡng 60. Craft stabilizer
  vì vậy được đồng bộ với rubric để bảo đảm ít nhất hai tín hiệu quyết định/hành động.
- Canary chim non v6 đã hoàn tất end-to-end ngay bản đầu, không repair và không retry. Package Stage 1
  có 9 artifact, verifier PASS, `outcome_compliant=true`, required element 5/5, contract 3/3, outline
  binding 3/3, forbidden outcome 0, blocker/P0 bằng 0 và preflight 91. Digest package là
  `e9320ae21cce9e46fb88ef80ac33f14e274bf5b5a27b56afd9dbee520b7c40ec`. Canary kịch bản chim non
  đã qua cổng; bước kế tiếp là canary local cho nhánh `TORN_BOAT_GRIEF`.

Kiểm chứng gần nhất: **143/143 test đạt** sau khi cập nhật contract, outline evidence, quality decision,
defect closure, audience consistency, telemetry, baseline reporting và promotion budget xuyên
Stage 1–4; JavaScript giao diện cũng vượt `node --check`.

## 1. Mục tiêu

Trong 8 tuần, đưa hệ thống từ trạng thái “tạo được package hợp lệ” sang trạng thái “tạo được truyện
bám brief, nhất quán và có bằng chứng chất lượng đủ tin cậy để quyết định chuyển stage”. Trọng tâm là
Stage 1; chất lượng hình ảnh chỉ được mở rộng sau khi nội dung đã vượt cổng biên tập.

Mục tiêu đo được:

- 100% lỗi P0 đã gắn nhãn trong corpus bị chặn hoặc sửa trước khi đóng gói.
- Tỷ lệ truyện bám đúng các sự kiện bắt buộc đạt ít nhất 95% trên corpus canonical.
- Tỷ lệ vi phạm vai trò, tuổi, quan hệ và trạng thái nhân vật bằng 0.
- 100% truyện production có đánh giá critic hoặc human hợp lệ; preflight không được mang nhãn biên tập.
- Median điểm biên tập của bản candidate tăng tối thiểu 10 điểm so với baseline trên cùng case/seed;
  không chiều nào dưới 3/5.
- Không giảm completion rate, safety pass rate hoặc tính toàn vẹn package.

## 2. Hiện trạng

Nền tảng kỹ thuật tương đối tốt: package có hash binding và reopen verification; Stage 1 đã có gate
cho độ dài, câu hoàn chỉnh, lặp, age profile, thoại, safety và rubric chín chiều; benchmark canonical
có 27 case; bộ test hiện tại đạt **137/137** khi chạy với `PYTHONPATH=src`.

Khoảng trống lớn nhất nằm ở độ tin cậy của phép đo:

- Brief adherence chủ yếu dựa vào lexical coverage nên có thể đạt điểm cao bằng cách chép brief ở
  opening, dù phần còn lại kể một câu chuyện khác.
- Invariant extraction có thể trả về tập rỗng cho brief giàu sự kiện; trường hợp này vẫn PASS.
- Role và relationship không được ràng buộc đủ mạnh. Ví dụ gần nhất biến “Mẹ” thành bạn học 10 tuổi.
- Rubric deterministic đang chấm tín hiệu bề mặt như tên nhân vật, từ cảm xúc, connector và môi trường;
  các tín hiệu này không chứng minh quan hệ nhân quả hoặc payoff.
- `quality_score` vẫn có thể chứa điểm preflight cao trong khi `editorial_status` là chưa đánh giá.
- Provider deterministic hữu ích cho workflow test nhưng template của nó có thể làm sai domain truyện;
  asset fixture cũng chưa được tách tuyệt đối khỏi đường production.

Vì vậy, dự án chưa cần thêm nhiều gate rời rạc. Dự án cần một mô hình bằng chứng thống nhất từ brief
đến outline, script, đánh giá và quyết định chuyển stage.

## 3. Kiến trúc chất lượng đích

Luồng Stage 1 nên có sáu bước rõ ràng:

1. **Chuẩn hóa brief:** xác định audience, thời lượng, entity, role, relationship, required event,
   forbidden outcome, state invariant và yêu cầu an toàn.
2. **Story contract:** tạo một hợp đồng máy đọc được trước khi viết, gồm event graph, character bible,
   state graph và acceptance criteria. Người dùng hoặc hệ thống xác nhận các suy luận có độ tin cậy thấp.
3. **Outline có bằng chứng:** mỗi beat tham chiếu event/state mà nó triển khai; không beat nào tồn tại chỉ
   để bơm đủ số từ.
4. **Sinh script:** generator nhận story contract, outline, budget từng zone và lịch sử trạng thái thay
   vì chỉ nhận brief thô.
5. **Critique và repair có mục tiêu:** critic trả defect code, severity, locator, expected correction;
   repair chỉ sửa vùng liên quan rồi chạy lại toàn bộ invariant.
6. **Release decision:** tách biệt technical, safety, editorial và production readiness; thiếu bằng
   chứng ở lớp nào thì lớp đó là `NOT_ASSESSED` hoặc `BLOCKED`, không suy diễn từ lớp khác.

Artifact mới đề xuất:

- `story_contract.json`: entity, relationship, event graph, state graph, audience và constraints.
- `outline_evidence.json`: ánh xạ beat sang requirement và state transition.
- `editorial_assessment.json`: rubric, locator, critic provenance và defect closure.
- `quality_decision.json`: bốn trạng thái độc lập và lý do chặn.

## 4. Chương trình triển khai

### Giai đoạn 0 — khóa baseline và dữ liệu đánh giá (Tuần 1)

Mục tiêu là tạo thước đo đáng tin trước khi thay generator.

- Đóng băng corpus v4 và bổ sung case “brief chống bão bị template hội họa chiếm chỗ”.
- Với mỗi case, gắn nhãn required events, forbidden events, role/relationship, initial/final state,
  audience và severity của lỗi.
- Chọn 8–10 case đại diện làm golden set; mỗi case có ít nhất hai đánh giá độc lập và quy tắc hòa giải.
- Chạy baseline trên cùng model, preset và seed; lưu output, metric, latency và manual score.
- Tách bộ test thành unit, contract, regression, benchmark smoke và benchmark full.

Đầu ra:

- Corpus v4 có version và digest.
- Baseline report có median, p10/p90 và lỗi theo taxonomy.
- Rubric hướng dẫn người chấm với ví dụ PASS/FAIL.

Điều kiện hoàn tất:

- 100% case có machine labels hợp lệ.
- Agreement giữa người chấm đạt Cohen's kappa từ 0,70 trở lên trên các blocker.
- Baseline có thể tái lập bằng một lệnh và không ghi đè kết quả cũ.

### Giai đoạn 1 — story contract và gate P0 (Tuần 2–3)

Mục tiêu là chặn truyện sai domain, sai vai trò và thiếu kết quả bắt buộc.

- Thêm schema cho entity, role, relationship, event và state transition.
- Xây extractor hai lớp: deterministic cho tuổi/quan hệ rõ; model-assisted cho event/state, kèm confidence
  và evidence span. Không cho phép tập invariant rỗng nếu brief có động từ mục tiêu hoặc trạng thái.
- Thay lexical adherence bằng event coverage. Một event chỉ đạt khi có setup, action/consequence và
  outcome ở các locator hợp lệ; đoạn chép brief không tính là action.
- Thêm các blocker: `OFF_BRIEF_EVENT_CHAIN`, `ROLE_AGE_CONTRADICTION`,
  `RELATIONSHIP_DIALOGUE_MISMATCH`, `MISSING_REQUIRED_OUTCOME`, `UNSUPPORTED_COMPLETION_CLAIM`.
- Buộc outline khai báo requirement ID và transition ID cho từng beat.

Vùng mã dự kiến:

- `schemas/story.schema.json` và schema mới cho story contract.
- `src/ai_story/stage1/local_providers.py`: prompt và parser tạo contract/outline.
- `src/ai_story/stage1/providers.py`: fixture đúng semantics, không dùng template hội họa chung.
- `src/ai_story/stage1/validation.py`: event, role, relationship và state gates.
- `src/ai_story/stage1/pipeline.py`: lưu contract, evidence và status.

Điều kiện hoàn tất:

- Negative fixture vừa đánh giá bị chặn bởi tối thiểu bốn defect P0 nêu trên.
- Mọi case PASS trong golden set có required-event recall 100%.
- Không tăng false reject quá 5 điểm phần trăm so với baseline human labels.

### Giai đoạn 2 — generator nhiều bước và repair có mục tiêu (Tuần 4–5)

Mục tiêu là tăng chất lượng bản nháp, không chỉ tăng khả năng phát hiện lỗi.

- Tách generation thành `contract → outline → scene plan → prose`, với validation sau mỗi bước.
- Dùng beat budget theo độ phức tạp nội dung. Nếu brief quá mỏng so với thời lượng, trả cảnh báo hoặc
  đề xuất thời lượng ngắn hơn thay vì lặp/padding.
- Cung cấp cho mỗi scene: viewpoint, goal, obstacle, decision, state before/after, location, prop,
  dialogue owner và sensory detail.
- Critic dùng rubric cấu trúc; mỗi nhận xét phải có locator và defect code. Nhận xét không có bằng chứng
  không được dùng để cấp PASS.
- Repair theo defect map, giới hạn hai vòng. Mỗi vòng phải chứng minh lỗi đã đóng và không mở lại
  invariant đã đạt. Nếu không hội tụ, trả `BLOCKED` thay vì tiếp tục sửa mù.
- Chuẩn hóa xưng hô tiếng Việt dựa trên relationship, tuổi tương đối và bối cảnh.

Điều kiện hoàn tất:

- Median editorial score tăng ít nhất 10 điểm trên cùng case/seed.
- P0 defect rate bằng 0 trên golden set.
- Semantic repetition giảm ít nhất 50% mà không làm giảm required-event recall.
- Tỷ lệ repair hội tụ trong tối đa hai vòng đạt ít nhất 90% với lỗi có thể sửa.

### Giai đoạn 3 — trạng thái chất lượng và trải nghiệm vận hành (Tuần 6)

Mục tiêu là ngăn người dùng hiểu nhầm workflow success thành quality pass.

- Tách bốn trường: `workflow_status`, `technical_status`, `editorial_status`, `release_status`.
- Đặt `editorial_score=null` khi không có critic/human evidence hợp lệ. Giữ điểm heuristic dưới tên
  `preflight_score` và không dùng nó để mở stage.
- UI hiển thị defect theo severity và locator; cho phép xem brief requirement nào chưa được đáp ứng.
- Chỉ bật “Chuyển Stage 2” khi technical, safety và editorial đều PASS, asset không phải fixture.
- Ghi wall-clock, call, attempt, retry và model lineage thực cho cả deterministic adapter.

Điều kiện hoàn tất:

- Không trạng thái `SUCCEEDED` đơn lẻ nào được trình bày như “truyện đạt chất lượng”.
- Mọi quyết định chuyển stage giải thích được bằng evidence ID.
- Telemetry duration sai lệch không quá 5% so với job wall-clock.

### Giai đoạn 4 — visual continuity và production readiness (Tuần 7)

Mục tiêu là bảo đảm hình ảnh kế thừa đúng semantics của truyện đã duyệt.

- Character bible lấy tuổi, role, relationship, presentation, tóc, trang phục, palette, silhouette và
  cultural context từ story contract; cấm tự suy quan hệ từ tên.
- Character sheet có pose/expression tối thiểu và tỷ lệ chiều cao tương đối để phân biệt trẻ em/người lớn.
- Visual QA kiểm required/forbidden elements theo shot và identity theo từng nhân vật; CLIP toàn ảnh
  chỉ là tín hiệu phụ.
- Asset deterministic luôn mang nhãn fixture và không thể thỏa production evidence.
- Human review bắt buộc với character sheet, cover, climax và ending trước Stage 3/4.

Điều kiện hoàn tất:

- Role/age/presentation accuracy đạt 100% trên golden visual set.
- Required-element recall đạt ít nhất 95%; forbidden-element rate bằng 0.
- Reviewer phân biệt đúng các nhân vật khi che tên ở 100% sample duyệt.

### Giai đoạn 5 — benchmark, canary và phát hành (Tuần 8)

Mục tiêu là biến chất lượng thành quy trình phát hành có kiểm soát.

- Chạy benchmark full trên cùng corpus/seed cho baseline và candidate; báo confidence interval, không
  chỉ báo trung bình.
- Chỉ promote khi completion không giảm, P0 bằng 0, expected outcome accuracy bằng 100%, assessed
  editorial rate bằng 100%, median editorial tăng và latency/VRAM nằm trong budget.
- Canary 10% lượt tạo nội bộ; audit ngẫu nhiên 20 truyện trước khi mở rộng.
- Lưu model/prompt/rubric/corpus version trong package lineage để rollback được.
- Theo dõi drift theo tuần; tự động hạ candidate nếu blocker rate hoặc false-pass rate vượt ngưỡng.

Điều kiện hoàn tất:

- Benchmark verdict `PROMOTE` với đầy đủ evidence và digest.
- Canary không có P0; tỷ lệ human accept đạt ít nhất 85%.
- Có runbook rollback và một lần diễn tập rollback thành công.

## 5. Backlog ưu tiên

| ID | Hạng mục | Ưu tiên | Ước lượng | Phụ thuộc |
|---|---|---:|---:|---|
| QL-01 | Corpus v4 và taxonomy lỗi | P0 | 3 ngày | Không |
| QL-02 | Schema `story_contract.json` | P0 | 2 ngày | QL-01 |
| QL-03 | Entity/role/relationship extractor | P0 | 4 ngày | QL-02 |
| QL-04 | Event/state graph extractor | P0 | 5 ngày | QL-02 |
| QL-05 | Event coverage và unsupported-claim gates | P0 | 4 ngày | QL-03, QL-04 |
| QL-06 | Outline evidence binding | P0 | 3 ngày | QL-04 |
| QL-07 | Generator contract-to-prose | P1 | 6 ngày | QL-06 |
| QL-08 | Critic evidence và targeted repair | P1 | 5 ngày | QL-05, QL-07 |
| QL-09 | Chuẩn hóa audience và xưng hô | P1 | 3 ngày | QL-03 |
| QL-10 | Tách trạng thái và cập nhật UI | P1 | 4 ngày | QL-05 |
| QL-11 | Character bible và visual semantic QA | P1 | 6 ngày | QL-02, QL-10 |
| QL-12 | Benchmark report, canary và rollback | P2 | 5 ngày | QL-08, QL-11 |

Ước lượng trên là effort kỹ thuật, có thể chạy song song ở các hạng mục không phụ thuộc nhau; lịch 8
tuần giả định một nhóm nhỏ gồm backend/ML, QA-biên tập và hỗ trợ UI.

## 6. Bộ chỉ số điều hành

Chỉ số chất lượng cốt lõi:

- Required-event precision/recall.
- Forbidden-outcome rate và P0 defect rate.
- Role, relationship và state consistency accuracy.
- Editorial score theo chiều: brief, causality, character, scene craft, dialogue, agency, payoff,
  repetition, age fit.
- Human accept rate và inter-rater agreement.

Chỉ số vận hành bảo vệ:

- Completion rate, repair success rate và retry/asset.
- p50/p95 latency, peak memory và lỗi provider.
- Tỷ lệ `NOT_ASSESSED`, tỷ lệ fixture bị chặn và số lần override thủ công.

Mỗi dashboard phải tách theo profile, model, prompt version, độ dài và loại brief. Không dùng một điểm
tổng duy nhất để che khuất một chiều P0 thất bại.

## 7. Quy tắc phát hành

Một candidate chỉ được promote khi đồng thời thỏa các điều kiện sau:

- Toàn bộ test unit/contract/regression đạt; package verifier không có lỗi.
- Corpus canonical chạy đủ, cùng case/seed với baseline, không thiếu evidence.
- P0 defect và forbidden outcome bằng 0; expected outcome accuracy đạt 100%.
- Editorial được đánh giá thật ở 100% case; không dimension nào dưới ngưỡng.
- Candidate cải thiện có ý nghĩa so với baseline và không làm xấu completion, safety, latency hoặc
  visual recall ngoài budget đã duyệt.
- Manifest ghi đủ model, prompt, rubric, corpus, provider và runtime lineage.

Override chỉ dành cho development, phải có người chịu trách nhiệm, lý do và thời hạn hết hiệu lực;
override không được tạo nhãn production-ready.

## 8. Rủi ro và biện pháp giảm thiểu

- **Extractor sai làm chặn truyện tốt:** dùng confidence, evidence span, human review cho suy luận thấp
  và đo false reject riêng.
- **Tối ưu quá mức theo corpus:** giữ holdout set không cho prompt author xem; luân phiên bổ sung case
  từ lỗi production.
- **Critic đồng thuận giả với generator:** dùng model/seed khác, rubric cố định và audit người đọc.
- **Repair làm hỏng phần đã đúng:** kiểm toàn bộ contract sau mỗi patch, không chỉ lỗi vừa sửa.
- **Chi phí và độ trễ tăng:** chạy deterministic preflight trước, critic sâu sau; cache theo digest và
  giới hạn vòng repair.
- **Điểm tổng che blocker:** mọi P0 là fail-closed bất kể tổng điểm.

## 9. Bước triển khai ngay

Trong tuần đầu, thực hiện theo thứ tự:

1. Đưa run `run-20260927033250-8dceca4a` vào corpus dưới nhãn negative regression.
2. Viết schema `story_contract.json` và nhãn chuẩn cho case chống bão.
3. Thêm bốn test P0 cho sai domain, sai tuổi/vai trò, sai xưng hô và tuyên bố hoàn thành không có bằng chứng.
4. Đổi contract của quality report để preflight score không còn được xuất như editorial score.
5. Chạy baseline v4 và khóa số liệu trước khi thay prompt hoặc generator.

Đây là lát cắt nhỏ nhất tạo giá trị: sau bước này, lỗi nghiêm trọng của gói vừa đánh giá phải bị hệ
thống bắt tự động, đồng thời nhóm có một baseline tin cậy để đo mọi cải tiến tiếp theo.
