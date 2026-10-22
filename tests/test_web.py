"""Exercise the local editor HTTP contract and real FFmpeg export paths."""

import array
import base64
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer

from fatfish_video.renderer import find_tools, probe_media
from fatfish_video.web_server import EditorHandler, ROOT, process_export


class QuietHandler(EditorHandler):
    def log_message(self, *args):
        pass


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join()

    def test_catalog_images_and_static_page(self):
        with urllib.request.urlopen(self.url + "/api/characters") as response:
            catalog = json.load(response)["characters"]
        self.assertGreater(len(catalog), 50)
        for item in catalog:
            self.assertNotIn("{", item["name"])
            for key in ("icon", "preview"):
                path = ROOT / item[key].lstrip("/")
                self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), str(path))
        with urllib.request.urlopen(self.url) as response:
            page = response.read().decode("utf-8")
        self.assertIn("角色拼贴工作台", page)
        import re
        for icon in set(re.findall(r'/assets/icons/[^" ]+', page)):
            self.assertTrue((ROOT / icon.lstrip("/")).is_file(), icon)

    def test_audio_range_and_file_boundaries(self):
        request = urllib.request.Request(self.url + "/assets/music/demo-original.wav", headers={"Range": "bytes=0-11"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(len(response.read()), 12)
            self.assertTrue(response.headers["Content-Range"].startswith("bytes 0-11/"))
        for path in ("/assets/../README.md", "/media/../../README.md"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

    def test_invalid_request_returns_error(self):
        for body, headers, code in ((b"not json", {}, 400), (b"{}", {"Origin": "https://example.com"}, 403)):
            request = urllib.request.Request(self.url + "/api/render", data=body, headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, code)
            self.assertIn("error", json.loads(error.exception.read()))
            error.exception.close()


class WebExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg, cls.ffprobe = find_tools()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fatfish-web-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        audio = self.root / "tone.wav"
        with wave.open(str(audio), "wb") as target:
            target.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            target.writeframes(array.array("h", (int(10000 * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(48000))).tobytes())
        self.payload = {"music": {"data": base64.b64encode(audio.read_bytes()).decode("ascii")}, "speed": 1.5, "volume": 0.65}

    def test_audio_export_speed_and_pitch(self):
        for preserve, frequency in ((False, 660), (True, 440)):
            self.payload["preserve_pitch"] = preserve
            result = process_export(self.payload, "audio", self.root)
            with wave.open(str(self.root / "outputs/web" / result["filename"]), "rb") as output:
                self.assertEqual((output.getframerate(), output.getnchannels()), (48000, 2))
                self.assertAlmostEqual(output.getnframes() / 48000, 2 / 1.5, delta=.05)
                samples = array.array("h", output.readframes(output.getnframes()))[::2]
            samples = samples[9600:24000]
            crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
            self.assertAlmostEqual(crossings / (len(samples) / 48000), frequency, delta=10)

    def test_video_export_reuses_engine_and_metadata(self):
        self.payload.update(image={"data": base64.b64encode((ROOT / "assets/web/kobe-face.png").read_bytes()).decode("ascii")},
                            caption="网页生成测试", duration=2, background="#5AA6CF")
        result = process_export(self.payload, "video", self.root)
        metadata = probe_media(self.root / "outputs/web" / result["filename"], self.ffprobe)
        video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"], video["avg_frame_rate"], video["nb_frames"]), (1920, 1080, "30/1", "60"))
        self.assertTrue(any(s["codec_type"] == "audio" for s in metadata["streams"]))
        self.assertEqual(result["duration"], 2)
        self.assertTrue((self.root / "outputs/web" / Path(result["cover"]).name).is_file())

    def test_invalid_export_data_is_rejected(self):
        self.payload["speed"] = 0
        with self.assertRaisesRegex(ValueError, "speed"):
            process_export(self.payload, "audio", self.root)
        with self.assertRaisesRegex(ValueError, "PNG"):
            process_export({"image": {"data": "aGVsbG8="}}, "video", self.root)


if __name__ == "__main__":
    unittest.main()
