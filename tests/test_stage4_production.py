from __future__ import annotations

import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from ai_story.stage4.subtitles import derive_subtitles, render_srt, render_webvtt
from ai_story.stage4.tts import render_tts


class Stage4ProductionTests(unittest.TestCase):
    def test_subtitles_follow_concatenated_clip_timeline_and_exact_text(self) -> None:
        clips = [
            {
                "clip_id": "clip_0001",
                "duration_seconds": 4,
                "usable_span_seconds": 2.5,
                "voice_plan": {"segments": [{"text": "Xin chào."}]},
            },
            {
                "clip_id": "clip_0002",
                "duration_seconds": 6,
                "usable_span_seconds": 3.25,
                "voice_plan": {"segments": [{"text": "Câu chuyện bắt đầu."}]},
            },
        ]
        entries = derive_subtitles(clips)
        self.assertEqual(entries[1].start_seconds, 4.0)
        self.assertEqual(entries[1].end_seconds, 7.25)
        self.assertIn("00:00:04,000 --> 00:00:07,250", render_srt(entries).decode())
        self.assertIn("Câu chuyện bắt đầu.", render_webvtt(entries).decode())

    def test_optional_piper_render_records_verified_wav(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "vi_voice.onnx"
            model.write_bytes(b"test model")
            clips = [
                {
                    "clip_id": "clip_0001",
                    "duration_seconds": 4,
                    "voice_plan": {"segments": [{"text": "Xin chào."}]},
                }
            ]

            def fake_piper(arguments: list[str], **_: object) -> SimpleNamespace:
                output = Path(arguments[arguments.index("--output_file") + 1])
                with wave.open(str(output), "wb") as stream:
                    stream.setnchannels(1)
                    stream.setsampwidth(2)
                    stream.setframerate(22050)
                    stream.writeframes(b"\0\0" * 22050)
                return SimpleNamespace(returncode=0)

            with patch("ai_story.stage4.tts.subprocess.run", side_effect=fake_piper):
                records = render_tts(
                    root,
                    clips,
                    model,
                    {"runtime_path": "piper"},
                )

            self.assertEqual(records[0]["path"], "audio/clip_0001.wav")
            self.assertEqual(records[0]["duration_seconds"], 1.0)
            self.assertEqual(records[0]["sample_rate"], 22050)
            self.assertEqual(records[0]["status"], "RENDERED")
            self.assertTrue((root / records[0]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
