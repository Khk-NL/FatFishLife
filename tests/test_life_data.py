from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("life_data", ROOT / "bots/astrbot_plugin_fatfish_life/data.py")
data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(data)


class DailyDataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "memory.db"
        self.start, self.end = data.beijing_day_bounds("2026-10-23")
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript("""
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY, platform TEXT, scope TEXT, kind TEXT,
                    session TEXT, actor TEXT, content TEXT, created_at TEXT, meta TEXT
                );
                CREATE TABLE journals (
                    id INTEGER PRIMARY KEY, day TEXT, content TEXT, source TEXT, created_at TEXT
                );
                CREATE TABLE provider_stats (
                    id INTEGER PRIMARY KEY, created_at TEXT,
                    token_input_other INTEGER, token_input_cached INTEGER, token_output INTEGER
                );
            """)

    def tearDown(self):
        self.directory.cleanup()

    def event(self, content, when, *, scope="public", platform="qq", kind="message", meta=None):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO events(platform,scope,kind,content,created_at,meta) VALUES (?,?,?,?,?,?)",
                (platform, scope, kind, content, when, meta),
            )

    def usage(self, when, uncached, cached, output):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO provider_stats(created_at,token_input_other,token_input_cached,token_output) VALUES (?,?,?,?)",
                (when, uncached, cached, output),
            )

    def test_beijing_bounds_are_aware_and_accept_date(self):
        self.assertEqual(data.beijing_day_bounds(date(2026, 10, 23)), (self.start, self.end))
        self.assertEqual(self.start.astimezone(timezone.utc).isoformat(), "2026-10-22T16:00:00+00:00")
        self.assertEqual(self.end.astimezone(timezone.utc).isoformat(), "2026-10-23T16:00:00+00:00")

    def test_event_window_normalizes_offsets_and_is_half_open(self):
        self.event("before", "2026-10-22T23:59:59+08:00")
        self.event("start", "2026-10-22T16:00:00+00:00")
        self.event("middle", "2026-10-23T12:00:00+08:00")
        self.event("end", "2026-10-23T16:00:00+00:00")
        rows = data.events_between(self.path, self.start, self.end)
        self.assertEqual([row["content"] for row in rows], ["start", "middle"])

    def test_latest_limit_uses_actual_time_then_returns_ascending(self):
        self.event("latest", "2026-10-23T15:00:00+08:00")
        self.event("oldest", "2026-10-23T01:00:00+08:00")
        self.event("middle", "2026-10-23T03:00:00+08:00")
        rows = data.events_between(self.path, self.start, self.end, limit=2)
        self.assertEqual([row["content"] for row in rows], ["middle", "latest"])

    def test_scope_is_explicit_and_empty_does_not_expose_private_rows(self):
        self.event("public", "2026-10-23T10:00:00+08:00")
        self.event("private", "2026-10-23T10:01:00+08:00", scope="private")
        self.assertEqual([row["content"] for row in data.events_between(self.path, self.start, self.end)], ["public"])
        self.assertEqual(data.events_between(self.path, self.start, self.end, scopes=()), [])
        self.assertEqual(
            [row["content"] for row in data.events_between(self.path, self.start, self.end, scopes=("private",))],
            ["private"],
        )
        with self.assertRaises(ValueError):
            data.events_between(self.path, self.start, self.end, scopes=("invalid",))

    def test_legacy_public_inbox_is_always_excluded(self):
        self.event("legacy", "2026-10-23T10:00:00+08:00", platform="bilibili", kind="inbox")
        self.event("private inbox", "2026-10-23T10:01:00+08:00", platform="bilibili", kind="inbox", scope="private")
        rows = data.events_between(self.path, self.start, self.end, scopes=("public", "private"))
        self.assertEqual([row["content"] for row in rows], ["private inbox"])

    def test_metadata_is_always_a_dict(self):
        for index, metadata in enumerate((json.dumps({"tag": "actual"}), "broken", "[]", None)):
            self.event(str(index), "2026-10-23T10:00:00+08:00", meta=metadata)
        rows = data.events_between(self.path, self.start, self.end)
        self.assertEqual([row["meta"] for row in rows], [{"tag": "actual"}, {}, {}, {}])

    def test_missing_activity_database_is_not_created(self):
        missing = self.path.with_name("missing.db")
        self.assertEqual(data.events_between(missing, self.start, self.end), [])
        self.assertFalse(missing.exists())

    def test_empty_window_and_zero_limit_have_no_rows(self):
        self.event("actual", "2026-10-23T10:00:00+08:00")
        self.assertEqual(data.events_between(self.path, self.start, self.end, limit=0), [])
        self.assertEqual(data.events_between(self.path, self.end, self.start), [])

    def test_naive_query_times_are_rejected(self):
        with self.assertRaises(ValueError):
            data.events_between(self.path, datetime(2026, 10, 23), self.end)
        with self.assertRaises(ValueError):
            data.read_usage(self.path, self.start, datetime(2026, 10, 24))

    def test_daily_journal_upsert_does_not_replace_manual_or_other_sources(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO journals(day,content,source,created_at) VALUES (?,?,?,?)", ("2026-10-23", "manual", "", "original"))
        first = data.upsert_daily_journal(self.path, "2026-10-23", "first")
        second = data.upsert_daily_journal(self.path, date(2026, 10, 23), "updated")
        other = data.upsert_daily_journal(self.path, "2026-10-23", "separate", source="other")
        self.assertEqual(first, second)
        self.assertNotEqual(other, first)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            rows = connection.execute("SELECT content,source FROM journals ORDER BY id").fetchall()
        self.assertEqual(rows, [("manual", ""), ("updated", "daily-reflection"), ("separate", "other")])

    def test_journal_sources_cannot_be_empty(self):
        with self.assertRaises(ValueError):
            data.upsert_daily_journal(self.path, "2026-10-23", "generated", source="")
        with self.assertRaises(ValueError):
            data.upsert_daily_journal(self.path, "2026-10-23", " ")

    def test_usage_converts_beijing_day_to_utc_naive_storage(self):
        self.usage("2026-10-22 15:59:59.000000", 900, 900, 900)
        self.usage("2026-10-22 16:00:00.000000", 10, 20, 30)
        self.usage("2026-10-23 15:59:59.999999", 1, 2, 3)
        self.usage("2026-10-23 16:00:00.000000", 900, 900, 900)
        result = data.read_usage(self.path, self.start, self.end)
        self.assertEqual(result, {"available": True, "calls": 2, "input_other": 11, "input_cached": 22, "output": 33, "total": 66})

    def test_usage_zero_is_available_but_missing_database_or_table_is_not(self):
        zero = data.read_usage(self.path, self.start, self.end)
        self.assertTrue(zero["available"])
        self.assertEqual(zero["total"], 0)
        self.assertEqual(zero["calls"], 0)
        missing = self.path.with_name("missing.db")
        self.assertFalse(data.read_usage(missing, self.start, self.end)["available"])
        self.assertFalse(missing.exists())
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("DROP TABLE provider_stats")
        self.assertFalse(data.read_usage(self.path, self.start, self.end)["available"])


class RecordUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_only_reported_usage_and_provider_metadata(self):
        database = SimpleNamespace(insert_provider_stat=AsyncMock())
        context = SimpleNamespace(get_db=lambda: database)
        provider = SimpleNamespace(meta=lambda: SimpleNamespace(id="actual-id"), get_model=lambda: "actual-model")
        response = SimpleNamespace(role="assistant", usage=SimpleNamespace(input_other=2, input_cached=3, output=4))
        await data.record_usage(context, provider, response, umo="synthetic-session", agent_type="fatfish-reflection")
        database.insert_provider_stat.assert_awaited_once_with(
            umo="synthetic-session", provider_id="actual-id", provider_model="actual-model",
            status="completed", stats={"token_usage": {"input_other": 2, "input_cached": 3, "output": 4}},
            agent_type="fatfish-reflection",
        )

    async def test_missing_usage_is_not_estimated(self):
        database = SimpleNamespace(insert_provider_stat=AsyncMock())
        context = SimpleNamespace(get_db=lambda: database)
        await data.record_usage(context, None, SimpleNamespace(usage=None), umo="unused", agent_type="test")
        database.insert_provider_stat.assert_not_awaited()

    async def test_database_failure_is_not_hidden(self):
        database = SimpleNamespace(insert_provider_stat=AsyncMock(side_effect=RuntimeError("write failed")))
        context = SimpleNamespace(get_db=lambda: database)
        provider = SimpleNamespace(meta=lambda: SimpleNamespace(id="id"), get_model=lambda: "model")
        response = SimpleNamespace(role="err", usage=SimpleNamespace(input_other=0, input_cached=0, output=0))
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            await data.record_usage(context, provider, response, umo="test", agent_type="test")
        self.assertEqual(database.insert_provider_stat.await_args.kwargs["status"], "error")


if __name__ == "__main__":
    unittest.main()
