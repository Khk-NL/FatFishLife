from datetime import datetime, timedelta, timezone
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fatfish_core.costs import BEIJING, format_cost_report, read_cost_report


class CostReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "usage.db"
        self.start = datetime(2026, 10, 24, tzinfo=BEIJING)
        self.end = self.start + timedelta(days=1)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE provider_stats(created_at TEXT, provider_id TEXT, provider_model TEXT, "
                       "agent_type TEXT, status TEXT, token_input_other INTEGER, token_input_cached INTEGER, "
                       "token_output INTEGER, umo TEXT)")

    def add(self, uncached=1_000_000, cached=1_000_000, output=1_000_000, *,
            when="2026-10-24T01:00:00", model="deepseek-flash", provider="deepseek/chat", agent="internal"):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO provider_stats VALUES(?,?,?,?,?,?,?,?,?)",
                       (when, provider, model, agent, "completed", uncached, cached, output, "PRIVATE_SESSION_NEVER_EXPOSE"))

    def report(self, **kwargs):
        return read_cost_report(self.path, self.start, self.end, **kwargs)

    def test_cost_range_uses_actual_token_classes_and_input_only_cache_ratio(self):
        self.add()
        result = self.report()
        total = result["totals"]
        self.assertEqual(total["known_cost_cny_low"], 5.02)
        self.assertEqual(total["known_cost_cny_high"], 10.04)
        self.assertEqual(total["cache_hit_ratio"], .5)
        self.assertEqual(total["total_tokens"], 3_000_000)
        self.assertFalse(result["pricing"]["is_bill"])
        self.assertNotIn("PRIVATE_SESSION", json.dumps(result))

    def test_unknown_models_are_explicitly_unpriced_instead_of_reported_as_free(self):
        self.add(model="unknown-price-model")
        result = self.report()
        self.assertEqual(result["totals"]["unpriced_calls"], 1)
        self.assertFalse(result["totals"]["estimate_complete"])
        self.assertIsNone(result["totals"]["estimate_cny"])
        self.assertIn("1 次未定价", format_cost_report(result))

    def test_local_free_api_accounting_requires_explicit_provider_identity(self):
        self.add(model="MiniCPM5-2B", provider="local-context")
        self.assertEqual(self.report()["totals"]["unpriced_calls"], 1)
        total = self.report(local_provider_ids=["local-context"])["totals"]
        self.assertEqual(total["local_calls"], 1)
        self.assertEqual(total["estimate_cny"], {"low": 0.0, "high": 0.0})

    def test_missing_database_table_and_empty_window_are_not_account_zero_claims(self):
        missing = read_cost_report(self.path.parent / "missing.db", self.start, self.end)
        self.assertFalse(missing["available"])
        self.assertIsNone(missing["totals"]["estimate_cny"])
        self.assertIn("不能当作零消费", format_cost_report(missing))
        empty = self.report()
        self.assertTrue(empty["available"])
        self.assertFalse(empty["has_statistics"])
        self.assertIsNone(empty["totals"]["estimate_cny"])
        self.assertIn("不代表账户没有消费", format_cost_report(empty))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DROP TABLE provider_stats")
        self.assertEqual(self.report()["unavailable_reason"], "provider_stats_schema_missing")

    def test_beijing_half_open_window_and_hour_buckets(self):
        self.add(when="2026-10-23T15:59:59")
        self.add(when="2026-10-23T16:00:00")
        self.add(when="2026-10-24T16:00:00")
        result = self.report()
        self.assertEqual(result["totals"]["calls"], 1)
        self.assertEqual(result["by_hour"][0]["hour"], "2026-10-24T00:00:00+08:00")

    def test_invalid_counters_are_not_silently_included_as_zero_cost_usage(self):
        self.add(uncached=None)
        self.add(output=-100)
        total = self.report()["totals"]
        self.assertEqual(total["calls"], 2)
        self.assertEqual(total["missing_usage_calls"], 2)
        self.assertIsNone(total["estimate_cny"])
        self.assertIsNone(total["cache_hit_ratio"])

    def test_groups_and_alerts_preserve_agent_type_without_private_session_data(self):
        self.add(agent="native")
        self.add(uncached=0, cached=0, output=100, model="deepseek-v4-pro", agent="fatfish_style")
        result = self.report(warning_cny=4)
        self.assertEqual({x["agent_type"] for x in result["by_model"]}, {"native", "fatfish_style"})
        self.assertEqual(result["alerts"][0]["code"], "recorded_cost_above_threshold")
        self.assertNotIn("umo", json.dumps(result))

    def test_reading_does_not_change_source_database(self):
        self.add()
        original = self.path.read_bytes()
        self.report()
        self.assertEqual(self.path.read_bytes(), original)

    def test_window_and_threshold_validation(self):
        with self.assertRaises(ValueError):read_cost_report(self.path, self.end, self.start)
        with self.assertRaises(ValueError):read_cost_report(self.path, self.start.replace(tzinfo=None), self.end)
        with self.assertRaises(ValueError):self.report(warning_cny=float("nan"))


if __name__ == "__main__":
    unittest.main()
