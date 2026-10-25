import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from plugin_support import load_plugin
from fatfish_core import RuntimeStore

PLUGIN = load_plugin("astrbot_plugin_fatfish_bili")
FEED = {"ok": True, "data": {"items": [{"bvid": "BV_TEST", "title": "游戏测试"}]}}


class AutoScrollTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        self.plugin.config = {"owner_uid": "123", "auto_scroll_keywords": "游戏"}
        self.plugin.seen = set()
        self.plugin._pause_reason = None
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.plugin.memory_db = Path(directory.name) / "memory.db"
        self.plugin._offline = Mock(return_value=False)
        self.plugin._save_seen = Mock()
        self.plugin._notify = AsyncMock()
        self.plugin._run = AsyncMock(side_effect=[FEED, {"ok": True}])

    async def test_default_preview_does_not_mark_video_as_sent(self):
        preview = {"ok": True, "data": {"dry_run": True}}
        self.plugin._run.side_effect = [FEED, preview, preview]
        await self.plugin._auto_scroll()
        self.assertTrue(self.plugin._run.await_args.kwargs["dry_run"])
        self.assertIn("preview:BV_TEST", self.plugin.seen)
        self.assertNotIn("BV_TEST", self.plugin.seen)
        self.plugin.config["dry_run_writes"] = False
        self.plugin._run.side_effect = [FEED, self.dm(), self.comment()]
        await self.plugin._auto_scroll()
        self.assertFalse(self.plugin._run.await_args.kwargs["dry_run"])
        self.assertIn("BV_TEST", self.plugin.seen)
        self.assertNotIn("preview:BV_TEST", self.plugin.seen)

    @staticmethod
    def dm():
        return {"ok": True, "data": {"sent": True, "msg_key": "dm-123"}}

    @staticmethod
    def comment(*, resolved=True):
        return {"ok": True, "data": {"rpid": 567, "mentions": [{"mid": 123, "resolved": resolved}]}}

    def state(self):
        return RuntimeStore(self.plugin.memory_db).get("bilibili_recommendations", "live", {})["batch"]

    async def test_failed_send_claim_is_saved_but_not_logged_as_success(self):
        self.plugin.config["dry_run_writes"] = False
        self.plugin._run.side_effect = [FEED, {"ok": False, "error": {"code": "risk_control"}}]
        with patch.object(PLUGIN.logger, "info") as info:
            await self.plugin._auto_scroll()
            info.assert_not_called()
        self.assertNotIn("BV_TEST", self.plugin.seen)
        self.assertIn("recommend:BV_TEST", self.plugin.seen)
        self.assertEqual(self.state()["dm"]["status"], "blocked")
        self.assertIsNotNone(self.plugin._pause_reason)

    async def test_dm_and_real_uid_mention_share_a_grounded_first_person_reason(self):
        self.plugin.config["dry_run_writes"] = False
        self.plugin._run.side_effect = [FEED, self.dm(), self.comment()]
        await self.plugin._auto_scroll()
        dm_call, comment_call = self.plugin._run.await_args_list[1:]
        reason = self.state()["items"][0]["reason"]
        self.assertIn("苹果乐", reason)
        self.assertIn(reason, dm_call.args[3])
        self.assertEqual(comment_call.args[:3], ("comment", "post", "BV_TEST"))
        self.assertEqual(comment_call.args[4:], ("--at", "123", "--wait"))
        self.assertIn(reason, comment_call.args[3])
        self.assertNotIn("看完", dm_call.args[3])
        self.assertEqual(self.state()["items"][0]["comment"]["rpid"], "567")
        self.assertEqual(self.state()["items"][0]["dm"]["msg_key"], "dm-123")

    async def test_comment_risk_pause_retains_dm_receipt_and_does_not_repeat_dm(self):
        self.plugin.config["dry_run_writes"] = False
        other = {"bvid":"BV_NEXT", "title":"游戏攻略"}
        feed = {"ok":True,"data":{"items":FEED["data"]["items"] + [other]}}
        self.plugin._run.side_effect = [feed, self.dm(), {"ok":False,"error":{"code":"risk_control"}}]
        await self.plugin._auto_scroll()
        self.assertEqual(self.state()["dm"]["status"], "sent")
        self.plugin._pause_reason = None
        self.plugin._run.reset_mock();self.plugin._run.side_effect = [self.comment()]
        await self.plugin._auto_scroll()
        self.assertEqual(self.plugin._run.await_count, 1)
        self.assertEqual(self.plugin._run.await_args.args[:3], ("comment", "post", "BV_NEXT"))

    async def test_missing_comment_receipt_or_unresolved_mention_never_resends(self):
        for result, expected in (({"ok":True,"data":{}},"uncertain"), (self.comment(resolved=False),"mention_unconfirmed")):
            with self.subTest(status=expected):
                self.plugin.seen.clear()
                RuntimeStore(self.plugin.memory_db).set("bilibili_recommendations", "live", {})
                self.plugin.config["dry_run_writes"] = False
                self.plugin._run.side_effect = [FEED, self.dm(), result]
                await self.plugin._auto_scroll()
                self.assertEqual(self.state()["items"][0]["comment"]["status"], expected)
                self.plugin._run.reset_mock();self.plugin._run.side_effect = [FEED]
                await self.plugin._auto_scroll()
                self.assertEqual(self.plugin._run.await_count, 1)

    async def test_restart_after_sending_claim_does_not_repeat_a_possible_dm(self):
        self.plugin.config["dry_run_writes"] = False
        RuntimeStore(self.plugin.memory_db).set("bilibili_recommendations", "live", {"batch":{
            "owner":"123","dm":{"status":"sending"},"items":[{"bvid":"BV_TEST","title":"游戏", "reason":"想找点乐子", "comment":{"status":"pending"}}]}})
        await self.plugin._auto_scroll()
        self.plugin._run.assert_not_awaited()
        self.assertEqual(self.state()["dm"]["status"], "uncertain")
        self.plugin._run.side_effect=[FEED]
        await self.plugin._auto_scroll()
        self.assertEqual(self.plugin._run.await_count,1)

    async def test_offline_gate_blocks_all_recommendation_reads_and_writes(self):
        self.plugin._offline.return_value=True
        await self.plugin._auto_scroll()
        self.plugin._run.assert_not_awaited()

    async def test_comment_switch_keeps_dm_and_disables_public_write(self):
        self.plugin.config.update(dry_run_writes=False, auto_scroll_comment_enabled=False)
        self.plugin._run.side_effect=[FEED,self.dm()]
        await self.plugin._auto_scroll()
        self.assertEqual(self.plugin._run.await_count,2)
        self.assertEqual(self.state()["items"][0]["comment"]["status"],"disabled")

    def test_title_rules_do_not_claim_to_have_viewed_the_video(self):
        for title in ("明日方舟前瞻","游戏攻略","游戏音乐","明日方舟剧情","科技工具","明日方舟玩法"):
            reason=self.plugin._recommendation_reason(title)
            self.assertLessEqual(len(reason),80)
            self.assertFalse(any(word in reason for word in ("看完", "看过", "视频里说", "字幕里说")))

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
