import asyncio
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from plugin_support import load_plugin

PLUGIN = load_plugin("astrbot_plugin_fatfish_bili")
FEED = {"ok": True, "data": {"items": [{"bvid": "BV_TEST", "title": "游戏测试"}]}}


class AutoScrollTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        self.plugin.config = {"owner_uid": "123", "auto_scroll_keywords": "游戏"}
        self.plugin.seen = set()
        self.plugin._pause_reason = None
        self.plugin._save_seen = Mock()
        self.plugin._notify = AsyncMock()
        self.plugin._run = AsyncMock(side_effect=[FEED, {"ok": True}])

    async def test_default_preview_does_not_mark_video_as_sent(self):
        await self.plugin._auto_scroll()
        self.assertTrue(self.plugin._run.await_args.kwargs["dry_run"])
        self.assertEqual(self.plugin.seen, {"preview:BV_TEST"})
        self.plugin.config["dry_run_writes"] = False
        self.plugin._run.side_effect = [FEED, {"ok": True}]
        await self.plugin._auto_scroll()
        self.assertFalse(self.plugin._run.await_args.kwargs["dry_run"])
        self.assertEqual(self.plugin.seen, {"BV_TEST"})

    async def test_failed_send_does_not_save_seen_or_log_success(self):
        self.plugin._run.side_effect = [FEED, {"ok": False, "error": {"code": "risk_control"}}]
        with patch.object(PLUGIN.logger, "info") as info:
            await self.plugin._auto_scroll()
            info.assert_not_called()
        self.assertEqual(self.plugin.seen, set())
        self.plugin._save_seen.assert_not_called()
        self.assertIsNotNone(self.plugin._pause_reason)

    async def test_paused_account_does_not_fetch_or_send(self):
        self.plugin._pause_reason = "风控暂停"
        await self.plugin._auto_scroll()
        self.plugin._run.assert_not_awaited()

    async def test_pause_during_feed_fetch_blocks_send(self):
        async def fetch(*args, **kwargs):
            self.plugin._pause_reason = "暂停"
            return FEED
        self.plugin._run.side_effect = fetch
        await self.plugin._auto_scroll()
        self.assertEqual(self.plugin._run.await_count, 1)
        self.plugin._save_seen.assert_not_called()

    async def test_one_daily_slot_runs_on_both_days_but_not_twice_same_minute(self):
        self.plugin.config["auto_scroll_times"] = "12:30"
        self.plugin._last_scroll = ""
        self.plugin._auto_scroll = AsyncMock()
        day = datetime(2026, 10, 23, 12, 30, tzinfo=timezone(timedelta(hours=8)))
        clock = Mock()
        clock.now.side_effect = [day, day, day + timedelta(days=1)]
        with patch.object(PLUGIN, "datetime", clock), patch.object(PLUGIN.asyncio, "sleep", AsyncMock(side_effect=[None, None, asyncio.CancelledError()])):
            with self.assertRaises(asyncio.CancelledError):
                await self.plugin._scroll_loop()
        self.assertEqual(self.plugin._auto_scroll.await_count, 2)
