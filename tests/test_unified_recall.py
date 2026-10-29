"""统一检索与成长写入的单元测试：四处存储各自独立，坏一个不能拖垮其他。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fatfish_core import growth, recall


KB_SCHEMA = """
CREATE TABLE kb (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL DEFAULT '未分类',
  name TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT ''
)
"""

GROUP_SCHEMA = """
CREATE TABLE messages (
  id TEXT PRIMARY KEY, group_id TEXT NOT NULL, platform_message_id TEXT NOT NULL,
  sender_id TEXT NOT NULL, sender_name TEXT NOT NULL DEFAULT '', sent_at INTEGER,
  received_at INTEGER, type TEXT, text TEXT, thread_id TEXT, reply_to_message_id TEXT
)
"""


class RecallSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_kb(self, rows):
        path = self.root / "kb.sqlite"
        conn = sqlite3.connect(path)
        conn.executescript(KB_SCHEMA)
        conn.executemany(
            "INSERT INTO kb (category, name, summary, payload, tags, source, updated_at)"
            " VALUES (?,?,?,?,?,?,?)", rows,
        )
        conn.commit()
        conn.close()
        return path

    def test_kb_hits_name_summary_and_payload(self):
        path = self.make_kb([
            ("技能", "苹果派配方", "低筋面粉加苹果", "正文", "烘焙", "手册", "2026-10-30 01:00:00"),
            ("技能", "别的条目", "没有关键词", "苹果派在正文里", "", "手册", "2026-10-29 01:00:00"),
        ])
        with patch.dict("os.environ", {"FATFISH_KB_DB": str(path)}):
            hits = recall.kb_rows("苹果派", 5)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["source"], "kb")

    def test_kb_missing_file_is_empty_not_crash(self):
        with patch.dict("os.environ", {"FATFISH_KB_DB": str(self.root / "nope.sqlite")}):
            self.assertEqual(recall.kb_rows("苹果", 5), [])

    def test_obsidian_matches_name_and_body(self):
        vault = self.root / "vault"
        (vault / "00-Home").mkdir(parents=True)
        (vault / "00-Home" / "苹果派.md").write_text("标题命中，正文不含关键词", encoding="utf-8")
        (vault / "日记.md").write_text("今天做了苹果派，很好吃", encoding="utf-8")
        with patch.dict("os.environ", {"FATFISH_OBSIDIAN_VAULT": str(vault)}):
            hits = recall.obsidian_rows("苹果派", 5)
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(hit["source"] == "obsidian" for hit in hits))

    def test_group_rows_escape_wildcards(self):
        path = self.root / "group.sqlite"
        conn = sqlite3.connect(path)
        conn.executescript(GROUP_SCHEMA)
        conn.execute(
            "INSERT INTO messages (id, group_id, platform_message_id, sender_id, sender_name, sent_at, text)"
            " VALUES ('m1','g1','p1','u1','老大',1,'进度 100% 完成')")
        conn.execute(
            "INSERT INTO messages (id, group_id, platform_message_id, sender_id, sender_name, sent_at, text)"
            " VALUES ('m2','g1','p2','u2','别人',2,'进度 1000 完成')")
        conn.commit()
        conn.close()
        with patch.dict("os.environ", {"FATFISH_GROUP_DB": str(path)}):
            hits = recall.group_rows("100%", 5)
        self.assertEqual([hit["sender"] for hit in hits], ["老大"])

    def test_recall_all_collects_every_source_and_isolates_failure(self):
        kb = self.make_kb([("技能", "苹果派", "摘要", "正文", "", "手册", "2026-10-30 01:00:00")])
        vault = self.root / "vault"
        vault.mkdir()
        (vault / "笔记.md").write_text("苹果派", encoding="utf-8")

        def boom(_term, _limit):
            raise RuntimeError("memory down")

        with patch.dict("os.environ", {"FATFISH_KB_DB": str(kb), "FATFISH_OBSIDIAN_VAULT": str(vault),
                                       "FATFISH_GROUP_DB": str(self.root / "none.sqlite")}):
            result = recall.recall_all("苹果派", 3, memory_search=boom)
        self.assertEqual(result["sources"]["kb"]["count"], 1)
        self.assertEqual(result["sources"]["obsidian"]["count"], 1)
        self.assertEqual(result["sources"]["group"]["count"], 0)
        self.assertEqual(result["sources"]["memory"]["error"], "RuntimeError")

    def test_empty_query_rejected(self):
        self.assertIn("error", recall.recall_all("   ", 3))


class RecordingStore:
    def __init__(self):
        self.calls = []

    def remember(self, content, **kwargs):
        self.calls.append((content, kwargs))
        return 7


class GrowthWriteTests(unittest.TestCase):
    def test_record_capability_stores_only_controlled_labels(self):
        store = RecordingStore()
        row_id = growth.record_capability(store, "tts", "failed", stage="generate", error_code="network")
        self.assertEqual(row_id, 7)
        content, kwargs = store.calls[0]
        self.assertIn("语音表达", content)
        self.assertEqual(kwargs["kind"], "capability")
        self.assertEqual(kwargs["meta"], {"capability": "tts", "status": "failed",
                                          "stage": "generate", "error_code": "network"})

    def test_unknown_label_rejected_and_free_text_dropped(self):
        store = RecordingStore()
        with self.assertRaises(ValueError):
            growth.record_capability(store, "free-form 乱七八糟", "success")
        growth.record_capability(store, "tts", "success", error_code="sk-secret-泄露")
        self.assertEqual(store.calls[0][1]["meta"]["error_code"], "")


if __name__ == "__main__":
    unittest.main()
