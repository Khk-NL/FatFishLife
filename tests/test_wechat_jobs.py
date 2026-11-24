from datetime import date
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fatfish_core.memory import MemoryStore
from fatfish_core import wechat_jobs


class WechatJobsTest(unittest.TestCase):
    def test_desktop_txt_is_exclusive(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            with patch.object(wechat_jobs, "_desktop", return_value=folder):
                result = wechat_jobs.create_desktop_text_file("a" * 64)
                self.assertTrue(result["ok"])
                path = folder / result["file"]
                self.assertEqual(path.read_bytes(), b"")
                path.write_text("existing", encoding="utf-8")
                self.assertFalse(wechat_jobs.create_desktop_text_file("a" * 64)["ok"])
                self.assertEqual(path.read_text(encoding="utf-8"), "existing")
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
                "desc": "来自公开视频简介", "play": 100_000, "pubdate": stamp}]}}
            subtitle = {"ok": True, "data": {"bvid": "BV1abcdefgh1", "text": "合成字幕记录了插件的三个安装步骤。"}}
            with patch.object(wechat_jobs, "_desktop", return_value=folder), patch.object(
                wechat_jobs.bili, "run", side_effect=[sample, subtitle],
            ) as cli:
                job = wechat_jobs.submit(store, "a" * 64, "b" * 64, "bili-report-qq", stamp)
                again = wechat_jobs.submit(store, "a" * 64, "b" * 64, "bili-report-qq", stamp)
                self.assertEqual(again["status"], "awaiting-visuals")
                self.assertEqual(cli.call_count, 2)
                self.assertEqual(cli.call_args.args, ("video", "subtitle", "BV1abcdefgh1", "--text"))
                self.assertEqual(job["status"], "awaiting-visuals")
                document_data = {"videos": job["videos"], "visuals": {
                    "BV1abcdefgh1": [{"second": 19, "detail": "终端出现插件安装完成的提示。"}]}}
                self.assertFalse(wechat_jobs.finish_report(store, "c" * 64, "b" * 64, document_data)["ok"])
                result = wechat_jobs.finish_report(store, "a" * 64, "b" * 64, document_data)
                self.assertEqual(result["status"], "document-ready")
                self.assertEqual(result["reason"], "qq-send-unavailable")
                self.assertEqual(result["watched"], 1)
                self.assertFalse(wechat_jobs.finish_report(store, "a" * 64, "b" * 64, document_data)["ok"])
                document = (folder / result["output"]).read_text(encoding="utf-8")
                self.assertIn("来自公开视频简介", document)
                self.assertIn("合成字幕记录了插件的三个安装步骤", document)
                self.assertIn("[00:19](https://www.bilibili.com/video/BV1abcdefgh1/?t=19)", document)
                self.assertIn("终端出现插件安装完成的提示", document)
                self.assertFalse(wechat_jobs.recent(store, "c" * 64)["jobs"])
            with patch("dsh.service.desktop_apps.outlook_today", return_value={"ok": True, "messages": [
                    {"subject": "内部邮件样例", "received": "08:00", "preview": "会议改期"}], "limited": False}):
                mail = wechat_jobs.submit(store, "a" * 64, "e" * 64, "mail-today", stamp)
                self.assertEqual(mail["messages"][0]["preview"], "会议改期")
                self.assertNotIn("内部邮件", str(wechat_jobs.recent(store, "a" * 64)))
                self.assertNotIn("messages", wechat_jobs.submit(store, "a" * 64, "e" * 64, "mail-today", stamp))
            draft = {"title": "鲸鲸的桌面花园", "reflection": "今天想试试给桌面留一点空白。",
                     "actions": ["把桌面上的书摆齐。", "把一盆海草放到窗边。", "看着留出的空白发会儿呆。"]}
            video = wechat_jobs.submit(store, "a" * 64, "f" * 64, "bili-video", stamp, draft=draft)
            self.assertEqual(video["status"], "pending-review")
            brief = (folder / "wechat-updream-briefs" / video["output"] / "creative-brief.md").read_text(encoding="utf-8")
            self.assertIn("给桌面留一点空白", brief)
            self.assertIn("一盆海草放到窗边", brief)
            invalid = wechat_jobs.submit(store, "a" * 64, "d" * 64, "bili-video", stamp,
                                         draft={**draft, "reflection": "把账号密码放进视频。"})
            self.assertEqual(invalid["status"], "blocked")
