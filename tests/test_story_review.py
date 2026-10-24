from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fatfish_bili.publisher import PublishError
from fatfish_story.review import ReviewError, ReviewQueue


class StoryReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.video, self.cover = self.root / "film.mp4", self.root / "cover.jpg"
        self.report = self.root / "film.result.json"
        self.video.write_bytes(b"rendered video")
        self.cover.write_bytes(b"rendered cover")
        self.report.write_text(json.dumps({
            "schema_version": 1, "status": "completed", "video": str(self.video),
            "cover": str(self.cover), "report": str(self.report),
        }), encoding="utf-8")
        self.queue = ReviewQueue(self.root / "reviews")
        self.identity = {"owner": "owner", "session": "qq:FriendMessage:owner"}
        self.meta = {"title": "公开选题", "description": "简介", "tags": ["测试"], "zone": 1, "tid": 17, "ai_declare": True}
        self.publisher = patch("fatfish_story.review.publish", return_value=Mock(as_dict=lambda: {"status": "submitted", "url": "https://www.bilibili.com/video/BV1234567890"}))
        self.upload = self.publisher.start()
        self.addCleanup(self.publisher.stop)

    def create(self):
        return self.queue.create(self.video, self.meta, topic="公开选题", **self.identity)

    def ready(self):
        row = self.create()
        self.queue.mark_preview(row["id"], **self.identity)
        return row

    def test_create_never_uploads(self):
        self.assertEqual(self.create()["status"], "pending_preview")
        self.upload.assert_not_called()

    def test_owner_and_session_both_required(self):
        row = self.ready()
        for identity in ({"owner": "stranger", "session": self.identity["session"]}, {"owner": "owner", "session": "another session"}):
            with self.assertRaises(ReviewError):
                self.queue.submit(row["id"], **identity)
        self.upload.assert_not_called()

    def test_cannot_approve_before_preview(self):
        with self.assertRaisesRegex(ReviewError, "预览"):
            self.queue.submit(self.create()["id"], **self.identity)
        self.upload.assert_not_called()

    def test_only_approved_revision_is_uploaded_once(self):
        row = self.ready()
        result = self.queue.submit(row["id"], bili_exe="fake-bili", bili_home="fake-home", **self.identity)
        self.assertEqual(result["status"], "submitted")
        args, kwargs = self.upload.call_args
        self.assertEqual(args[0], str(self.video))
        self.assertEqual(args[1].as_dict()["title"], self.meta["title"])
        self.assertFalse(kwargs["dry_run"])
        with self.assertRaises(ReviewError):
            ReviewQueue(self.queue.directory).submit(row["id"], **self.identity)
        self.assertEqual(self.upload.call_count, 1)

    def test_changes_in_any_artifact_prevent_upload(self):
        for attr in ("video", "cover", "report"):
            with self.subTest(artifact=attr):
                path = getattr(self, attr)
                original = path.read_bytes()
                row = self.ready()
                path.write_bytes(original + b"changed")
                with self.assertRaisesRegex(ReviewError, "变化"):
                    self.queue.submit(row["id"], **self.identity)
                path.write_bytes(original)
        self.upload.assert_not_called()

    def test_metadata_changes_require_new_identifier_and_preview(self):
        row = self.ready()
        updated = self.queue.revise(row["id"], {**self.meta, "title": "更新标题"}, **self.identity)
        self.assertNotEqual(row["id"], updated["id"])
        for identifier in (row["id"], updated["id"]):
            with self.assertRaises(ReviewError):
                self.queue.submit(identifier, **self.identity)
        self.queue.mark_preview(updated["id"], **self.identity)
        self.queue.submit(updated["id"], **self.identity)
        self.assertEqual(self.upload.call_args.args[1].title, "更新标题")

    def test_interrupted_submission_is_durable_and_never_auto_retried(self):
        row = self.ready()
        self.upload.side_effect = PublishError("timeout")
        with self.assertRaisesRegex(ReviewError, "未确认"):
            self.queue.submit(row["id"], **self.identity)
        restarted = ReviewQueue(self.queue.directory)
        self.assertEqual(restarted.get(row["id"], **self.identity)["status"], "uncertain")
        with self.assertRaises(ReviewError):
            restarted.submit(row["id"], **self.identity)
        self.assertEqual(self.upload.call_count, 1)

    def test_process_exit_during_submission_leaves_nonretryable_state(self):
        row = self.ready()
        self.upload.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.queue.submit(row["id"], **self.identity)
        self.assertEqual(self.queue.get(row["id"], **self.identity)["status"], "uncertain")

    def test_inflight_record_after_process_crash_does_not_retry(self):
        row = self.ready()
        row["status"] = "submitting"
        self.queue._save(row)
        with self.assertRaises(ReviewError):
            ReviewQueue(self.queue.directory).submit(row["id"], **self.identity)
        self.upload.assert_not_called()

    def test_missing_partition_still_allows_preview_but_not_upload(self):
        self.meta["zone"] = 0
        row = self.ready()
        self.assertIn("zone", row["metadata_error"])
        with self.assertRaises(PublishError):
            self.queue.submit(row["id"], **self.identity)
        self.upload.assert_not_called()

    def test_cancel_prevents_submission(self):
        row = self.ready()
        self.queue.cancel(row["id"], **self.identity)
        with self.assertRaises(ReviewError):
            self.queue.submit(row["id"], **self.identity)
        self.upload.assert_not_called()

    def test_rejects_storyboard_only_and_mismatched_video(self):
        self.report.write_text(json.dumps({"schema_version": 1, "stage": "storyboard", "status": "completed"}), encoding="utf-8")
        with self.assertRaises(PublishError):
            self.create()

    def test_rejects_path_traversal_identifier(self):
        with self.assertRaises(ReviewError):
            self.queue.get("../film", **self.identity)


if __name__ == "__main__":
    unittest.main()
