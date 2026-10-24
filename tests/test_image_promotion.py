from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from ai_story.image_promotion import promote_cover_in_bundle


class ImagePromotionTests(unittest.TestCase):
    def test_promote_cover_changes_only_cover_and_keeps_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.zip"
            approved = root / "approved.png"
            output = root / "promoted.zip"
            backup = root / "rollback" / "cover.png"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("checkpoint.json", b"checkpoint")
                archive.writestr("landscape/cover.png", b"old-cover")
                archive.writestr("landscape/climax.png", b"climax")
                archive.writestr("landscape/ending.png", b"ending")
            approved.write_bytes(b"approved-cover")

            report = promote_cover_in_bundle(
                source_bundle=source,
                approved_cover=approved,
                output_bundle=output,
                backup_cover=backup,
            )

            self.assertEqual(report["changed_entries"], ["landscape/cover.png"])
            self.assertTrue(report["rollback_verified"])
            self.assertEqual(backup.read_bytes(), b"old-cover")
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("landscape/cover.png"), b"approved-cover")
                self.assertEqual(archive.read("landscape/climax.png"), b"climax")
                self.assertEqual(archive.read("landscape/ending.png"), b"ending")

    def test_promote_cover_allows_only_declared_metadata_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.zip"
            approved = root / "approved.png"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("checkpoint.json", b"old-checkpoint")
                archive.writestr("landscape/cover.png", b"old-cover")
                archive.writestr("landscape/climax.png", b"climax")
            approved.write_bytes(b"approved-cover")

            report = promote_cover_in_bundle(
                source_bundle=source,
                approved_cover=approved,
                output_bundle=root / "promoted.zip",
                backup_cover=root / "rollback.png",
                metadata_updates={"checkpoint.json": b"new-checkpoint"},
            )

            self.assertEqual(
                report["changed_entries"],
                ["checkpoint.json", "landscape/cover.png"],
            )


if __name__ == "__main__":
    unittest.main()
