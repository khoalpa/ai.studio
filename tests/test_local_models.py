from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_story.errors import ConfigurationError
from ai_story.local_models import LocalModelManager


class LocalModelManagerTests(unittest.TestCase):
    def test_register_activate_and_remove_preserves_weights(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            weights = root / "story.gguf"
            weights.write_bytes(b"small-test-model")
            manager = LocalModelManager(root)
            item = manager.register(
                {"id": "story-q4", "name": "Story Q4", "kind": "text", "path": str(weights)}
            )
            self.assertEqual(item["status"], "READY")
            self.assertTrue(item["sha256"])
            active = manager.activate("story-q4", "story")
            self.assertEqual(active["active_roles"], ["story"])
            result = manager.remove("story-q4")
            self.assertFalse(result["weights_deleted"])
            self.assertTrue(weights.is_file())

    def test_invalid_role_kind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            weights = root / "voice.onnx"
            weights.write_bytes(b"voice")
            manager = LocalModelManager(root)
            manager.register({"id": "voice", "kind": "voice", "path": str(weights)})
            with self.assertRaises(ConfigurationError):
                manager.activate("voice", "story")

    def test_uncached_remote_model_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = LocalModelManager(Path(temporary))
            item = manager.register(
                {"id": "remote", "kind": "image", "model_id": "missing/example-model"}
            )
            self.assertEqual(item["status"], "DOWNLOAD_REQUIRED")
            with self.assertRaises(ConfigurationError):
                manager.activate("remote", "landscape")

    def test_optional_cli_values_accept_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            weights = root / "story.gguf"
            weights.write_bytes(b"small-test-model")
            manager = LocalModelManager(root)
            item = manager.register(
                {
                    "id": "story-cli",
                    "kind": "text",
                    "path": str(weights),
                    "model_id": None,
                    "quantization": None,
                }
            )
            self.assertEqual(item["status"], "READY")

    def test_stage_selection_is_scoped_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            weights = root / "story.gguf"
            weights.write_bytes(b"small-test-model")
            manager = LocalModelManager(root)
            manager.register({"id": "writer", "kind": "text", "path": str(weights)})
            selected = manager.resolve_stage_selection(1, {"story": "writer"})
            self.assertEqual(selected["story"]["id"], "writer")
            self.assertEqual(manager.inventory()["active"], {})
            with self.assertRaises(ConfigurationError):
                manager.resolve_stage_selection(2, {"story": "writer"})

    def test_component_directory_is_visible_but_not_selectable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            component = root / "clip"
            component.mkdir()
            (component / "config.json").write_text("{}", encoding="utf-8")
            manager = LocalModelManager(root)
            item = manager.register({
                "id": "clip-qa", "kind": "vision", "path": str(component),
                "lifecycle": "system", "usage": "Semantic QA", "selectable": False,
            })
            self.assertEqual(item["status"], "READY")
            self.assertEqual(item["lifecycle"], "system")
            self.assertFalse(item["selectable"])
            with self.assertRaises(ConfigurationError):
                manager.activate("clip-qa", "story")


if __name__ == "__main__":
    unittest.main()
