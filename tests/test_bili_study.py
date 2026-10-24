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
                                       {"ok": True, "data": {"items": [{"content": "test comment"}]}}])
            result = await MODULE.study_tag(run, store, "test", seen=set())
            self.assertTrue(result["ok"])
            self.assertEqual(result["comment_count"], 1)
            rows = store.recent(limit=10, scopes=("private",))
            with closing(sqlite3.connect(store.path)) as connection:
                meta = json.loads(connection.execute("SELECT meta FROM events WHERE kind='capability'").fetchone()[0])
            self.assertEqual(meta["status"], "success")
            self.assertNotIn("test comment", rows[0]["content"])


if __name__ == "__main__":
    unittest.main()
