# Tuần 6 — QA và hoàn thiện

Ngày kiểm thử: 24/09/2026  
Phạm vi: web MVP, workflow Stage 1–4, package, responsive và accessibility cơ bản.

## 1. Kết quả phát hành

**Kết luận kỹ thuật:** đạt điều kiện phát hành local MVP.

Điều kiện đi kèm:

- Chỉ bind localhost theo mặc định.
- Provider hiện tại là deterministic development provider.
- Job đang chạy không được phục hồi sau khi restart server.
- Usability test với 5 người dùng thật chưa được thực hiện; các chỉ số task-completion vẫn là mục tiêu cần xác thực, không phải kết quả đã đo.

## 2. Kiểm thử tự động

Lệnh:

```powershell
$env:PYTHONPATH = "src"
py -3 tools/lint_spec.py
py -3 -m unittest discover -s tests -v
```

Kết quả:

- Spec linter: PASS.
- Profiles: 3.
- Routes: 24.
- Gates: 18.
- Unit/integration tests: 27 PASS, 0 FAIL.
- Web test bao phủ tuyến Stage 1 → Stage 4 bằng job API.
- Package inspector được kiểm bằng package Stage 1 thật.
- Artifact path traversal bị từ chối.
- Unknown API endpoint trả 404.
- CSP và security headers được kiểm tra.

## 3. Smoke test trên trình duyệt

Đã kiểm tra trực tiếp:

1. Mở dashboard khi workspace trống.
2. Tạo truyện thiếu nhi bằng wizard.
3. Theo dõi job Stage 1 đến khi hoàn thành.
4. Mở workspace và preview artifact.
5. Khởi chạy Stage 2 từ checkpoint Stage 1.
6. Hiển thị gallery ảnh ngang.
7. Tải package qua endpoint của run.
8. Kiểm tra accessibility tree và browser console.

Kết quả browser console: không có error hoặc warning.

## 4. Responsive QA

Viewport đã kiểm tra:

- Desktop mặc định của Codex browser.
- Mobile 390 × 844 px.

Các vấn đề tìm thấy và đã sửa:

| ID | Mức | Vấn đề | Cách sửa |
|---|---|---|---|
| QA-01 | P1 | Mobile grid kéo giãn hàng navigation, tạo khoảng trống lớn | Đặt `grid-template-rows: auto 1fr` dưới 680 px |
| QA-02 | P1 | Nav label bị ẩn trên mobile làm link mất accessible name | Thêm `aria-label` độc lập cho bốn link chính |
| QA-03 | P1 | Gallery Stage 2 trộn ảnh nhân vật kế thừa với ảnh ngang | Lọc preview theo prefix artifact của stage hiện tại |
| QA-04 | P2 | Stage navigation dùng semantics tab nhưng không đổi panel | Chuyển thành progress list với `aria-current="step"` |
| QA-05 | P2 | Stage 1 ưu tiên gallery nhân vật thay vì kịch bản | Ưu tiên preview nội dung truyện ở Stage 1 |
| QA-06 | P2 | Static asset cache gây khó xác minh thay đổi khi phát triển | Chuyển web asset sang `Cache-Control: no-cache` |

## 5. Accessibility checklist

| Hạng mục | Kết quả | Ghi chú |
|---|---|---|
| Landmark và heading | PASS | Header, nav, main và heading có cấu trúc |
| Accessible names | PASS | Nav, icon button và run links có nhãn |
| Keyboard controls | PASS | Dùng button, link, input, select và textarea native |
| Focus visibility | PASS | Focus ring 2 px dùng brand token |
| Color-independent state | PASS | Badge có text và dot; lỗi có nhãn |
| Touch target | PASS có điều kiện | Control chính ≥ 38 px; media query/layout dành đủ khoảng chạm |
| Reduced motion | PASS | Có `prefers-reduced-motion` |
| Dynamic job status | PASS | Modal và toast dùng nội dung đọc được; toast có `aria-live` |
| Screen-reader test thực tế | Chưa thực hiện | Cần NVDA/VoiceOver trước production release |
| Automated contrast audit | Chưa thực hiện | Token được thiết kế theo AA nhưng cần đo bằng tooling ở production stack |

## 6. Security và integrity

- Server mặc định bind `127.0.0.1`.
- CSP chỉ cho phép script/style/image/connect từ cùng origin; style inline được phép vì frontend hiện dùng style trạng thái động.
- `frame-ancestors 'none'` và `X-Frame-Options: DENY` ngăn embedding.
- Camera, microphone và geolocation bị tắt bằng Permissions Policy.
- Không gửi referrer.
- Run ID và artifact path được chuẩn hóa và giới hạn trong runtime root.
- ZIP inspector dùng verifier canonical, có giới hạn upload 100 MB và xóa file tạm.
- Package nguồn không bị ghi đè khi chạy stage tiếp theo.

## 7. Acceptance criteria MVP

| Tiêu chí | Trạng thái |
|---|---|
| Tạo Stage 1 không dùng CLI | PASS |
| Chạy tuyến Stage 1–4 qua web API | PASS |
| Không cho bỏ qua source stage canonical | PASS |
| Hiển thị năm validation status mà không gom nhị phân | PASS |
| Preview artifact theo stage | PASS |
| Package inspector | PASS |
| Download package | PASS |
| Responsive desktop/mobile | PASS sau sửa QA-01/02 |
| Repair editor | DEFERRED |
| Tiếp tục/kết thúc series từ anchor | DEFERRED |
| Usability test 5 người | CHƯA THỰC HIỆN |

## 8. Release checklist

- [x] Spec lint đạt.
- [x] Toàn bộ automated tests đạt.
- [x] Web server bind localhost mặc định.
- [x] Static assets được đóng gói trong distribution.
- [x] Smoke test Stage 1 và Stage 2 trên browser.
- [x] Service integration test Stage 1–4.
- [x] Desktop và mobile breakpoint được kiểm tra.
- [x] Browser console sạch.
- [x] Security headers hiện diện.
- [ ] Usability test với người dùng thật.
- [ ] Screen-reader test bằng NVDA hoặc VoiceOver.
- [ ] Kiểm thử production provider.

## 9. Go-live recommendation

Phù hợp để phát hành dưới nhãn **Local Development MVP**. Không nên gắn nhãn production-ready trước khi hoàn thành ba mục chưa đánh dấu trong release checklist.

