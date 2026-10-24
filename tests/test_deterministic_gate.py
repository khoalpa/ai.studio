from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ai_story.determinism import package_fingerprint


class DeterministicGateTests(unittest.TestCase):
    def _package(self, path: Path, *, run_id: str, story: str) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "workflow_manifest.json",
                json.dumps(
                    {
                        "run_id": run_id,
                        "created_at": "2026-09-30T10:00:00Z",
                        "package_digest_sha256": "volatile",
                        "story": story,
                    }
                ),
            )
            archive.writestr("assets/reference.bin", b"fixed-asset")

    def test_fingerprint_ignores_only_operational_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "a.zip", root / "b.zip"
            self._package(first, run_id="run-20260930100000-aaaaaaaa", story="same")
            self._package(second, run_id="run-20260930110000-bbbbbbbb", story="same")
            self.assertEqual(package_fingerprint(first), package_fingerprint(second))

    def test_fingerprint_detects_semantic_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "a.zip", root / "b.zip"
            self._package(first, run_id="run-20260930100000-aaaaaaaa", story="first")
            self._package(second, run_id="run-20260930110000-bbbbbbbb", story="second")
            self.assertNotEqual(package_fingerprint(first), package_fingerprint(second))


if __name__ == "__main__":
    unittest.main()
