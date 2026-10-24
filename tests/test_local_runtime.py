from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_story.local_runtime import LlamaServerSupervisor


class LlamaServerSupervisorTests(unittest.TestCase):
    def test_state_match_requires_same_catalog_id_and_resolved_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.gguf"
            second = root / "second.gguf"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            supervisor = LlamaServerSupervisor(root)
            supervisor.state_path.parent.mkdir(parents=True)
            supervisor.state_path.write_text(
                json.dumps(
                    {"pid": 123, "model_id": "first", "model_path": str(first)}
                ),
                encoding="utf-8",
            )

            self.assertTrue(
                supervisor._state_matches({"id": "first", "path": str(first)})
            )
            self.assertFalse(
                supervisor._state_matches({"id": "second", "path": str(second)})
            )
            self.assertFalse(
                supervisor._state_matches({"id": "other-id", "path": str(first)})
            )


if __name__ == "__main__":
    unittest.main()
