# Audio Story Studio — Sổ tay vận hành

## 1. Khởi chạy

Từ thư mục dự án, chạy:

```bat
open_app.bat
```

Mặc định Studio dùng workspace `artifacts\studio-workspace` và bind tại
`http://127.0.0.1:4173`. Có thể truyền workspace khác:

```bat
open_app.bat D:\du-lieu\workspace
```

Mở trình duyệt tại `http://127.0.0.1:4173`. Dừng server bằng `Ctrl+C`.

## 2. Quy trình sản xuất

1. Tạo Stage 1 và chờ trạng thái `PASS`.
2. Tạo Stage 2 bằng `MOCK` cho kiểm thử hoặc `COMFYUI` cho ảnh local.
3. Với ComfyUI, mở `Duyệt semantic`, chạy Qwen local hoặc nhập nhận xét thủ công.
4. Chỉ khi đủ 10/10 semantic PASS, Stage 2 mới tạo package.
5. Bắt đầu Stage 3 Portrait; mặc định dùng `VLM_LOCAL`.
6. Sau Stage 3 PASS, mở Timeline và dựng Stage 4 Video.
7. Màn hình Xuất bản & sao lưu phải hiển thị readiness PASS trước khi phát hành.

## 3. Backup và restore

Trong UI chọn `Xuất bản & sao lưu` → `Tạo backup STATE_ONLY`. Backup được lưu dưới
`<workspace>\backups\` và hiển thị SHA-256.

Backup đầy đủ bằng CLI:

```text
audio-story backup --workspace <workspace> --output <backup.zip> --mode FULL
```

Restore chỉ thực hiện vào workspace rỗng:

```text
audio-story restore --backup <backup.zip> --workspace <empty-workspace>
```

Không restore trực tiếp lên workspace đang sản xuất.

## 4. Xử lý lỗi

- `UI110/UI111`: kiểm tra Stage 1 package và đường dẫn nằm trong workspace.
- `M7C299_AGGREGATE_BLOCKED`: còn thiếu hoặc có semantic assessment không đạt.
- `VLM001`: kiểm tra model path trong `docs/m7-vlm-assessor.json` và dependency local.
- `M10C001`: kiểm tra FFmpeg và FFprobe có trong PATH hoặc truyền đường dẫn CLI.
- `M22_STAGE4_OUTPUT_MISSING`: chạy lại Stage 4 trước khi xuất bản.
- Tác vụ nặng đang chạy: dùng nút Hủy; không kill process cưỡng bức nếu chưa cần.

Kiểm tra readiness qua API:

```text
GET http://127.0.0.1:4173/api/v1/release
```

## 5. Kiểm tra release

Build bundle:

```text
.venv\Scripts\python.exe scripts\build_release_bundle.py
```

Acceptance trên bundle:

```text
.venv\Scripts\python.exe scripts\validate_release_bundle.py dist\audio-story-studio.zip
```

Chỉ phát hành khi acceptance trả `status: PASS`.

