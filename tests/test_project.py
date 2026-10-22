import json
import tempfile
import unittest
from pathlib import Path

from fatfish_video import ProjectError, load_project
from fatfish_video.renderer import _ass_text, wrap_caption


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "角色.png").write_bytes(b"fixture")
        self.config = self.root / "project.json"
        self.data = {"schema_version": 1, "assets": {"role": "角色.png"},
                     "scenes": [{"duration": 1.01, "roles": ["role"], "caption": "中文字幕"}]}

    def load(self):
        self.config.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8-sig")
        return load_project(self.config)

    def test_paths_are_relative_to_config_and_duration_quantized_to_frames(self):
        project = self.load()
        self.assertEqual(project.assets["role"].path, self.root / "角色.png")
        self.assertEqual((project.frames, project.duration), (30, 1))
        self.assertEqual((project.width, project.height, project.fps), (1920, 1080, 30))

    def test_caption_overlap_rejected(self):
        scene = self.data["scenes"][0]
        del scene["caption"]
        scene["captions"] = [{"start": 0, "end": 0.7, "text": "第一句"}, {"start": 0.5, "end": 1, "text": "第二句"}]
        with self.assertRaisesRegex(ProjectError, "不可重叠"):
            self.load()

    def test_caption_endpoint_uses_same_frame_rounding_as_scene(self):
        self.data["scenes"] = [{"duration": 1.01, "roles": ["role"],
                                "captions": [{"text": "整帧对齐", "start": 0, "end": 1.01}]}]
        project = self.load()
        self.assertEqual(project.scenes[0].captions[0].end, project.duration)

    def test_invalid_inputs_rejected(self):
        for value in (0, -1, True, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.data["scenes"][0]["duration"] = value
                with self.assertRaises(ProjectError):
                    self.load()

    def test_unknown_field_does_not_silently_ignore_typo(self):
        self.data["scenes"][0]["duraton"] = 3
        with self.assertRaisesRegex(ProjectError, "未知字段"):
            self.load()

    def test_news_requires_panel_and_reference_must_exist(self):
        self.data["template"] = "news"
        with self.assertRaisesRegex(ProjectError, "需要 panel"):
            self.load()
        self.data["scenes"][0]["panel"] = "missing"
        with self.assertRaisesRegex(ProjectError, "不存在的素材"):
            self.load()

    def test_boxes_stay_inside_canvas(self):
        self.data["scenes"][0]["roles"] = [{"asset": "role", "box": [0.8, 0, 0.5, 1]}]
        with self.assertRaisesRegex(ProjectError, "画布内"):
            self.load()

    def test_unicode_wrap_and_ass_literal_text(self):
        self.assertEqual(wrap_caption("孩子们ABC", 6), "孩子们\nABC")
        escaped = _ass_text("{\\pos(1,2)}\n孩子们")
        self.assertNotIn("{", escaped)
        self.assertNotIn("\\pos", escaped)
        self.assertIn("\\N孩子们", escaped)


if __name__ == "__main__":
    unittest.main()

