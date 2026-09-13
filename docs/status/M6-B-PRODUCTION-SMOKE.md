# M6-B Combined Production Smoke

Status: PASS.

The combined offline transaction ran on `127.0.0.1:8189` using ComfyUI
`0.35.1`, the digest-bound SDXL workflow, checkpoint SHA-256
`31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b`,
Pillow/DejaVu Sans renderer `M6B-PILLOW-1.0`, and pinned Vietnamese
Tesseract `v5.5.0.20241111`. No model or dependency was downloaded. Custom
nodes, API nodes, Manager UI and auto-launch were disabled; deterministic mode
was enabled. The evidence record was corrected to the active shared checkpoint
path without changing its previously approved digest.

The exact sequence was ComfyUI generation, base PNG QA, Vietnamese zero-text
OCR, production typography, final PNG QA, exact Vietnamese OCR, candidate
registration, three current PASS gates, and transaction commit. The base image
SHA-256 was
`c3ea2fa66475abb956acfc60ffba088411f645ad900c63faf512a53e246c3e2a`.
Raw base OCR confidence was `0.36375960153846154`, below the residual-text
policy threshold `0.8`, so the zero-text gate passed without discarding its raw
evidence. Base OCR evidence SHA-256 was
`700917de75462bf8ec8436bf806df507372e50b6a721dca8b568e77088de52a7`.

The committed 1024x1024 cover SHA-256 was
`9413e28d7be6a2919601f1b30b73f116709bb0897e5ffa7985417b6c3dc88778`.
Final OCR returned exactly `Chuyện kể đêm nay` with confidence
`0.9636167525`; evidence SHA-256 was
`253175752e78dbd92b2d5afea598fda0176e1dcf1c2cf434725fdffad8db4f03`
and normalized text SHA-256 was
`d2e4c33fb09a305930c97c98e5cc0d8e1f9a076ded2d4dfd92f875a7bcedb771`.
The transaction finished `AUTHORITATIVE`, progress was `1/1`, and the current
gate set was `IMAGE_QA_GATE`, `TYPOGRAPHY_GATE`, and `OCR_GATE`.

The reusable smoke entry point is `scripts/run_m6b_production_smoke.py`. The
default offline suite remains GPU-free; this explicit smoke requires the
provisioned local dependencies and a reviewed offline ComfyUI instance.
Final verification reports 300 passed, 2 optional smoke skips and 92.64% total
branch coverage. Ruff, mypy strict, canonical prompt SHA-256 and
`git diff --check` pass.
