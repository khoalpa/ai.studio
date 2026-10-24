# AI Themes 1.0.0

AI Themes là bộ giao diện dùng chung cho các dự án trong `D:/project`. Nguồn chuẩn nằm tại `ai.atelier/themes`; thư mục `themes` trong mỗi dự án khác là một bản sao được ghim phiên bản. Ứng dụng chỉ dùng tài nguyên cục bộ và không cần truy cập thư mục của dự án bên cạnh khi chạy.

## Cấu hình giao diện

`project.json` xác định bốn nhóm tùy chọn:

| Thuộc tính | Giá trị hỗ trợ |
|---|---|
| `theme` | `neutral`, `studio`, `paper` |
| `mode` | `system`, `light`, `dark` |
| `style` | `minimal`, `soft`, `editorial` |
| `density` | `comfortable`, `compact` |

Token màu nguồn nằm trong `tokens.json`; component chỉ sử dụng các biến `--ui-*`. Màu của ảnh, video, phụ đề và nhận diện nghiệp vụ nằm ngoài phạm vi theme và phải được giữ nguyên.

Khả năng chọn giao diện phụ thuộc vào nền tảng:

- Web có nút tròn **Giao diện** ở góc dưới bên phải. Lựa chọn được lưu riêng cho từng ứng dụng trong trình duyệt; chế độ hệ thống tự cập nhật khi hệ điều hành đổi theme.
- Streamlit có nhóm **Giao diện** trong thanh bên và lưu lựa chọn theo phiên ứng dụng.
- Windows/Gradio nhận cấu hình mặc định hoặc các biến `AI_THEME`, `AI_THEME_MODE`, `AI_THEME_STYLE`, `AI_THEME_DENSITY` khi khởi động.
- Android dùng bảng màu Neutral sáng/tối theo hệ thống.
- Telegram giữ bộ chọn chế độ hiện có.

## Tích hợp vào ứng dụng web

Sao chép `dist/theme.css` và `dist/theme.js` vào thư mục tài nguyên do máy chủ phục vụ. Nạp JavaScript trong `head` trước phần nội dung để khôi phục lựa chọn trước khi trang được vẽ, sau đó nạp CSS của theme sau CSS ứng dụng.

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

Các lớp component có sẵn gồm `.ui-input`, `.ui-select`, `.ui-textarea`, `.ui-card`, `.ui-table`, `.ui-feedback`, `.ui-tabs` và `.ui-actions`. Ứng dụng vẫn chịu trách nhiệm triển khai điều khiển bàn phím và trạng thái ARIA cho tabs. Nút đổi giao diện sử dụng dialog gốc của trình duyệt.

Font mặc định là font hệ thống có hỗ trợ tiếng Việt. Phong cách Editorial dùng serif cho tiêu đề. Khoảng cách, độ bo góc và màu sắc được cấu hình độc lập.

## Phát triển, triển khai và hoàn tác

Chạy các lệnh sau tại dự án AI Atelier:

```powershell
.venv-ai/Scripts/python.exe themes/tools/build.py
.venv-ai/Scripts/python.exe themes/tools/deploy.py
.venv-ai/Scripts/python.exe themes/tools/verify.py
node themes/tools/theme.test.js
```

- `build.py` sinh CSS từ token.
- `deploy.py` đồng bộ bản ghim và tài nguyên runtime, đồng thời cập nhật các điểm nạp đã biết.
- `verify.py` xác minh kết quả triển khai.
- Tệp nguồn bị thay đổi được sao lưu trong `.theme-backups/` của từng dự án.
- Manifest trong `themes/deployment/` ghi đường dẫn và checksum.
- Chạy lại quy trình không sửa những tệp đã có nội dung giống nhau.

Hoàn tác một lần triển khai:

```powershell
.venv-ai/Scripts/python.exe themes/tools/deploy.py --rollback themes/deployment/TIMESTAMP.json
```

Quy trình từ chối hoàn tác nếu tệp đã được chỉnh sửa thêm sau lần triển khai đó và không tự xóa thay đổi mới của người dùng. Các bản đóng gói cũ phải được tạo lại; tiến trình đang chạy phải được khởi động lại để nhận theme mới.

Manifest tổng hợp của đợt triển khai đầu tiên nằm tại `deployment/initial-rollout.json`. Kết quả kiểm tra và giới hạn xác minh nằm trong `verification/results.json`; ảnh trang mẫu nằm tại `verification/preview.png`.

## Bộ chuyển đổi theo nền tảng

| Dự án | Điểm tích hợp |
|---|---|
| ai.atelier | Web, ánh xạ token và palette cũ |
| ai.studio | Web, ánh xạ biến và danh sách tài nguyên máy chủ |
| watermarks-remover | Web, ánh xạ biến và tuyến tài nguyên |
| ai.slide, ai.story | Studio và cửa sổ Audio/Video Streamlit |
| ai.player | QSS, giữ bố cục và thay bảng màu của cửa sổ chính |
| ai.meeting, ai.player.android | Resource màu giữ ID cũ và `values-night` |
| ai.telegram.android | Material 3 `ColorScheme`, giữ bộ chọn sáng/tối |
| VieNeu-TTS | Gradio CPU/CUDA, XPU và giao diện streaming FastAPI |
| sd.webui | Extension `ai-shared-themes`, không sửa mã upstream |

CSS component đầy đủ dành cho web. Native adapter ánh xạ theo khả năng của từng nền tảng; Android chưa có bộ chọn ba phong cách và hai mật độ trong phần cài đặt. QSS vẫn giữ các quy tắc bố cục riêng. Khi thêm màn hình mới, hãy dùng semantic token để tránh mở rộng lớp tương thích màu cũ.
