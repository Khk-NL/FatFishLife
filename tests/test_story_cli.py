from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fatfish_story.cli import main
from fatfish_story.client import ProviderError
from fatfish_video.renderer import RenderError


class StoryCliTests(unittest.TestCase):
    def test_missing_provider_credentials_returns_readable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors), patch("fatfish_story.pipeline.build_provider", side_effect=ProviderError("缺少 DEEPSEEK_API_KEY")):
                code = main(["create", "--topic", "鉴权错误", "--out", str(Path(directory) / "story.json")])
            self.assertEqual(code, 1)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("缺少 DEEPSEEK_API_KEY", errors.getvalue())
            self.assertNotIn("Traceback", errors.getvalue())

    def test_no_render_reports_only_the_storyboard_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "story.json"
            output = io.StringIO()
            with redirect_stdout(output), patch("fatfish_story.cli.render_project") as render:
                code = main(["create", "--topic", "分镜测试", "--provider", "mock", "--out", str(path), "--no-render"])
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["stage"], "storyboard")
            self.assertNotIn("render", result)
            render.assert_not_called()
            self.assertFalse(path.with_suffix(".mp4").exists())

    def test_render_failure_does_not_report_completed_video(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "story.json"
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors), patch("fatfish_story.cli.render_project", side_effect=RenderError("测试编码失败")):
                code = main(["create", "--topic", "编码失败测试", "--provider", "mock", "--out", str(path)])
            self.assertEqual(code, 1)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("测试编码失败", errors.getvalue())
            self.assertFalse(path.with_suffix(".result.json").exists())
            self.assertEqual(json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))["stage"], "storyboard")


if __name__ == "__main__":
    unittest.main()
