from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fatfish_story.client import MockProvider
from fatfish_story.options import StoryOptions
from fatfish_story.pipeline import StoryError, _fit_durations, _split_caption, _visible_length, generate_project
from fatfish_video.project import load_project
from fatfish_video.renderer import render_project

ROOT = Path(__file__).resolve().parent.parent


class BadProvider:
    name = "bad"

    def __init__(self, payload: dict):
        self.payload = payload

    def complete_json(self, system: str, user: str) -> dict:
        return self.payload


class RetryProvider:
    name = "retry"

    def __init__(self):
        self.calls = 0

    def complete_json(self, system: str, user: str) -> dict:
        self.calls += 1
        if self.calls == 1:
            return {"title": "bad", "scenes": []}
        return MockProvider().complete_json(system, user)


class StoryTests(unittest.TestCase):
    def test_mock_generates_valid_thirty_second_project(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = generate_project(
                StoryOptions(topic="新角色上线", duration=30, provider="mock", config_dir=Path(directory))
            )
            self.assertEqual(generated.project.duration, 30.0)
            self.assertEqual(generated.project.frames, 900)
            self.assertEqual(len(generated.project.scenes), 4)
            self.assertTrue(generated.config_path.is_file())
            self.assertTrue(generated.config_path.with_suffix(".meta.json").is_file())
            self.assertEqual(load_project(generated.config_path).title, generated.project.title)
            for scene in generated.project.scenes:
                self.assertTrue(scene.captions)
                self.assertLessEqual(len(scene.captions), 2)

    def test_caption_is_split_under_limit(self):
        text = "这是一条明显超过三十六个汉字的字幕文案，需要被自动拆成两段，避免渲染层因为超过三行而直接报错，也避免字幕盖住角色。"
        self.assertGreater(_visible_length(text), 36)
        pieces = _split_caption(text)
        self.assertGreaterEqual(len(pieces), 2)
        for piece in pieces:
            self.assertLessEqual(_visible_length(piece), 36)

    def test_short_caption_stays_single(self):
        self.assertEqual(_split_caption("孩子们，开局了。"), ["孩子们，开局了。"])

    def test_durations_fit_target_and_scene_bounds(self):
        fitted = _fit_durations([1, 1, 1], 30, 30)
        self.assertAlmostEqual(sum(fitted), 30.0, places=2)
        self.assertTrue(all(3 <= value <= 15 for value in fitted))
        with self.assertRaises(StoryError):
            _fit_durations([1, 1], 40, 30)

    def test_unknown_character_is_rejected(self):
        payload = {
            "title": "坏数据",
            "template": "single",
            "scenes": [{"duration": 30, "characters": ["不存在的角色"], "caption": "测试"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(StoryError):
                generate_project(
                    StoryOptions(topic="测试", duration=30, provider="mock", config_dir=Path(directory)),
                    provider=BadProvider(payload),
                )

    def test_retry_after_invalid_storyboard(self):
        provider = RetryProvider()
        with tempfile.TemporaryDirectory() as directory:
            generated = generate_project(
                StoryOptions(topic="测试重试", duration=30, config_dir=Path(directory), max_attempts=2),
                provider=provider,
            )
            self.assertEqual(provider.calls, 2)
            self.assertEqual(generated.metadata["attempts"], 2)

    def test_news_without_panel_degrades_to_single(self):
        payload = {
            "title": "资讯",
            "template": "news",
            "scenes": [{"duration": 15, "characters": ["1001"], "caption": "没有配图"}, {"duration": 15, "characters": ["1001"], "caption": "降级处理"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            generated = generate_project(
                StoryOptions(topic="资讯", duration=30, provider="mock", config_dir=Path(directory)),
                provider=BadProvider(payload),
            )
            self.assertEqual(generated.project.scenes[0].template, "single")
            self.assertTrue(any("降级" in item for item in generated.metadata["warnings"]))

    def test_rendered_story_video(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = generate_project(
                StoryOptions(topic="渲染测试", duration=30, provider="mock", config_dir=Path(directory))
            )
            result = render_project(generated.project, output=Path(directory) / "story.mp4")
            self.assertEqual(result.frames, 900)
            self.assertEqual((result.width, result.height, result.fps), (1920, 1080, 30))
            self.assertTrue(result.video.is_file())
            self.assertTrue(json.loads(result.report.read_text(encoding="utf-8"))["status"] == "completed")


if __name__ == "__main__":
    unittest.main()
