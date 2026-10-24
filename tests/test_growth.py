from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from fatfish_core.growth import CAPABILITIES, capability_summary, record_capability, tool_outcome
from fatfish_core.memory import MemoryStore


class GrowthTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = MemoryStore(Path(directory.name) / "memory.db")

    def rows(self):
        with closing(sqlite3.connect(self.store.path)) as connection:
            connection.row_factory = sqlite3.Row
            return [{**dict(row), "meta": json.loads(row["meta"])} for row in connection.execute("SELECT * FROM events")]

    def test_all_capabilities_use_existing_private_events_without_secret_error_text(self):
        for capability in CAPABILITIES:
            record_capability(self.store, capability, "failed", stage="use", error_code="SECRET_TOKEN_AND_PRIVATE_CHAT")
        rows = self.rows()
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(row["scope"] == "private" and row["actor"] == "bot" for row in rows))
        self.assertNotIn("SECRET_TOKEN", json.dumps(rows))
        self.assertEqual(self.store.recent(scopes=("public",)), [])

    def test_invalid_labels_are_not_persisted(self):
        for args in (("SECRET", "success", "use"), ("tts", "SECRET", "use"), ("tts", "success", "SECRET")):
            with self.assertRaises(ValueError):
                record_capability(self.store, args[0], args[1], stage=args[2])
        self.assertEqual(self.rows(), [])

    def test_summary_distinguishes_setup_generation_delivery_and_unconfirmed(self):
        record_capability(self.store, "tts", "success", stage="setup")
        record_capability(self.store, "tts", "success", stage="generate")
        record_capability(self.store, "tts", "failed", stage="delivery", error_code="network")
        record_capability(self.store, "video_review", "blocked", stage="publish", error_code="awaiting_review")
        record_capability(self.store, "video_review", "uncertain", stage="delivery", error_code="unconfirmed")
        summary = capability_summary(self.rows())
        self.assertEqual(len(summary), 5)
        self.assertFalse(any(item["capability"] == "tts" and item["stage"] == "delivery" and item["status"] == "success" for item in summary))

    def test_summary_ignores_untrusted_text_and_public_or_unknown_metadata(self):
        trusted = {"kind": "capability", "scope": "private", "content": "PRIVATE_SECRET", "meta": {"capability": "tts", "status": "success", "stage": "generate", "secret": "SECRET"}}
        rows = [trusted, {**trusted, "scope": "public"}, {**trusted, "kind": "message"}, {**trusted, "meta": {"capability": "SECRET"}}]
        summary = capability_summary(rows)
        self.assertEqual(summary, [{"capability": "tts", "name": "语音表达", "status": "success", "stage": "generate", "count": 1}])

    def test_tool_completion_does_not_turn_empty_or_error_response_into_success(self):
        for result in (None, {}, SimpleNamespace(content=[])):
            self.assertEqual(tool_outcome(result), ("uncertain", "unconfirmed"))
        for result in (
            {"isError": True, "content": [{"type": "text", "text": "PRIVATE_SECRET"}]},
            {"structuredContent": {"ok": False, "error": "SECRET"}},
            {"content": [{"type": "text", "text": "错误：密钥 SECRET 不可用"}]},
            {"content": [{"type": "text", "text": '{"ok":false,"private":"SECRET"}'}]},
        ):
            self.assertEqual(tool_outcome(result), ("failed", "service_error"))
        self.assertEqual(tool_outcome({"content": [{"type": "text", "text": "找到公开资料"}]}), ("success", ""))


if __name__ == "__main__":
    unittest.main()
