# Mốc E — Stage 4 và gói sản xuất

## Đã triển khai

Stage 4 giờ tạo một gói bàn giao production có thể kiểm chứng, thay vì chỉ tạo danh sách prompt video. Mỗi package gồm:

- `video_prompts.json`: clip plan canonical, giữ nguyên nội dung truyện và tham chiếu hình ảnh;
- `production_plan.json`: shot registry, continuity graph, camera vocabulary, negative-prompt policy, voice inventory và preset xuất;
- `subtitles.srt` và `subtitles.vtt`: phụ đề UTF-8 theo timeline nối tiếp của clip, giữ nguyên văn bản nguồn;
- `audio/<clip_id>.wav`: tùy chọn, chỉ có khi Piper render thành công một file cho mọi clip.

Mỗi shot có shot size, góc máy, chuyển động, framing rule, cut motivation, action, visual delta và digest của continuity vào/ra. Continuity graph nối đúng thứ tự clip và buộc state đầu vào của shot kế tiếp. Camera term và negative prompt được kiểm tra với vocabulary canonical trong `spec/stage4.json`.

## TTS local tùy chọn

Piper là adapter TTS offline hiện được hỗ trợ. Stage 4 luôn ghi voice inventory; hệ thống không tự chọn hoặc giả định một voice model. Không có `--render-tts`, package vẫn hợp lệ với trạng thái `PLANNED_NOT_RENDERED`.

Để render narration, cài executable `piper` trên `PATH` và cung cấp model `.onnx` đã được người vận hành chọn:

```powershell
$env:PYTHONPATH = "src"
py -3.10 -m ai_story generate-stage4 `
  --root .runtime `
  --input-package path\to\stage3\story.zip `
  --confirm-large-plan `
  --render-tts `
  --piper-voice-model path\to\vi_voice.onnx
```

Mỗi WAV được mở lại để xác nhận sample rate, số kênh và thời lượng. Audio dài hơn clip làm stage thất bại; không tạo package với bộ audio dở dang.

## Phụ đề và preset xuất

Timeline phụ đề dùng thời lượng clip làm mốc bắt đầu, còn điểm kết thúc dùng `usable_span_seconds`. Production plan bind SHA-256 của cả SRT và WebVTT.

Hai preset canonical:

- `LANDSCAPE_16_9`: 3840 × 2160, 24 fps, H.264/AAC, `yuv420p`;
- `PORTRAIT_9_16`: 1080 × 1920, 30 fps, H.264/AAC, `yuv420p`.

`mux_command_template` là hướng dẫn bàn giao cho renderer/FFmpeg, không tuyên bố rằng video đã được render. Trạng thái project giữ `PLANNED_NOT_RENDERED` cho đến khi có một video renderer riêng.

## Validation và ranh giới

Trước khi đóng ZIP, pipeline kiểm tra field order/schema, digest production plan, số shot, thứ tự clip, continuity edge, camera vocabulary, negative prompt, binding phụ đề, audio và export preset. Manifest bind toàn bộ artifact bằng SHA-256.

Mốc này chưa sinh frame động hoặc file MP4. Video generation vẫn là adapter tùy chọn ở bước downstream; gói hiện tại là đầu vào production đã chuẩn hóa và có thể tái lập.
