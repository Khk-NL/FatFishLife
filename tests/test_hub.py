"""fatfish_core.hub 与中枢命令行的单元测试；全部用临时库，不碰真实 memory.db。"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fatfish_core import hub
from fatfish_core.knowledge_graph import KnowledgeGraph

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "dsh" / "service" / "fatfish_hub_cli.py"

SCHEMA = """
CREATE TABLE events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL,
  session TEXT, actor TEXT, content TEXT NOT NULL, created_at TEXT NOT NULL, meta TEXT
);
CREATE TABLE journals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL, content TEXT NOT NULL, source TEXT, created_at TEXT NOT NULL
);
CREATE TABLE mood(scope TEXT PRIMARY KEY, value REAL NOT NULL, reason TEXT DEFAULT '', updated_at REAL NOT NULL);
"""

LORE_TEXT = "能天使和德克萨斯是企鹅物流的成员。蕾缪安是能天使的姐姐。"
LORE_DATA = {
    "entities": [
        {"name": name, "type": kind}
        for name, kind in [("能天使", "人物"), ("德克萨斯", "人物"), ("企鹅物流", "组织"), ("蕾缪安", "人物")]
    ],
    "relations": [
        {"subject": "能天使", "predicate": "所属组织", "object": "企鹅物流",
         "evidence": "能天使和德克萨斯是企鹅物流的成员", "confidence": .95},
        {"subject": "能天使", "predicate": "姐姐", "object": "蕾缪安",
         "evidence": "蕾缪安是能天使的姐姐", "confidence": 1},
    ],
}


class HubTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "memory.db"
        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()
        patcher = patch.dict(os.environ, {
            "FATFISH_MEMORY_DB": str(self.db),
            "FATFISH_LORE_COLLECTION": "lore",
            "FATFISH_SERVICE_READONLY": "0",
            "FATFISH_HUB_WRITE": "0",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def pin_today(self, value="2026-10-30"):
        patcher = patch.object(hub, "_today", return_value=value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def add_event(self, created_at, content="消息", *, scope="public", kind="message", platform="qq"):
        conn = sqlite3.connect(self.db)
        with conn:
            conn.execute(
                "INSERT INTO events(platform,scope,kind,session,actor,content,created_at,meta)"
                " VALUES(?,?,?,NULL,NULL,?,?,NULL)",
                (platform, scope, kind, content, created_at),
            )
        conn.close()

    def journal_rows(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute("SELECT day,content,source FROM journals ORDER BY id").fetchall()
        finally:
            conn.close()


class MoodTests(HubTestBase):
    def test_mood_get_defaults_to_neutral(self):
        state = hub.mood_get()
        self.assertEqual(state["scope"], "global")
        self.assertEqual(state["value"], 50.0)
        self.assertEqual(state["label"], "挺平静")
        self.assertIsNone(state["updated_at"])
        self.assertIn("现在心情", state["description"])
        self.assertNotIn("error", state)

    def test_mood_nudge_clamps_delta_and_truncates_reason(self):
        result = hub.mood_nudge(9, "夸" * 200)
        self.assertEqual(result["value"], 51.0)
        self.assertEqual(result["label"], "挺平静")
        self.assertEqual(len(result["reason"]), 80)
        self.assertIsInstance(result["updated_at"], float)
        self.assertEqual(hub.mood_get()["value"], 51.0)
        hub.mood_nudge(-9)
        self.assertEqual(hub.mood_get()["value"], 50.0)

    def test_mood_nudge_keeps_scopes_separate(self):
        hub.mood_nudge(1, "私聊夸了", scope="private:u1")
        self.assertEqual(hub.mood_get()["value"], 50.0)
        self.assertEqual(hub.mood_get("private:u1")["value"], 51.0)

    def test_mood_get_decays_toward_neutral(self):
        updated = time.time() - 3 * 3600
        conn = sqlite3.connect(self.db)
        with conn:
            conn.execute(
                "INSERT INTO mood(scope,value,reason,updated_at) VALUES('global',90,'很兴奋',?)", (updated,)
            )
        conn.close()
        state = hub.mood_get()
        self.assertAlmostEqual(state["value"], 72.0, delta=0.2)
        self.assertEqual(state["label"], "心情不错")

    def test_mood_get_missing_db_degrades_without_creating_file(self):
        missing = self.root / "none" / "memory.db"
        with patch.dict(os.environ, {"FATFISH_MEMORY_DB": str(missing)}):
            state = hub.mood_get()
        self.assertEqual(state["value"], 50.0)
        self.assertIn("error", state)
        self.assertFalse(missing.exists())


class LoreTests(HubTestBase):
    def test_lore_search_returns_document_provenance(self):
        KnowledgeGraph(self.db).replace(
            "lore", "relations.md", "关系资料", LORE_TEXT, LORE_DATA,
            source_url="https://prts.wiki/w/能天使",
        )
        result = hub.lore_search("能天使的姐姐是谁")
        self.assertEqual(result["count"], 1)
        item = result["items"][0]
        self.assertEqual(item["title"], "关系资料")
        self.assertEqual(item["source"], "relations.md")
        self.assertEqual(item["source_url"], "https://prts.wiki/w/能天使")
        self.assertEqual(item["collection"], "lore")
        self.assertEqual(len(item["digest"]), 64)

    def test_lore_search_empty_query_and_missing_db(self):
        self.assertEqual(hub.lore_search("  "), {"count": 0, "items": []})
        missing = self.root / "absent" / "memory.db"
        with patch.dict(os.environ, {"FATFISH_MEMORY_DB": str(missing)}):
            result = hub.lore_search("能天使")
        self.assertEqual(result["count"], 0)
        self.assertIn("error", result)
        self.assertFalse(missing.exists())

    def test_lore_context_returns_evidence_with_sources(self):
        KnowledgeGraph(self.db).replace(
            "lore", "relations.md", "关系资料", LORE_TEXT, LORE_DATA,
            source_url="https://prts.wiki/w/能天使",
        )
        result = hub.lore_context("能天使的姐姐是谁", max_chars=300)
        self.assertIn("【知识图谱证据】", result["context"])
        self.assertIn("蕾缪安", result["context"])
        self.assertIn("prts.wiki", result["context"])
        self.assertLessEqual(len(result["context"]), 300)
        self.assertEqual(hub.lore_context("")["context"], "")

    def test_lore_collection_override(self):
        KnowledgeGraph(self.db).replace(
            "private_obsidian", "private.md", "私人笔记", LORE_TEXT, LORE_DATA
        )
        self.assertEqual(hub.lore_search("能天使")["count"], 0)
        with patch.dict(os.environ, {"FATFISH_LORE_COLLECTION": "private_obsidian"}):
            self.assertEqual(hub.lore_search("能天使")["count"], 1)


class JournalTests(HubTestBase):
    def test_journal_write_same_day_same_source_overwrites(self):
        first = hub.journal_write("2026-10-30", "第一版")
        second = hub.journal_write("2026-10-30", "第二版", source="dsh")
        self.assertTrue(first["ok"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.journal_rows(), [("2026-10-30", "第二版", "dsh")])
        third = hub.journal_write("2026-10-30", "日记版", source="diary")
        self.assertNotEqual(second["id"], third["id"])
        self.assertEqual(len(self.journal_rows()), 2)

    def test_journal_write_truncates_content(self):
        hub.journal_write("2026-10-30", "字" * 9000)
        self.assertEqual(len(self.journal_rows()[0][1]), 8000)

    def test_journal_write_validates_day_and_content(self):
        for bad in ("2026/10/30", "2026-13-01", "2026-02-30", "", "20261030", "2026-10-3"):
            with self.subTest(day=bad), self.assertRaises(ValueError):
                hub.journal_write(bad, "内容")
        with self.assertRaises(ValueError):
            hub.journal_write("2026-10-30", "   ")
        self.assertEqual(self.journal_rows(), [])

    def test_journal_write_missing_db_raises_file_not_found(self):
        missing = self.root / "none" / "memory.db"
        with patch.dict(os.environ, {"FATFISH_MEMORY_DB": str(missing)}):
            with self.assertRaises(FileNotFoundError):
                hub.journal_write("2026-10-30", "内容")
        self.assertFalse(missing.exists())

    def test_journal_recent_orders_desc_and_limits_window(self):
        self.pin_today()
        for day in ("2026-10-01", "2026-10-24", "2026-10-29", "2026-10-30"):
            hub.journal_write(day, f"{day} 内容")
        result = hub.journal_recent(days=7)
        self.assertEqual(result["count"], 3)
        self.assertEqual(
            [item["day"] for item in result["items"]],
            ["2026-10-30", "2026-10-29", "2026-10-24"],
        )
        self.assertEqual(result["items"][0]["content"], "2026-10-30 内容")


class DigestTests(HubTestBase):
    def test_day_digest_counts_scopes_kinds_and_samples(self):
        self.add_event("2026-10-30T01:00:00+08:00", "公开消息一", scope="public", kind="message")
        self.add_event("2026-10-30T02:00:00+08:00", "公开回复", scope="public", kind="reply")
        self.add_event("2026-10-30T03:00:00+08:00", "私聊消息", scope="private", kind="message")
        self.add_event("2026-10-29T23:00:00+08:00", "昨天消息")
        digest = hub.day_digest("2026-10-30")
        self.assertEqual(digest["events"], 3)
        self.assertEqual(digest["scopes"], {"public": 2, "private": 1})
        self.assertEqual(digest["kinds"], {"message": 2, "reply": 1})
        self.assertEqual(len(digest["samples"]), 3)
        self.assertIn("公开消息一", digest["samples"])
        self.assertTrue(all(len(sample) <= 80 for sample in digest["samples"]))

    def test_day_digest_uses_stored_date(self):
        self.add_event("2026-10-29T16:00:00+00:00", "跨时区消息")
        self.assertEqual(hub.day_digest("2026-10-29")["events"], 1)
        self.assertEqual(hub.day_digest("2026-10-30")["events"], 0)

    def test_day_digest_invalid_day_raises(self):
        for bad in ("2026-1-01", "", "2026-13-01", "2026-02-30", "2026-10-30T00:00:00"):
            with self.subTest(day=bad), self.assertRaises(ValueError):
                hub.day_digest(bad)

    def test_day_digest_missing_db_returns_empty_with_error(self):
        missing = self.root / "absent" / "memory.db"
        with patch.dict(os.environ, {"FATFISH_MEMORY_DB": str(missing)}):
            digest = hub.day_digest("2026-10-30")
        self.assertEqual(digest["events"], 0)
        self.assertEqual(digest["scopes"], {})
        self.assertIn("error", digest)


class StyleTermsTests(HubTestBase):
    def test_style_terms_extracts_phrases_from_window_only(self):
        self.pin_today()
        for index in range(6):
            self.add_event(f"2026-10-01T0{index}:00:00+08:00", "苹果派真好吃")
        self.assertEqual(hub.style_terms(days=7)["count"], 0)
        for index in range(6):
            self.add_event(f"2026-10-25T0{index}:00:00+08:00", "苹果派真好吃")
        result = hub.style_terms(days=7, limit=8)
        self.assertGreater(result["count"], 0)
        self.assertTrue(any("苹果" in term for term in result["terms"]))
        self.assertEqual(result["count"], len(result["terms"]))

    def test_style_terms_missing_db_returns_empty_with_error(self):
        missing = self.root / "absent" / "memory.db"
        with patch.dict(os.environ, {"FATFISH_MEMORY_DB": str(missing)}):
            result = hub.style_terms()
        self.assertEqual(result["count"], 0)
        self.assertIn("error", result)


class ResilienceTests(HubTestBase):
    def test_read_functions_do_not_raise_on_corrupt_database(self):
        broken = self.root / "broken.db"
        broken.write_bytes(b"not a sqlite database")
        with patch.dict(os.environ, {"FATFISH_MEMORY_DB": str(broken)}):
            results = [
                hub.mood_get(),
                hub.lore_search("能天使"),
                hub.lore_context("能天使"),
                hub.journal_recent(),
                hub.day_digest("2026-10-30"),
                hub.style_terms(),
            ]
        for result in results:
            self.assertIn("error", result)


class McpToolTests(HubTestBase):
    def setUp(self):
        super().setUp()
        from dsh.service import fatfish_memory_mcp as service

        self.service = service

    def test_write_tools_respect_hub_write_gate(self):
        with patch.dict(os.environ, {"FATFISH_HUB_WRITE": "0", "FATFISH_SERVICE_READONLY": "0"}):
            journal = json.loads(self.service.journal_write("2026-10-30", "未授权"))
            nudge = json.loads(self.service.mood_nudge(1, "未授权"))
        self.assertFalse(journal["ok"])
        self.assertIn("FATFISH_HUB_WRITE", journal["error"])
        self.assertFalse(nudge["ok"])
        self.assertIn("FATFISH_HUB_WRITE", nudge["error"])
        self.assertEqual(self.journal_rows(), [])

    def test_tools_delegate_to_hub_and_return_json(self):
        self.pin_today()
        with patch.dict(os.environ, {"FATFISH_HUB_WRITE": "1", "FATFISH_SERVICE_READONLY": "0"}):
            written = json.loads(self.service.journal_write("2026-10-30", "通过 MCP 写入"))
            digest = json.loads(self.service.day_digest("2026-10-30"))
            mood = json.loads(self.service.mood_get())
            terms = json.loads(self.service.style_terms())
        self.assertTrue(written["ok"])
        self.assertEqual(digest["day"], "2026-10-30")
        self.assertEqual(mood["scope"], "global")
        self.assertIn("terms", terms)

    def test_write_tools_turn_database_errors_into_json(self):
        broken = self.root / "broken.db"
        broken.write_bytes(b"not a sqlite database")
        with patch.dict(os.environ, {
            "FATFISH_MEMORY_DB": str(broken),
            "FATFISH_HUB_WRITE": "1",
            "FATFISH_SERVICE_READONLY": "0",
        }):
            journal = json.loads(self.service.journal_write("2026-10-30", "损坏库"))
            nudge = json.loads(self.service.mood_nudge(1, "损坏库"))
        self.assertFalse(journal["ok"])
        self.assertIn("error", journal)
        self.assertFalse(nudge["ok"])
        self.assertIn("error", nudge)


class CliTests(HubTestBase):
    def run_cli(self, *args):
        env = {
            **os.environ,
            "FATFISH_MEMORY_DB": str(self.db),
            "FATFISH_LORE_COLLECTION": "lore",
            "PYTHONIOENCODING": "utf-8",
        }
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=str(ROOT), capture_output=True, env=env, timeout=120,
        )

    def test_cli_prints_utf8_json(self):
        self.add_event("2026-10-30T02:00:00+08:00", "中文消息")
        run = self.run_cli("day-digest", "--day", "2026-10-30")
        self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))
        payload = json.loads(run.stdout.decode("utf-8"))
        self.assertEqual(payload["day"], "2026-10-30")
        self.assertEqual(payload["events"], 1)
        mood = self.run_cli("mood-get")
        self.assertEqual(json.loads(mood.stdout.decode("utf-8"))["label"], "挺平静")

    def test_cli_invalid_day_exits_nonzero_with_stderr(self):
        run = self.run_cli("day-digest", "--day", "2026-13-01")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(run.stdout, b"")
        self.assertIn("day", run.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
