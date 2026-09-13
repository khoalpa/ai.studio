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

The OCR checkpoint is committed. ComfyUI production validation now passes in
its separate checkpoint; production typography/font remains `MISSING` /
`NOT_VERIFIED`. Complete M6 production is not declared done and M7 remains out
of scope.

## Production zero-text smoke

The ComfyUI production PNG was inspected with pinned local Tesseract
`v5.5.0.20241111`, executable SHA-256
`ccd044d6cf16eaaad151260e1fcc5e3e1504cd1b8644e940b4f7ae3e315dd0d3`,
and pinned `eng`/`osd` traineddata. Process execution and digest binding PASS,
but the zero-text gate FAILS: Tesseract returned low-confidence false-positive
text at confidence `0.306593564`. Request digest is
`f8a1120e6220650a8c79b65abed782b4d128881bad9d8144ac6b001a5bea9361` and
result digest is
`d03d6906fdab466fe63627cd6ff3cad733f848b7da02a753ecdb63f4fdd03085`.
No production OCR PASS is claimed.

The deterministic residual-text policy now uses an explicit minimum confidence
of `0.8` without mutating raw OCR evidence. Re-running the same digest-bound
production fixture preserved the raw confidence `0.306593564` and classified
the low-confidence texture reading as no residual text; the zero-text gate is
therefore PASS. Regression tests cover low-confidence false positives,
high-confidence text, empty text and invalid thresholds. Full suite: 291 passed,
2 optional skips; branch coverage 92.85%; Ruff and mypy PASS.
