import importlib.util
from contextlib import closing
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from fatfish_core import MemoryStore

SPEC = importlib.util.spec_from_file_location("bili_study", Path(__file__).parents[1] / "bots/astrbot_plugin_fatfish_bili/study.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BiliStudyTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_comments_can_be_retried_and_do_not_claim_growth(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            run = AsyncMock(side_effect=[{"ok": True, "data": {"items": [{"bvid": "BVtest"}]}}, {"ok": False}])
            seen = set()
            result = await MODULE.study_tag(run, store, "test", seen=seen)
            self.assertFalse(result["ok"])
            self.assertNotIn("BVtest", seen)
            rows = store.recent(limit=10, scopes=("private",))
            with closing(sqlite3.connect(store.path)) as connection:
                meta = json.loads(connection.execute("SELECT meta FROM events WHERE kind='capability'").fetchone()[0])
            self.assertEqual(meta["status"], "failed")

    async def test_real_comments_record_success_and_no_private_text_in_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            run = AsyncMock(side_effect=[{"ok": True, "data": {"items": [{"bvid": "BVtest"}]}},
                                       {"ok": True, "data": {"title":"真实标题", "tags":["明日方舟"],
                                        "transcript":{"source":"subtitle:zh", "text":"已有字幕正文"},
                                        "hot_comments": [{"content": "test comment"}]}}])
            result = await MODULE.study_tag(run, store, "test", seen=set())
            self.assertTrue(result["ok"])
            self.assertEqual(result["comment_count"], 1)
            rows = store.recent(limit=10, scopes=("private",))
            with closing(sqlite3.connect(store.path)) as connection:
                meta = json.loads(connection.execute("SELECT meta FROM events WHERE kind='capability'").fetchone()[0])
            self.assertEqual(meta["status"], "success")
            self.assertNotIn("test comment", rows[0]["content"])
            reading = store.recent(scopes=("public",), kinds=("video",))[0]
            self.assertIn("读取B站文字资料", reading["content"])
            self.assertIn("已有字幕正文", reading["content"])
            self.assertNotIn("看了", reading["content"])
            args = run.await_args.args
            self.assertEqual(args[args.index("--frames") + 1], "0")
            self.assertEqual(args[args.index("--transcript") + 1], "subtitle")

    async def test_captionless_video_uses_other_text_without_fallback_or_extra_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.db")
            run = AsyncMock(side_effect=[{"ok": True, "data": {"items": [{"bvid": "BVtest"}]}},
                                        {"ok": True, "data": {"title":"只有标题", "desc":"公开简介", "tags":["标签"],
                                         "transcript":{"source":None,"text":"","hint":"自动下载转写"}, "hot_comments":[]}}])
            result = await MODULE.study_tag(run, store, "test", seen=set())
            self.assertEqual(result["text_reads"], 1)
            self.assertEqual(run.await_count, 2)
            self.assertIn("公开简介", store.recent(scopes=("public",), kinds=("video",))[0]["content"])


if __name__ == "__main__":
    unittest.main()
