"""Native integration: encode/decode media, inspect pixels, check audio pitch."""

import array
import json
import math
import struct
import subprocess
import tempfile
import unittest
import wave
import zlib
from pathlib import Path

from fatfish_video import RenderError, render_project
from fatfish_video.renderer import find_font, find_tools, probe_media


def png(path, red, green, blue):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = (b"\0" + bytes((red, green, blue)) * 16) * 16
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class NativeRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg, cls.ffprobe = find_tools()
            find_font()
        except RenderError as exc:
            raise unittest.SkipTest(f"媒体集成测试需要 FFmpeg 与中文字体：{exc}")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fatfish-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        png(self.root / "角色.png", 20, 220, 40)
        png(self.root / "配图.png", 200, 20, 40)
        with wave.open(str(self.root / "tone.wav"), "wb") as audio:
            audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            audio.writeframes(array.array("h", (int(10000 * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(24000))).tobytes())
        self.data = {
            "schema_version": 1, "canvas": {"width": 320, "height": 180, "fps": 10},
            "assets": {"role": "角色.png", "panel": "配图.png"},
            "music": {"path": "tone.wav", "speed": 1.25, "pitch": "follow_speed", "loop": False, "fade_in": 0, "fade_out": 0},
            "scenes": [
                {"duration": 0.6, "roles": ["role"], "caption": "中文测试", "zoom": 0},
                {"duration": 0.6, "template": "news", "roles": ["role"], "panel": "panel", "caption": "第二个场景", "zoom": 0.02},
            ],
            "output": "成片.mp4",
        }

    def render(self):
        config = self.root / "项目.json"
        config.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        return render_project(config)

    def decode(self, video, arguments):
        return subprocess.run([str(self.ffmpeg), "-v", "error", *arguments, "-i", str(video),
                               "-f", "rawvideo", "-pix_fmt", "rgb24", "-frames:v", "1", "pipe:1"], check=True, capture_output=True).stdout

    def test_native_render_has_exact_timeline_pixels_chinese_and_report(self):
        result = self.render()
        metadata = probe_media(result.video, self.ffprobe)
        video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"], int(video["nb_frames"])), (320, 180, 12))
        self.assertEqual(video["avg_frame_rate"], "10/1")
        self.assertTrue(result.cover.is_file())
        self.assertIn("00:00:00,600 --> 00:00:01,200", result.subtitles.read_text(encoding="utf-8-sig"))
        self.assertEqual(json.loads(result.report.read_text(encoding="utf-8"))["status"], "completed")
        frame = self.decode(result.video, ["-ss", "0.2"])
        pixels = list(zip(frame[::3], frame[1::3], frame[2::3]))
        self.assertGreater(sum(g > 140 and r < 90 and b < 100 for r, g, b in pixels), 1000)
        self.assertGreater(sum(r > 170 and g > 160 and b < 100 for r, g, b in pixels[320 * 120:]), 10)
        second = self.decode(result.video, ["-ss", "0.8"])
        self.assertGreater(sum(r > 130 and g < 80 for r, g in zip(second[::3], second[1::3])), 1000)
        with self.assertRaisesRegex(RenderError, "输出已存在"):
            self.render()

    def test_audio_speed_modes_and_short_track_padding(self):
        for pitch, expected in (("follow_speed", 550), ("preserve", 440)):
            with self.subTest(pitch=pitch):
                self.data["music"]["pitch"] = pitch
                self.data["output"] = f"{pitch}.mp4"
                result = self.render()
                raw = subprocess.run([str(self.ffmpeg), "-v", "error", "-ss", "0.2", "-i", str(result.video),
                                      "-t", "0.3", "-vn", "-f", "s16le", "-ar", "24000", "-ac", "1", "pipe:1"], check=True, capture_output=True).stdout
                samples = array.array("h", raw)
                crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
                self.assertAlmostEqual(crossings / (len(samples) / 24000), expected, delta=15)
                audio = next(s for s in probe_media(result.video, self.ffprobe)["streams"] if s["codec_type"] == "audio")
                self.assertAlmostEqual(float(audio["duration"]), 1.2, delta=0.05)

    def test_failed_media_never_publishes_success_artifacts(self):
        self.data["assets"]["role"] = {"path": "角色.png", "crop": [0, 0, 999, 999]}
        with self.assertRaises(RenderError):
            self.render()
        self.assertFalse((self.root / "成片.mp4").exists())
        self.assertFalse((self.root / "成片.result.json").exists())
        self.assertFalse(list(self.root.glob(".fatfish-render-*")))

    def test_explicit_missing_executable_does_not_fall_back(self):
        with self.assertRaisesRegex(RenderError, "指定的 ffmpeg 不存在"):
            find_tools(self.root / "missing-ffmpeg.exe")


if __name__ == "__main__":
    unittest.main()
