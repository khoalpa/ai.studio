# M6-B Checkpoint 2 — Tesseract production adapter

Status: reviewed and committed at `7cd8fe3`.

This checkpoint adds the local Tesseract TSV adapter, typed production binding fields, deterministic
negative tests and an explicit digest-bound production smoke harness. It does not modify ComfyUI or
production typography, start a backend, download a model, call a cloud API, implement M7, modify the
canonical prompt or resolve PCF001.

The production smoke remains `NOT_VERIFIED` until a reviewed PNG fixture and all environment bindings
are explicitly supplied and the `local_ocr` test passes. Default mocked process tests are not recorded
as production evidence.

## Verification

Toolchain: bundled Python 3.12.14, Ruff 0.16.7, mypy 2.3.1 strict and pytest 9.1.1.

- `python -m ruff format --check .`: PASS (109 files already formatted).
- `python -m ruff check .`: PASS.
- `python -m mypy src`: PASS (55 source files).
- `python -m pytest`: PASS — 271 passed, 2 skipped.
- Whole-repository branch coverage: 93.28%.
- `tesseract.py` branch coverage: 92%.
- Focused OCR/adapter tests: PASS — 34 passed.
- Production Tesseract smoke: SKIP / `NOT_VERIFIED`; no approved digest-bound PNG fixture was
  supplied. The other skip is the pre-existing optional llama.cpp smoke.
- Canonical SHA-256/read-only: PASS.
- `git diff --check`: PASS.

## Changed paths

- `pyproject.toml`
- `src/audio_story/adapters/ocr/__init__.py`
- `src/audio_story/adapters/ocr/base.py`
- `src/audio_story/adapters/ocr/mock.py`
- `src/audio_story/adapters/ocr/tesseract.py`
- `tests/unit/test_image_adapters.py`
- `tests/unit/test_tesseract_adapter.py`
- `tests/integration/test_tesseract_smoke.py`
- `docs/tesseract-adapter.md`
- `docs/status/M6-B-OCR.md`

The OCR checkpoint is committed. ComfyUI stays `BLOCKED`; production typography/font remains
`MISSING` / `NOT_VERIFIED`; complete M6 production is not declared done and M7 remains out of scope.
