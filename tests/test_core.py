from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fatfish_core import MemoryStore, RuntimeStore, SeenStore, StateStore, build_context, read_offline, resolve_shared_db


class SharedCoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / "memory.db"

    def test_state_json_migrates_once_into_the_existing_memory_database(self):
        memory = MemoryStore(self.db)
        memory.remember("主人私有笔记", scope="private", kind="note")
        legacy = self.root / "offline"
        legacy.mkdir()
        original = {"manual": "on", "usage": {"hour": "2026-10-23T14", "count": 7}, "daily_apple_pie": {"day": "2026-10-23", "status": "sent"}}
        source = legacy / "state.json"
        source.write_text(json.dumps(original), encoding="utf-8")
        state = StateStore(legacy, db_path=self.db)
        self.assertEqual(state.manual, "on")
        self.assertEqual(state.usage_count("2026-10-23T14"), 7)
        self.assertEqual(state.daily_apple_pie_state()["status"], "sent")
        state.set_manual("off")
        reloaded = StateStore(legacy, db_path=self.db)
        self.assertEqual(reloaded.manual, "off")
        self.assertEqual(json.loads(source.read_text(encoding="utf-8")), original)
        self.assertEqual(memory.recall("主人私有笔记", scopes=("private",))[0]["content"], "主人私有笔记")
        self.assertEqual(build_context(memory, scopes=("public",)), "")

    def test_signal_and_seen_share_one_database_without_entering_memory(self):
        memory = MemoryStore(self.db)
        offline = StateStore(self.root / "offline", db_path=self.db)
        resume = datetime(2026, 10, 23, 18, tzinfo=timezone.utc)
        offline.publish_offline(True, reason="high_cost", resume_at=resume)
        self.assertEqual(read_offline(self.db)["resume_at"], resume.isoformat(timespec="seconds"))
        seen = SeenStore(self.db)
        seen.save({"dm:private-id", "comment:public-id"})
        self.assertEqual(SeenStore(self.db).load(), {"dm:private-id", "comment:public-id"})
        self.assertEqual(memory.stats()["events"], 0)
        self.assertEqual(build_context(memory, scopes=("public", "private")), "")

    def test_external_resume_reaches_an_existing_state_store(self):
        state = StateStore(self.root / 'offline', db_path=self.db)
        state.set_manual('on')
        state.set_silent(True)
        external = RuntimeStore(self.db)
        data = external.get('offline', 'control')
        data.update(manual='off', silent=False)
        external.set('offline', 'control', data)
        self.assertFalse(state.silent)
        self.assertEqual(state.manual, 'off')

    def test_usage_save_cannot_put_old_control_flags_back(self):
        state = StateStore(self.root / 'offline', db_path=self.db)
        state.set_silent(True)
        second = StateStore(self.root / 'other', db_path=self.db)
        second.set_silent(False)
        second.set_manual('off')
        state.bump_usage('2026-10-28T19')
        saved = RuntimeStore(self.db).get('offline', 'control')
        self.assertFalse(saved['silent'])
        self.assertEqual(saved['manual'], 'off')
        self.assertEqual(saved['usage']['count'], 1)
        state.set_silent(True)
        self.assertTrue(second.silent)
        self.assertEqual(second.manual, 'off')

    def test_seen_import_keeps_legacy_file_but_never_replays_deleted_preview(self):
        source = self.root / "seen.json"
        source.write_text(json.dumps({"keys": ["preview:123", "comment:456"]}), encoding="utf-8")
        first = SeenStore(self.db, legacy_path=source)
        self.assertEqual(first.load(), {"preview:123", "comment:456"})
        first.save({"comment:456"})
        self.assertEqual(SeenStore(self.db, legacy_path=source).load(), {"comment:456"})
        self.assertTrue(source.is_file())

    def test_namespaces_are_isolated_and_seen_is_bounded(self):
        one = SeenStore(self.db)
        two = SeenStore(self.db, namespace="other")
        saved = one.save({f"key:{index:04}" for index in range(801)})
        self.assertEqual(len(saved), 500)
        self.assertEqual(two.load(), set())
        runtime = RuntimeStore(self.db)
        runtime.set("other", "signal", {"offline": False})
        self.assertEqual(read_offline(self.db), {})

    def test_shared_path_respects_existing_setting_and_deployment_overrides(self):
        config = self.root / "config"
        config.mkdir()
        configured = self.root / "custom" / "old-memory.db"
        (config / "astrbot_plugin_fatfish_memory_config.json").write_text(json.dumps({"db_path": str(configured)}), encoding="utf-8")
        with patch.dict(os.environ, {"FATFISH_DATA_DIR": "", "FATFISH_MEMORY_DB": ""}):
            self.assertEqual(resolve_shared_db(self.root), configured)
            self.assertEqual(resolve_shared_db(self.root, self.db), self.db)
        override = self.root / "override.db"
        with patch.dict(os.environ, {"FATFISH_MEMORY_DB": str(override)}):
            self.assertEqual(resolve_shared_db(self.root, configured), override)
        with patch.dict(os.environ, {"FATFISH_DATA_DIR": str(self.root), "FATFISH_MEMORY_DB": ""}):
            self.assertEqual(resolve_shared_db(self.root / "not-used"), configured)

    def test_compatibility_imports_are_the_same_core_types(self):
        from bots.astrbot_plugin_fatfish_memory.store import MemoryStore as LegacyMemory
        from bots.astrbot_plugin_fatfish_memory.context import build_context as legacy_context
        from bots.astrbot_plugin_fatfish_offline.state import StateStore as LegacyState
        self.assertIs(LegacyMemory, MemoryStore)
        self.assertIs(legacy_context, build_context)
        self.assertIs(LegacyState, StateStore)


if __name__ == "__main__":
    unittest.main()
