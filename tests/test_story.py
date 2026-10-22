from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fatfish_story.client import MockProvider, ProviderError, _loads_json_object
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
            self.assertEqual(generated.metadata["stage"], "storyboard")
            self.assertEqual(Path(generated.metadata["face_source"]).name, "kobe-original.png")
            self.assertTrue(all(asset.path.suffix == ".png" and asset.path.parent.name.endswith(".assets") for asset in generated.project.assets.values()))
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

    def test_malformed_model_json_is_retried_but_provider_errors_are_not(self):
        provider = MockProvider()
        with tempfile.TemporaryDirectory() as directory:
            original = provider.complete_json
            calls = []
            def complete(system, user):
                calls.append(user)
                return _loads_json_object("not json") if len(calls) == 1 else original(system, user)
            with patch.object(provider, "complete_json", side_effect=complete):
                generated = generate_project(StoryOptions(topic="测试", config_dir=Path(directory)), provider=provider)
            self.assertEqual(generated.metadata["attempts"], 2)
            self.assertEqual(len(calls), 2)
            with patch.object(provider, "complete_json", side_effect=ProviderError("网络失败")) as request:
                with self.assertRaisesRegex(StoryError, "网络失败"):
                    generate_project(StoryOptions(topic="网络错误", config_dir=Path(directory)), provider=provider)
                self.assertEqual(request.call_count, 1)

    def test_existing_config_is_protected_before_calling_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.json"
            path.write_text("USER_ORIGINAL_CONFIG", encoding="utf-8")
            provider = MockProvider()
            with patch.object(provider, "complete_json") as request:
                with self.assertRaisesRegex(StoryError, "文件已存在"):
                    generate_project(StoryOptions(topic="保护配置", config_path=path), provider=provider)
                request.assert_not_called()
            self.assertEqual(path.read_text(encoding="utf-8"), "USER_ORIGINAL_CONFIG")

    def test_invalid_replacement_keeps_existing_config_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.json"
            meta = path.with_suffix(".meta.json")
            path.write_text("USER_CONFIG", encoding="utf-8")
            meta.write_text("USER_METADATA", encoding="utf-8")
            with self.assertRaisesRegex(StoryError, "每个场景必须是对象"):
                generate_project(StoryOptions(topic="坏场景", config_path=path, overwrite=True), provider=BadProvider({"scenes": [None]}))
            self.assertEqual(path.read_text(encoding="utf-8"), "USER_CONFIG")
            self.assertEqual(meta.read_text(encoding="utf-8"), "USER_METADATA")
            self.assertEqual(list(Path(directory).glob(".story-*.json")), [])

    def test_requested_character_is_used_and_uncalibrated_character_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            generated = generate_project(StoryOptions(topic="选角", characters=("1005",), provider="mock", config_dir=Path(directory)))
            self.assertEqual(set(generated.project.assets), {"char1005"})
            with self.assertRaisesRegex(StoryError, "尚无校准的正面模型"):
                generate_project(StoryOptions(topic="不可自动贴脸", characters=("1001",), provider="mock", config_dir=Path(directory)))

    def test_news_without_panel_degrades_to_single(self):
        payload = {
            "title": "资讯",
            "template": "news",
            "scenes": [{"duration": 15, "characters": ["1006"], "caption": "没有配图"}, {"duration": 15, "characters": ["1006"], "caption": "降级处理"}],
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
