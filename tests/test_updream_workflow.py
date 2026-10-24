import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from fatfish_story.updream import save_brief, import_export
from fatfish_story.review import ReviewQueue
from fatfish_video.renderer import find_tools, RenderError


class UpdreamWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_brief_keeps_narrative_and_never_claims_generated_video(self):
        data = {"title":"雨夜来信", "logline":"一封信改变了选择", "characters":["能天使，红发光环"],
                "visual_style":"动画，雨夜街道", "sound_plan":"雨声、克制配乐", "shots":[
                    {"duration":5,"action":"跑过街角","dialogue":"等一下","visual_prompt":"跟拍奔跑动作"} for _ in range(3)]}
        job = save_brief(self.root, "公开故事", data, owner="owner", session="qq:FriendMessage:owner")
        self.assertEqual(job["status"], "awaiting_updream")
        self.assertFalse(job["generated"])
        self.assertFalse(job["uploaded"])
        self.assertIn("跟拍奔跑动作", Path(job["path"]).read_text(encoding="utf-8"))

    def test_invalid_export_never_reaches_review(self):
        video = self.root / "bad.mp4"; video.write_bytes(b"not video")
        with self.assertRaises(RenderError): import_export(video, self.root / "imports")
        self.assertFalse(list(self.root.rglob("*.result.json")))

    def test_real_decode_and_cover_allow_review_but_still_require_owner_approval(self):
        ffmpeg, _ = find_tools(); source = self.root / "export.mp4"
        subprocess.run([str(ffmpeg),"-v","error","-f","lavfi","-i","color=c=blue:s=320x180:r=30:d=0.2",
                        "-c:v","libx264","-pix_fmt","yuv420p",str(source)], check=True,capture_output=True)
        media = import_export(source, self.root / "imports")
        self.assertTrue(media["validation"]["fully_decoded"])
        self.assertFalse(media["origin_verified_by_platform"])
        queue = ReviewQueue(self.root / "reviews")
        row = queue.create(media["video"], {"title":"作品","description":"简介","tags":["动画"],"zone":1,"tid":17},
                           owner="owner",session="qq:FriendMessage:owner",topic="话题",report=media["report"])
        self.assertEqual(row["status"], "pending_preview")
        self.assertTrue(source.exists())
        self.assertTrue(Path(row["cover"]).stat().st_size)
