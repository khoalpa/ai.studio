# M6-B Local Tesseract Adapter

`TesseractOcrAdapter` is an explicit local subprocess adapter. It never discovers, installs or
downloads an executable or language model. Callers must provide an executable path, exact SHA-256,
engine version, tessdata directory and an allowlist of language-model digests.

The adapter sends exact PNG bytes over stdin and requests TSV output. It parses the structured word
rows, validates page number, confidence and bounding boxes, filters evidence to the requested region,
and applies the existing NFC/whitespace normalization. Evidence binds the exact image, page identity,
region, languages, adapter/engine identity, model digests and normalized result. It does not log image
bytes or recognized text.

Stable production codes added by this checkpoint:

| Code | Meaning |
|---|---|
| `OCR008_REQUEST_INVALID` | Invalid request or adapter configuration |
| `OCR009_DEPENDENCY_MISSING` | Executable, requested language or model is absent |
| `OCR010_CANCELLED` | Cancellation was observed and the owned process was cleaned up |
| `OCR011_DEPENDENCY_DIGEST` | Executable or language model no longer matches its binding |
| `OCR012_OUTPUT_LIMIT` | Bounded stderr policy was exceeded |
| `OCR013_NON_ZERO_EXIT` | Tesseract returned a non-zero exit status |
| `OCR014_IMAGE_INVALID` | PNG, dimensions or region do not match the request |
| `OCR015_TSV_MALFORMED` | TSV is empty, truncated, malformed or outside its numeric contract |
| `OCR016_PAGE_IDENTITY` | TSV returned an unexpected page number |
| `OCR017_NORMALIZATION_INVALID` | Evidence text is not in canonical NFC/whitespace form |
| `OCR018_PROCESS_CLEANUP` | The owned Tesseract process could not be terminated or reaped |

The default test suite mocks only the process boundary and remains offline. Production validation is
the explicit `local_ocr` smoke test. It skips unless all executable/model/fixture paths and their
pre-locked digests are supplied through environment variables. A skip is `NOT_VERIFIED`, never PASS.
No local dependency or smoke output belongs in Git.
