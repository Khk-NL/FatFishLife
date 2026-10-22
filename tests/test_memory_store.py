from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bots" / "astrbot_plugin_fatfish_memory"))

from store import MemoryStore  # noqa: E402


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.directory.name) / "memory.db")

    def tearDown(self):
        self.directory.cleanup()

    def test_private_rows_need_private_scope(self):
        self.store.remember("主人的私人安排", platform="qq", scope="private", actor="10001")
        self.store.remember("公开话题", platform="bilibili", scope="public")
        public = self.store.recall("", scopes=("public",))
        both = self.store.recall("", scopes=("public", "private"))
        self.assertEqual([row["content"] for row in public], ["公开话题"])
        self.assertEqual(len(both), 2)

    def test_owner_registration_and_lookup(self):
        self.store.add_owner("qq", "10001", "主人")
        self.store.add_owner("bilibili", "20002")
        self.assertTrue(self.store.is_owner("qq", "10001"))
        self.assertTrue(self.store.is_owner("bilibili", "20002"))
        self.assertFalse(self.store.is_owner("qq", "20002"))
        self.assertEqual(len(self.store.owners()), 2)

    def test_persona_roundtrip(self):
        self.store.set_persona("我是大肥鱼，说话短。")
        self.assertEqual(self.store.get_persona(), "我是大肥鱼，说话短。")
        self.store.set_persona("换个说法。")
        self.assertEqual(self.store.get_persona(), "换个说法。")

    def test_summary_and_journal(self):
        self.store.add_summary("今天聊了投稿。", period="2026-10-22")
        self.store.add_journal("主人不喜欢长回复。", day="2026-10-22")
        self.assertEqual(len(self.store.summaries()), 1)
        journals = self.store.journals()
        self.assertEqual(journals[0]["content"], "主人不喜欢长回复。")
        self.assertEqual(journals[0]["day"], "2026-10-22")

    def test_query_requires_all_tokens(self):
        self.store.remember("三月七 新皮肤", platform="bilibili", scope="public")
        self.store.remember("丹恒 新剧情", platform="bilibili", scope="public")
        self.assertEqual(len(self.store.recall("三月七", scopes=("public",))), 1)
        self.assertEqual(len(self.store.recall("三月七 皮肤", scopes=("public",))), 1)
        self.assertEqual(len(self.store.recall("三月七 剧情", scopes=("public",))), 0)

    def test_prune_removes_old_events_only(self):
        self.store.remember("新消息", platform="qq", scope="public")
        self.assertEqual(self.store.prune(90), 0)
        self.assertEqual(self.store.prune(0), 0)
        self.assertEqual(self.store.stats()["events"], 1)

    def test_empty_content_rejected(self):
        with self.assertRaises(ValueError):
            self.store.remember("   ", platform="qq", scope="public")
        with self.assertRaises(ValueError):
            self.store.remember("内容", platform="qq", scope="shared")

    def test_reopen_keeps_data(self):
        self.store.remember("写一条", platform="qq", scope="public")
        reopened = MemoryStore(self.store.path)
        self.assertEqual(reopened.stats()["events"], 1)


if __name__ == "__main__":
    unittest.main()
