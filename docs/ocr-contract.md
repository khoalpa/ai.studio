# M6 OCR Contract

`LocalOcrAdapter` returns normalized text, confidence, a crop locator, engine identity and an
evidence digest bound to the input image digest. The deterministic mock is empty-text test evidence
only; it does not modify pixels or claim production OCR quality. Low confidence, residual text and
safe-margin decisions remain deterministic gates owned by the image workflow.

`inspect_ocr` converts a local-engine timeout or exception into stable
`OCR006_ENGINE_TIMEOUT` or `OCR007_ENGINE_FAILURE` and then validates the
returned evidence. Validation rejects an invalid confidence policy
(`OCR001_CONFIDENCE_POLICY`), confidence outside the configured domain or
threshold (`OCR002_CONFIDENCE_INVALID`), malformed/out-of-region boxes
(`OCR003_BOUNDING_BOX_INVALID`), malformed evidence digests
(`OCR004_EVIDENCE_DIGEST_INVALID`) and image bytes that no longer match the
request digest (`OCR005_STALE_IMAGE_DIGEST`). None of these fixture-level tests
constitutes production OCR validation.
