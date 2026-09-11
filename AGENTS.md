# Audio Story Offline Runtime

## Scope and invariants

- `canonical/ChatGPT_prompt_v3.16.13.txt` is the byte-for-byte source of truth. Do not edit it in milestones M0-M8. Verify it against `canonical/prompt.sha256`.
- Runtime operation is offline. Never add cloud fallback, cloud credentials, or automatic model downloads.
- Local services bind to `127.0.0.1` by default.
- Deterministic checks (schema, counts, hashes, paths, dimensions, CRC, archive safety, and timeline arithmetic) belong to code, never LLM self-assessment.
- Preserve the v3.16.13 CURRENT `story.zip` layout. Schema changes require an ADR and a compatibility adapter.
- The RTX A4500 Laptop GPU has 16 GB VRAM. Permit at most one GPU-heavy job system-wide.
- Work one milestone at a time. Keep unrelated user changes and update `docs/status/<milestone>.md` with evidence before stopping.
- Do not begin a later milestone until the current milestone Definition of Done passes.

## Development baseline

Use Python 3.11 or newer. Install with `python -m pip install -e ".[dev]"`, then run:

```text
ruff format --check .
ruff check .
mypy src
pytest
```
