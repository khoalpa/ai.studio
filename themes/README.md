# AI Themes 1.0.0

Bộ giao diện dùng chung cho các dự án trong `D:/project`. Nguồn chuẩn là
`ai.atelier/themes`; thư mục `themes` ở dự án khác là bản sao ghim phiên bản.
Ứng dụng chạy bằng tài nguyên cục bộ, không cần đọc thư mục của dự án bên cạnh.

## Cấu hình

`project.json` chọn `theme` (neutral, studio, paper), `mode` (system, light,
dark), `style` (minimal, soft, editorial), `density` (comfortable, compact).
Token màu nguồn nằm trong `tokens.json`; component chỉ dùng biến `--ui-*`.
Giữ màu nội dung ảnh, video, phụ đề và màu nhận diện nghiệp vụ ngoài theme.

Web có nút tròn “Giao diện” ở góc phải dưới. Lựa chọn được lưu riêng cho từng
ứng dụng trong trình duyệt. Chế độ hệ thống tự cập nhật khi hệ điều hành đổi.
Streamlit có nhóm “Giao diện” trong thanh bên, lưu theo phiên ứng dụng.
Windows/Gradio nhận cấu hình mặc định hoặc các biến `AI_THEME`, `AI_THEME_MODE`,
`AI_THEME_STYLE`, `AI_THEME_DENSITY` khi khởi động. Android dùng bảng màu Neutral
sáng/tối theo hệ thống; Telegram giữ bộ chọn chế độ đã có.

## Tích hợp web mới

Sao chép `dist/theme.css` và `dist/theme.js` vào thư mục tài nguyên được máy chủ
phục vụ. Nạp JS trong head trước nội dung để phục hồi lựa chọn trước khi vẽ;
nạp CSS sau CSS của ứng dụng.

```html
<html data-theme="neutral" data-mode="system" data-style="minimal"
      data-density="comfortable" data-theme-app="my-project">
  <head>
    <script src="/ai-theme.js"></script>
    <link rel="stylesheet" href="/ai-theme.css">
  </head>
  <body class="ui-scope">
    <button class="ui-button ui-primary">Lưu</button>
  </body>
</html>
```

Dùng `.ui-input`, `.ui-select`, `.ui-textarea`, `.ui-card`, `.ui-table`,
`.ui-feedback`, `.ui-tabs`, `.ui-actions`. Tabs vẫn cần logic bàn phím và trạng
thái ARIA của ứng dụng. Nút đổi giao diện sử dụng dialog gốc của trình duyệt.
Font mặc định là font hệ thống hỗ trợ tiếng Việt. Editorial dùng serif cho
tiêu đề; khoảng cách và bo góc đổi độc lập với màu.

## Phát triển và cập nhật

Chạy tại dự án AI Atelier:

```powershell
.venv-ai/Scripts/python.exe themes/tools/build.py
.venv-ai/Scripts/python.exe themes/tools/deploy.py
.venv-ai/Scripts/python.exe themes/tools/verify.py
node themes/tools/theme.test.js
```

`build.py` sinh CSS từ token. `deploy.py` đồng bộ bản ghim và tài nguyên runtime,
cập nhật điểm nạp đã biết. Tệp nguồn bị sửa có bản sao tại `.theme-backups/` của
từng dự án. Manifest trong `themes/deployment/` ghi đường dẫn và checksum.
Lần chạy lại không sửa những tệp có nội dung giống nhau.

Hoàn tác một lần triển khai:

```powershell
.venv-ai/Scripts/python.exe themes/tools/deploy.py --rollback themes/deployment/TIMESTAMP.json
```

Hoàn tác từ chối nếu tệp đã được chỉnh tiếp sau triển khai. Không tự hoàn tác
những sửa đổi mới của người dùng. Các bản đóng gói cũ và tiến trình đang chạy
cần được tạo lại hoặc khởi động lại để nhận thay đổi.

Đợt triển khai đầu tiên có manifest gộp `deployment/initial-rollout.json`.
Kết quả kiểm tra và giới hạn xác minh ghi tại `verification/results.json`;
ảnh trang mẫu tại `verification/preview.png`.

## Bộ chuyển đổi nền tảng

| Dự án | Điểm tích hợp |
|---|---|
| ai.atelier | Web, ánh xạ token và palette cũ |
| ai.studio | Web, ánh xạ biến và danh sách tài nguyên máy chủ |
| watermarks-remover | Web, ánh xạ biến và tuyến tài nguyên |
| ai.slide, ai.story | Studio và cửa sổ Audio/Video Streamlit |
| ai.player | QSS, giữ bố cục và thay bảng màu của cửa sổ chính |
| ai.meeting, ai.player.android | Resource màu giữ ID cũ và values-night |
| ai.telegram.android | Material 3 ColorScheme, giữ bộ chọn sáng/tối |
| VieNeu-TTS | Gradio CPU/CUDA, XPU và giao diện streaming FastAPI |
| sd.webui | Extension ai-shared-themes; không sửa mã upstream |

CSS component đầy đủ dành cho web. Native adapter ánh xạ theo khả năng nền tảng;
chưa bổ sung bộ chọn ba phong cách/hai mật độ vào cài đặt Android. QSS giữ các
quy tắc bố cục đặc thù. Khi thêm màn hình mới, dùng semantic token để tránh
phải mở rộng lớp tương thích màu cũ.
