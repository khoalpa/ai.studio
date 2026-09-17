# Release Checklist

- [ ] Canonical prompt hash khớp `canonical/prompt.sha256`.
- [ ] `ruff format --check src scripts` đạt.
- [ ] `ruff check .` đạt.
- [ ] `mypy src` đạt.
- [ ] Full `pytest` đạt coverage tối thiểu 85%.
- [ ] Bundle có `open_app.bat`, `open_release.bat`, UI, migrations và canonical source.
- [ ] Bundle không chứa `.git`, `artifacts/` hoặc model weights.
- [ ] Manifest SHA-256 toàn bộ file hợp lệ.
- [ ] Clean-machine smoke đạt.
- [ ] Release acceptance trả `PASS`.
- [ ] Ghi lại bundle SHA-256 trong biên bản phát hành.

