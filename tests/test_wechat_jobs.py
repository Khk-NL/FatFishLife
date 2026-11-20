from datetime import date
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fatfish_core.memory import MemoryStore
from fatfish_core import wechat_jobs


class WechatJobsTest(unittest.TestCase):
    def test_report_filters_dates_and_sorts_by_confirmed_views(self):
        base = {"title": "样例", "pubdate": "2026-11-20T08:30:00+08:00"}
        rows = wechat_jobs.report_items([
            {**base, "bvid": "BV1abcdefgh1", "play": 65},
            {**base, "bvid": "BV1abcdefgh2", "play": 120},
            {**base, "bvid": "BV1abcdefgh3", "play": 900, "pubdate": "2026-11-19T20:30:00+08:00"},
            {**base, "bvid": "https://example.org", "play": 1000},
        ], date(2026, 11, 20))
        self.assertEqual([item["views"] for item in rows], [120, 65])

    def test_desktop_report_is_written_once_and_qq_remains_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            store = MemoryStore(folder / "memory.db")
            stamp = int(time.time())
            sample = {"ok": True, "data": {"items": [{"bvid": "BV1abcdefgh1", "title": "工作流样例",
                "desc": "来自公开视频简介", "play": 10, "pubdate": stamp}]}}
            with patch.object(wechat_jobs, "_desktop", return_value=folder), patch.object(wechat_jobs.bili, "run", return_value=sample) as search:
                job = wechat_jobs.submit(store, "a" * 64, "b" * 64, "bili-report-qq", stamp)
                again = wechat_jobs.submit(store, "a" * 64, "b" * 64, "bili-report-qq", stamp)
                self.assertEqual(job, again)
                self.assertEqual(search.call_count, 1)
                self.assertEqual(job["status"], "document-ready")
                self.assertEqual(job["reason"], "qq-send-unavailable")
                self.assertIn("来自公开视频简介", (folder / job["output"]).read_text(encoding="utf-8"))
                self.assertFalse(wechat_jobs.recent(store, "c" * 64)["jobs"])
            with patch("dsh.service.desktop_apps.outlook_today", return_value={"ok": True, "messages": [
                    {"subject": "内部邮件样例", "received": "08:00", "preview": "会议改期"}], "limited": False}):
                mail = wechat_jobs.submit(store, "a" * 64, "e" * 64, "mail-today", stamp)
                self.assertEqual(mail["messages"][0]["preview"], "会议改期")
                self.assertNotIn("内部邮件", str(wechat_jobs.recent(store, "a" * 64)))
                self.assertNotIn("messages", wechat_jobs.submit(store, "a" * 64, "e" * 64, "mail-today", stamp))
            video = wechat_jobs.submit(store, "a" * 64, "f" * 64, "bili-video", stamp)
            self.assertEqual(video["status"], "pending-review")
            self.assertTrue((folder / "wechat-updream-briefs" / video["output"] / "creative-brief.md").is_file())
