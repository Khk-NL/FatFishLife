from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from fatfish_bili import PublishError, PublishMeta, get_status, publish
from fatfish_bili.cli import main


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.video = self.root / "完成的视频.mp4"
        self.cover = self.video.with_suffix(".cover.jpg")
        self.report = self.video.with_suffix(".result.json")
        self.video.write_bytes(b"unit-test-video")
        self.cover.write_bytes(b"unit-test-cover")
        self.report_data = {"schema_version": 1, "status": "completed", "video": str(self.video),
                            "cover": str(self.cover), "report": str(self.report)}
        self.write_report()
        # Test-only IDs verify argument plumbing, not real account categories.
        self.meta = PublishMeta("测试标题", "第一行\n第二行", ("测试标签", "第二标签"), zone=9991, tid=9992)
        self.meta_path = self.root / "meta.json"
        self.meta_path.write_text(json.dumps(self.meta.as_dict(), ensure_ascii=False), encoding="utf-8")

    def write_report(self):
        self.report.write_text(json.dumps(self.report_data), encoding="utf-8")

    @staticmethod
    def success(data):
        return Mock(returncode=0, stdout=json.dumps({"ok": True, "data": data}), stderr="")

    @patch("fatfish_bili.publisher.subprocess.run")
    def test_default_draft_is_reviewable_and_never_runs_external_command(self, run):
        result = publish(self.video, self.meta, bili_exe="not-installed-bili")
        run.assert_not_called()
        self.assertEqual(result.status, "draft")
        self.assertIsNone(result.bvid)
        data = json.loads(result.draft.read_text(encoding="utf-8"))
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["render_report"], str(self.report))
        self.assertEqual(data["metadata"], self.meta.as_dict())
        self.assertEqual(data["cover"], str(self.cover))
        self.assertEqual(data["command"][1:3], ["upload", "video"])

    @patch("fatfish_bili.publisher.subprocess.run")
    def test_only_completed_matching_render_report_is_accepted(self, run):
        for update in ({"status": "failed"}, {"status": "rendering"}, {"schema_version": 2},
                       {"video": str(self.root / "other.mp4")}, {"report": str(self.root / "other.result.json")}):
            original = self.report_data.copy()
            with self.subTest(update=update):
                self.report_data.update(update)
                self.write_report()
                with self.assertRaises(PublishError):
                    publish(self.video, self.meta, dry_run=False)
            self.report_data = original
        run.assert_not_called()

    @patch("fatfish_bili.publisher.subprocess.run")
    def test_missing_empty_or_malformed_artifacts_fail_before_upload(self, run):
        for path in (self.report, self.video, self.cover):
            original = path.read_bytes()
            with self.subTest(path=path):
                path.unlink()
                with self.assertRaises(PublishError):
                    publish(self.video, self.meta, dry_run=False)
                path.write_bytes(b"")
                with self.assertRaises(PublishError):
                    publish(self.video, self.meta, dry_run=False)
                path.write_bytes(original)
        self.report.write_text("not json", encoding="utf-8")
        with self.assertRaises(PublishError):
            publish(self.video, self.meta)
        run.assert_not_called()

    def test_metadata_is_explicit_and_validated_without_guessing_categories(self):
        for update in ({"title": ""}, {"title": "字" * 81}, {"description": None}, {"description": "字" * 2001},
                       {"tags": "不是数组"}, {"tags": []}, {"tags": ["a,b"]}, {"zone": 0}, {"tid": True}, {"private": "false"}):
            with self.subTest(update=update), self.assertRaises(PublishError):
                PublishMeta.from_dict({**self.meta.as_dict(), **update})
        with self.assertRaises(PublishError):
            PublishMeta.from_dict({"title": "没有分区和标签"})

    @patch("fatfish_bili.publisher.subprocess.run")
    def test_explicit_confirmation_passes_exact_upload_arguments_and_records_submission(self, run):
        run.return_value = self.success({"bvid": "BV1xx411c7mD", "aid": 123})
        result = publish(self.video, self.meta, dry_run=False, bili_exe="bili-test", bili_home=self.root / "profile")
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["bili-test", "upload", "video", str(self.video)])
        self.assertEqual(command[command.index("--desc") + 1], "第一行\n第二行")
        self.assertEqual(command[command.index("--zone") + 1], "9991")
        self.assertEqual(command[command.index("--tid") + 1], "9992")
        self.assertEqual([command[index + 1] for index, item in enumerate(command) if item == "--tag"], ["测试标签", "第二标签"])
        self.assertIn("--ai-declare", command)
        self.assertNotIn("--dry-run", command)
        self.assertEqual(run.call_args.kwargs["env"]["BILI_CLI_HOME"], str(self.root / "profile"))
        self.assertEqual(result.status, "submitted")
        receipt = json.loads(result.receipt.read_text(encoding="utf-8"))
        self.assertEqual(receipt["review_status"], "pending")
        self.assertFalse(receipt["dry_run"])
        self.assertEqual(receipt["bvid"], "BV1xx411c7mD")

    @patch("fatfish_bili.publisher.subprocess.run")
    def test_cli_error_or_missing_submission_id_is_never_reported_as_success(self, run):
        responses = [
            Mock(returncode=1, stdout=json.dumps({"ok": False, "error": {"code": "not_logged_in", "message": "请先登录"}})),
            Mock(returncode=0, stdout=json.dumps({"ok": False, "error": {"message": "上传失败"}})),
            Mock(returncode=1, stdout=json.dumps({"ok": True, "data": {"bvid": "BV1xx411c7mD"}})),
            Mock(returncode=0, stdout="not json"),
            self.success({"aid": 123}),
            self.success({"bvid": "BV1xx411c7mD", "dry_run": True}),
        ]
        for response in responses:
            with self.subTest(response=response):
                run.return_value = response
                with self.assertRaises(PublishError):
                    publish(self.video, self.meta, dry_run=False)
                self.assertFalse(self.video.with_suffix(".publish-draft.result.json").exists())

    @patch("fatfish_bili.publisher.subprocess.run")
    def test_process_timeout_and_missing_executable_are_explicit_errors(self, run):
        for error in (subprocess.TimeoutExpired(["bili"], 1), FileNotFoundError("missing bili")):
            with self.subTest(error=error):
                run.side_effect = error
                with self.assertRaises(PublishError):
                    publish(self.video, self.meta, dry_run=False)

    @patch("fatfish_bili.publisher.subprocess.run")
    def test_cli_defaults_to_draft_and_confirm_is_required_to_submit(self, run):
        args = ["publish", str(self.video), "--meta", str(self.meta_path)]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "draft")
        run.assert_not_called()
        run.return_value = self.success({"bvid": "BV1xx411c7mD"})
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args + ["--confirm"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "submitted")
        self.assertEqual(run.call_count, 1)

    @patch("fatfish_bili.publisher.subprocess.run")
    def test_cli_failure_returns_nonzero_without_success_output(self, run):
        run.return_value = Mock(returncode=1, stdout='{"ok":false,"error":{"message":"认证失败"}}')
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(["publish", str(self.video), "--meta", str(self.meta_path), "--confirm"])
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("认证失败", error.getvalue())

    @patch("fatfish_bili.publisher.subprocess.run")
    def test_status_uses_read_only_status_command(self, run):
        run.return_value = self.success({"published": False, "state_desc": "审核中"})
        result = get_status("BV1xx411c7mD", bili_exe="bili-test")
        self.assertEqual(run.call_args.args[0], ["bili-test", "upload", "status", "BV1xx411c7mD"])
        self.assertFalse(result["published"])

    def test_draft_cannot_overwrite_render_report(self):
        original = self.report.read_bytes()
        for draft in (self.report, self.video.with_suffix(".json")):
            with self.subTest(draft=draft), self.assertRaises(PublishError):
                publish(self.video, self.meta, draft=draft)
        self.assertEqual(self.report.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
