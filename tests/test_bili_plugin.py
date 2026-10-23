from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from plugin_support import load_plugin


PLUGIN = load_plugin("astrbot_plugin_fatfish_bili")
MEMORY = load_plugin("astrbot_plugin_fatfish_memory")


class Event:
    def __init__(self, uid="owner", private=True, platform="aiocqhttp", admin=False):
        self.uid = uid
        self.private = private
        self.platform = platform
        self.admin = admin

    def get_sender_id(self):
        return self.uid

    def get_platform_name(self):
        return self.platform

    def is_private_chat(self):
        return self.private

    def is_admin(self):
        return self.admin

    def plain_result(self, text):
        return text

    def chain_result(self, chain):
        return chain


async def collect(results):
    return "\n".join([result async for result in results])


class BiliPrivacyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        self.plugin.config = {"owner_qq": "owner", "owner_uid": "123"}
        self.plugin.memory_db = Path(directory.name) / "memory.db"
        self.plugin.home = Path(directory.name)
        self.plugin.exe = "unused-bili"
        self.plugin._poll_task = None
        self.plugin._pause_reason = None
        self.plugin._offline = Mock(return_value=False)
        self.plugin._run = AsyncMock(return_value={"ok": True, "data": {}})
        self.store = MEMORY.MemoryStore(self.plugin.memory_db)
        self.store.remember("PRIVATE_MESSAGE_TOKEN", platform="bilibili", scope="private", kind="dm")
        self.store.remember("PUBLIC_VIDEO_TOKEN", platform="bilibili", scope="public", kind="video")

    def untrusted_events(self):
        return (
            Event("visitor"),
            Event("visitor", private=False),
            Event(private=False),
            Event(private=False, admin=True),
            Event(platform="telegram"),
        )

    async def test_account_and_private_commands_require_trusted_private_chat(self):
        self.plugin._poll_once = AsyncMock(return_value=[])
        for action in ("状态", "登录", "确认", "收件箱", "处理", "私信"):
            for event in self.untrusted_events():
                with self.subTest(action=action, event=vars(event)):
                    result = await collect(self.plugin.bili(event, action, "123 消息"))
                    self.assertIn("私聊", result)
        self.plugin._run.assert_not_awaited()
        self.plugin._poll_once.assert_not_awaited()

    async def test_owner_and_admin_can_view_account_status_in_private_chat(self):
        self.plugin._run.return_value = {"ok": True, "data": {"logged_in": True}}
        for event in (Event(), Event("admin", platform="telegram", admin=True)):
            result = await collect(self.plugin.bili(event, "状态"))
            self.assertIn("登录：是", result)
        self.assertEqual(self.plugin._run.await_count, 4)

    async def test_inbox_tool_rejects_public_and_untrusted_sessions_before_cli_call(self):
        for event in self.untrusted_events():
            result = await collect(self.plugin.bili_inbox(event))
            self.assertIn("私聊", result)
        self.plugin._run.assert_not_awaited()

    async def test_inbox_command_and_tool_keep_private_messages_out_of_public_memory(self):
        self.plugin._run.return_value = {
            "ok": True,
            "data": {"private_messages": [{"text": "PRIVATE_INBOX_TOKEN"}]},
        }
        for results in (
            self.plugin.bili(Event(), "收件箱"),
            self.plugin.bili_inbox(Event()),
        ):
            result = await collect(results)
            self.assertIn("PRIVATE_INBOX_TOKEN", result)
        self.assertEqual(self.store.recall("PRIVATE_INBOX_TOKEN", scopes=("public",)), [])
        private = self.store.recall("PRIVATE_INBOX_TOKEN", scopes=("private",))
        self.assertEqual(len(private), 2)
        self.assertTrue(all(row["kind"] == "inbox" for row in private))

    async def test_memory_queries_only_expose_private_rows_in_trusted_private_chat(self):
        for event in (*self.untrusted_events(), Event(), Event("admin", admin=True)):
            with self.subTest(event=vars(event)):
                result = await collect(self.plugin.bili(event, "记忆", "TOKEN"))
                self.assertIn("PUBLIC_VIDEO_TOKEN", result)
                trusted_private = event.private and (event.admin or event.uid == "owner" and event.platform == "aiocqhttp")
                self.assertEqual("PRIVATE_MESSAGE_TOKEN" in result, trusted_private)

    async def test_legacy_public_inbox_is_hidden_even_before_memory_plugin_reload(self):
        self.store.remember("LEGACY_INBOX_TOKEN", platform="bilibili", scope="public", kind="inbox")
        for event in self.untrusted_events():
            result = await collect(self.plugin.bili(event, "记忆", "TOKEN"))
            self.assertNotIn("LEGACY_INBOX_TOKEN", result)
            self.assertIn("PUBLIC_VIDEO_TOKEN", result)
        result = await collect(self.plugin.bili(Event(), "记忆", "TOKEN"))
        self.assertIn("LEGACY_INBOX_TOKEN", result)

    async def test_public_video_tools_remain_available(self):
        self.plugin._run.return_value = {"ok": True, "data": {"title": "公开视频", "summary": "PUBLIC_SUMMARY_TOKEN"}}
        event = Event("visitor", private=False)
        for results in (
            self.plugin.bili(event, "看", "BVexample"),
            self.plugin.bili_watch(event, "BVexample"),
            self.plugin.bili(event, "搜", "公开话题"),
            self.plugin.bili_search(event, "公开话题"),
        ):
            self.assertIn("公开视频", await collect(results))
        self.assertEqual(len(self.store.recall("PUBLIC_SUMMARY_TOKEN", scopes=("public",))), 2)

    async def test_poll_notifications_keep_public_replies_but_redact_private_reply_text(self):
        self.plugin._run.side_effect = [
            {"ok": True, "data": {"items": [{"rpid": "1"}]}},
            {"ok": True, "data": {"items": []}},
            {"ok": True, "data": {"items": [{"uid": "123"}]}},
        ]
        self.plugin._reply_comment = AsyncMock(return_value="PUBLIC_REPLY_TOKEN")
        self.plugin._reply_dm = AsyncMock(return_value="PRIVATE_REPLY_TOKEN")
        self.plugin._notify = AsyncMock()
        handled = await self.plugin._poll_once(force=True)
        self.assertEqual(handled, ["PUBLIC_REPLY_TOKEN", "PRIVATE_REPLY_TOKEN"])
        self.plugin._notify.assert_awaited_once()
        notification = self.plugin._notify.await_args.args[0]
        self.assertIn("PUBLIC_REPLY_TOKEN", notification)
        self.assertIn("私信", notification)
        self.assertNotIn("PRIVATE_REPLY_TOKEN", notification)

    async def test_owner_can_send_private_message_without_recording_it_as_public(self):
        self.plugin.config["dry_run_writes"] = False
        result = await collect(self.plugin.bili(Event(), "私信", "123 PRIVATE_SENT_TOKEN"))
        self.assertIn("已发送", result)
        self.plugin._run.assert_awaited_once_with("dm", "send", "123", "PRIVATE_SENT_TOKEN", timeout=90, dry_run=False)
        self.assertEqual(self.store.recall("PRIVATE_SENT_TOKEN", scopes=("public",)), [])
        self.assertEqual(len(self.store.recall("PRIVATE_SENT_TOKEN", scopes=("private",))), 1)

    async def test_public_comment_reply_still_works_for_owner_in_group(self):
        result = await collect(self.plugin.bili(Event(private=False), "回复", "BVexample 1 公开回复"))
        self.assertIn("预览（未发送）", result)
        self.plugin._run.assert_awaited_once_with("comment", "reply", "BVexample", "1", "公开回复", timeout=90, dry_run=True)

    def mock_provider(self):
        provider = types.SimpleNamespace(text_chat=AsyncMock(return_value=types.SimpleNamespace(completion_text="本轮回复")))
        self.plugin.context = types.SimpleNamespace(get_using_provider=lambda: provider)
        return provider

    async def test_auto_reply_uses_shared_private_notes_only_for_owner_dm(self):
        self.store.remember("SHARED_PRIVATE_TOKEN", platform="qq", scope="private", kind="note")
        self.store.remember("SHARED_PUBLIC_TOKEN", platform="qq", scope="public", kind="note")
        self.store.add_journal("PRIVATE_JOURNAL_TOKEN")
        provider = self.mock_provider()
        for kind, actor in (("comment", "123"), ("dm", "456"), ("dm", "123"), ("dm", "")):
            with self.subTest(kind=kind, actor=actor):
                result = await self.plugin._generate_reply(kind, "TOKEN", actor=actor, session=f"{kind}:{actor}")
                self.assertEqual(result, "本轮回复")
                system = provider.text_chat.await_args.kwargs["system_prompt"]
                self.assertIn("SHARED_PUBLIC_TOKEN", system)
                self.assertEqual("SHARED_PRIVATE_TOKEN" in system, kind == "dm" and actor == "123")
                self.assertEqual("PRIVATE_JOURNAL_TOKEN" in system, kind == "dm" and actor == "123")
                self.assertNotIn("PRIVATE_MESSAGE_TOKEN", system)
        self.plugin._run.assert_not_awaited()

    async def test_auto_reply_isolates_raw_chat_by_video_or_dm_session(self):
        self.store.remember("THIS_VIDEO_TOKEN", platform="bilibili", scope="public", session="comment:BV1")
        self.store.remember("OTHER_VIDEO_TOKEN", platform="bilibili", scope="public", session="comment:BV2")
        self.store.remember("QQ_GROUP_TOKEN", platform="qq", scope="public", session="comment:BV1")
        provider = self.mock_provider()
        await self.plugin._generate_reply("comment", "TOKEN", actor="123", session="comment:BV1")
        system = provider.text_chat.await_args.kwargs["system_prompt"]
        self.assertIn("THIS_VIDEO_TOKEN", system)
        self.assertNotIn("OTHER_VIDEO_TOKEN", system)
        self.assertNotIn("QQ_GROUP_TOKEN", system)

    async def test_auto_reply_records_real_conversation_but_not_dry_run_as_fact(self):
        self.plugin.seen = set()
        self.plugin._save_seen = lambda: None
        self.plugin._generate_reply = AsyncMock(return_value="ACTUAL_REPLY_TOKEN")
        item = {"user": {"mid": "123"}, "on": {"bvid": "BVexample"}, "rpid": "1", "content": "INCOMING_MESSAGE_TOKEN"}
        await self.plugin._reply_comment(item)
        self.assertEqual(self.store.recall("INCOMING_MESSAGE_TOKEN", scopes=("public",)), [])
        self.assertEqual(self.store.recall("ACTUAL_REPLY_TOKEN", scopes=("public",)), [])
        self.plugin.config["dry_run_writes"] = False
        await self.plugin._reply_comment(item)
        rows = self.store.recall("TOKEN", scopes=("public",), kinds=("message",), conversation=("bilibili", "comment:BVexample"))
        self.assertEqual({row["content"] for row in rows}, {"ACTUAL_REPLY_TOKEN", "INCOMING_MESSAGE_TOKEN"})
        self.assertTrue(all(row["session"] == "comment:BVexample" for row in rows))


class BiliExtensionTests(unittest.IsolatedAsyncioTestCase):
    setUp = BiliPrivacyTests.setUp
    untrusted_events = BiliPrivacyTests.untrusted_events

    async def test_account_recommendations_and_interactions_require_trusted_private_chat(self):
        for action, body in (("推荐", "5"), ("点赞", "BVexample"), ("取消点赞", "BVexample"),
                             ("收藏", "BVexample"), ("取消收藏", "BVexample"),
                             ("动态", "123"), ("动态详情", "456"), ("发动态", "正文")):
            for event in self.untrusted_events():
                with self.subTest(action=action, event=vars(event)):
                    self.assertIn("私聊", await collect(self.plugin.bili(event, action, body)))
        for event in self.untrusted_events():
            self.assertIn("私聊", await collect(self.plugin.bili_recommend(event)))
        self.plugin._run.assert_not_awaited()

    async def test_recommendation_command_and_tool_pass_verified_cli_options(self):
        self.plugin._run.return_value = {"ok": True, "data": {"items": [{"title": "推荐视频"}]}}
        self.assertIn("推荐视频", await collect(self.plugin.bili(Event(), "推荐", "3 2")))
        self.plugin._run.assert_awaited_once_with("feed", "recommend", "--count", "3", "--page", "2", "--unseen", timeout=90)
        self.plugin._run.reset_mock()
        await collect(self.plugin.bili_recommend(Event(), count=99, page=0))
        self.plugin._run.assert_awaited_once_with("feed", "recommend", "--count", "30", "--page", "1", "--unseen", timeout=90)

    async def test_invalid_command_arguments_do_not_call_cli(self):
        for action, body in (("推荐", "0"), ("推荐", "31"), ("推荐", "2 0"),
                             ("推荐", "--raw"), ("推荐", "1 2 3"), ("点赞", ""),
                             ("点赞", "BVexample extra"), ("收藏", ""),
                             ("动态", "bad-id"), ("动态详情", ""), ("发动态", "")):
            with self.subTest(action=action, body=body):
                await collect(self.plugin.bili(Event(), action, body))
        self.plugin._run.assert_not_awaited()

    async def test_interaction_previews_do_not_become_public_memory(self):
        for action, body, args in (
            ("点赞", "BVexample", ("video", "like", "BVexample")),
            ("取消点赞", "BVexample", ("video", "like", "BVexample", "--undo")),
            ("收藏", "BVexample 明日 方舟", ("video", "fav", "BVexample", "--folder", "明日 方舟")),
            ("取消收藏", "BVexample", ("video", "fav", "BVexample", "--remove")),
        ):
            with self.subTest(action=action):
                self.plugin._run.reset_mock()
                self.assertIn("预览（未执行）", await collect(self.plugin.bili(Event(), action, body)))
                self.plugin._run.assert_awaited_once_with(*args, timeout=90, dry_run=True)
        self.assertEqual(self.store.recall("BVexample", scopes=("public",)), [])

    async def test_actual_interaction_success_records_fact_but_failure_does_not(self):
        self.plugin.config["dry_run_writes"] = False
        await collect(self.plugin.bili(Event(), "收藏", "BVsuccess 文件夹"))
        rows = self.store.recall("BVsuccess", scopes=("public",))
        self.assertEqual(len(rows), 1)
        self.assertIn("文件夹", rows[0]["content"])
        self.plugin._run.return_value = {"ok": False, "error": {"code": "risk_control", "message": "测试风控"}}
        self.plugin._notify = AsyncMock()
        self.assertIn("risk_control", await collect(self.plugin.bili(Event(), "点赞", "BVfailure")))
        self.assertEqual(self.store.recall("BVfailure", scopes=("public",)), [])
        self.assertIn("risk_control", self.plugin._pause_reason)

    async def test_dynamic_listing_and_show_only_read(self):
        for action, body, args in (("动态", "", ("dynamic", "list")),
                                  ("动态", "123", ("dynamic", "list", "--mid", "123")),
                                  ("动态详情", "456", ("dynamic", "show", "456"))):
            self.plugin._run.reset_mock()
            await collect(self.plugin.bili(Event(), action, body))
            self.plugin._run.assert_awaited_once_with(*args, timeout=90)

    async def test_dynamic_preview_is_sanitized_and_not_recorded_as_sent(self):
        self.plugin._run.return_value = {"ok": True, "data": {"dry_run": True}}
        text = await collect(self.plugin.bili(Event(), "发动态", "你好 @某人"))
        self.assertIn("未发送", text)
        self.assertIn("＠某人", text)
        args = self.plugin._run.await_args
        self.assertEqual(args.args[:3], ("dynamic", "post", "--file"))
        self.assertTrue(args.kwargs["dry_run"])
        self.assertFalse(Path(args.args[3]).exists())
        self.assertEqual(self.store.recall("某人", scopes=("public",)), [])

    async def test_dynamic_receipt_and_uncertain_status_are_not_confused(self):
        self.plugin.config["dry_run_writes"] = False
        self.plugin._run.return_value = {"ok": True, "data": {"id": "12345"}}
        text = await collect(self.plugin.bili(Event(), "发动态", "SENT_DYNAMIC_TOKEN"))
        self.assertIn("https://t.bilibili.com/12345", text)
        self.assertEqual(len(self.store.recall("SENT_DYNAMIC_TOKEN", scopes=("public",))), 1)
        self.plugin._run.return_value = {"ok": True, "data": {}}
        text = await collect(self.plugin.bili(Event(), "发动态", "UNCERTAIN_DYNAMIC_TOKEN"))
        self.assertIn("结果不确定", text)
        self.assertEqual(self.store.recall("UNCERTAIN_DYNAMIC_TOKEN", scopes=("public",)), [])

    async def test_watch_exposes_ai_summary_transcript_and_safe_frame_sheet(self):
        sheet = self.plugin.home / "frames" / "video" / "sheet.jpg"
        sheet.parent.mkdir(parents=True)
        sheet.write_bytes(b"test-frame")
        self.plugin._run.return_value = {"ok": True, "data": {
            "title": "标题", "bvid": "BVexample", "ai_summary": "AI_SUMMARY_TOKEN",
            "transcript": {"source": "subtitle:zh", "text": "字幕正文"},
            "hot_comments": [{"content": "热评内容"}], "frames_sheet": str(sheet),
        }}
        for results in (self.plugin.bili(Event(), "看", "BVexample"), self.plugin.bili_watch(Event(), "BVexample")):
            values = [result async for result in results]
            self.assertIn("AI_SUMMARY_TOKEN", values[0])
            self.assertIn("字幕正文", values[0])
            self.assertIn("热评内容", values[0])
            self.assertIn("抽帧", values[0])
            self.assertEqual(values[1], [str(sheet.resolve())])
        self.assertEqual(len(self.store.recall("AI_SUMMARY_TOKEN", scopes=("public",))), 2)

    async def test_watch_does_not_send_files_outside_cli_frame_cache(self):
        unrelated = self.plugin.home / "private.txt"
        unrelated.write_text("private", encoding="utf-8")
        self.plugin._run.return_value = {"ok": True, "data": {"title": "标题", "frames_sheet": str(unrelated)}}
        values = [result async for result in self.plugin.bili_watch(Event(), "BVexample")]
        self.assertEqual(len(values), 1)
        self.assertIn("未提供", values[0])


class BiliReplyDedupTests(unittest.IsolatedAsyncioTestCase):
    COMMENT = {"user": {"mid": "123"}, "on": {"bvid": "BVexample"}, "rpid": "1", "content": "评论内容"}
    DM = {"uid": "123", "last_message": {"from": "them", "text": "私信内容", "time": "2026-10-23T08:00:00+08:00"}}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.plugin = self.make_plugin()

    def make_plugin(self, *, dry_run=True, seen_path=None):
        plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        plugin.config = {"owner_uid": "123", "dry_run_writes": dry_run}
        plugin._pause_reason = None
        plugin.seen_path = seen_path or self.root / "seen.json"
        plugin.memory_db = plugin.seen_path.with_suffix(".db")
        plugin.seen = plugin._load_seen()
        plugin._generate_reply = AsyncMock(return_value="生成的回复")
        plugin._run = AsyncMock(return_value={"ok": True, "data": {}})
        plugin._remember = Mock(return_value=True)
        return plugin

    def reload_plugin(self):
        previous = self.plugin
        self.plugin = self.make_plugin(dry_run=previous.config["dry_run_writes"], seen_path=previous.seen_path)
        self.assertEqual(self.plugin.seen, previous.seen)

    async def assert_preview_to_send_cycle(self, handler, item):
        first = await getattr(self.plugin, handler)(item)
        self.assertEqual(first, "[预览] 生成的回复")
        self.assertIsNone(await getattr(self.plugin, handler)(item))
        self.plugin._run.assert_awaited_once()
        self.assertTrue(self.plugin._run.await_args.kwargs["dry_run"])
        self.plugin._generate_reply.assert_awaited_once()
        self.plugin._remember.assert_not_called()
        self.assertTrue(self.plugin.memory_db.is_file())
        self.assertFalse(self.plugin.seen_path.exists())

        # Preview suppression must survive a reload without suppressing a real send.
        self.reload_plugin()
        self.assertIsNone(await getattr(self.plugin, handler)(item))
        self.plugin._run.assert_not_awaited()
        self.plugin._generate_reply.assert_not_awaited()
        self.plugin.config["dry_run_writes"] = False
        self.assertEqual(await getattr(self.plugin, handler)(item), "生成的回复")
        self.plugin._run.assert_awaited_once()
        self.assertFalse(self.plugin._run.await_args.kwargs["dry_run"])
        self.plugin._generate_reply.assert_awaited_once()

        # Once actually sent, neither mode may send or regenerate it again.
        for dry_run in (False, True):
            self.plugin.config["dry_run_writes"] = dry_run
            self.assertIsNone(await getattr(self.plugin, handler)(item))
        self.plugin._run.assert_awaited_once()
        self.plugin._generate_reply.assert_awaited_once()
        self.reload_plugin()
        for dry_run in (True, False):
            self.plugin.config["dry_run_writes"] = dry_run
            self.assertIsNone(await getattr(self.plugin, handler)(item))
        self.plugin._run.assert_not_awaited()
        self.plugin._generate_reply.assert_not_awaited()

    async def test_comment_preview_can_transition_to_single_actual_send_after_reload(self):
        await self.assert_preview_to_send_cycle("_reply_comment", self.COMMENT)

    async def test_dm_preview_can_transition_to_single_actual_send_after_reload(self):
        await self.assert_preview_to_send_cycle("_reply_dm", self.DM)

    async def assert_failed_calls_are_retryable(self, handler, item):
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                self.plugin = self.make_plugin(dry_run=dry_run, seen_path=self.root / f"failed-{dry_run}.json")
                self.plugin._run.return_value = {"ok": False, "error": {"code": "network_error", "message": "测试失败"}}
                for _ in range(2):
                    self.assertIsNone(await getattr(self.plugin, handler)(item))
                self.assertEqual(self.plugin.seen, set())
                self.assertFalse(self.plugin.seen_path.exists())
                self.assertEqual(self.plugin._run.await_count, 2)
                self.assertEqual(self.plugin._generate_reply.await_count, 2)
                self.plugin._remember.assert_not_called()
                self.plugin._run.return_value = {"ok": True, "data": {}}
                result = await getattr(self.plugin, handler)(item)
                self.assertEqual(result, "[预览] 生成的回复" if dry_run else "生成的回复")
                self.assertEqual(self.plugin._run.await_count, 3)
                self.reload_plugin()
                self.assertIsNone(await getattr(self.plugin, handler)(item))
                self.plugin._run.assert_not_awaited()

    async def test_comment_failures_do_not_mark_preview_or_actual_send_as_handled(self):
        await self.assert_failed_calls_are_retryable("_reply_comment", self.COMMENT)

    async def test_dm_failures_do_not_mark_preview_or_actual_send_as_handled(self):
        await self.assert_failed_calls_are_retryable("_reply_dm", self.DM)

    async def test_legacy_keys_remain_treated_as_already_sent_after_reload(self):
        self.plugin.seen = {"comment:1", "dm:123:2026-10-23T08:00:00+08:00"}
        self.plugin._save_seen()
        self.reload_plugin()
        for dry_run in (True, False):
            self.plugin.config["dry_run_writes"] = dry_run
            self.assertIsNone(await self.plugin._reply_comment(self.COMMENT))
            self.assertIsNone(await self.plugin._reply_dm(self.DM))
        self.plugin._run.assert_not_awaited()
        self.plugin._generate_reply.assert_not_awaited()


class BiliPollPauseTests(unittest.IsolatedAsyncioTestCase):
    CODES = ("not_logged_in", "auth_expired", "risk_control", "captcha_required")
    COMMENT = BiliReplyDedupTests.COMMENT
    DM = BiliReplyDedupTests.DM

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def plugin(self):
        plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        plugin.config = {"owner_qq": "owner", "owner_uid": "123", "dry_run_writes": True}
        plugin.exe = "unused-bili"
        plugin.home = self.root
        plugin.memory_db = self.root / "absent-memory.db"
        plugin._poll_task = None
        plugin._pause_reason = None
        plugin._offline = lambda: False
        plugin.seen = set()
        plugin._save_seen = Mock()
        plugin._remember = Mock(return_value=True)
        plugin._run = AsyncMock(return_value={"ok": True, "data": {"items": []}})
        plugin._generate_reply = AsyncMock(return_value="生成的回复")
        plugin._notify = AsyncMock()
        return plugin

    def error(self, code):
        return {"ok": False, "error": {"code": code, "message": "测试账号错误"}}

    async def test_background_poll_and_owner_processing_send_a_duplicate_comment_once(self):
        plugin = self.plugin()
        plugin.config["dry_run_writes"] = False
        first_feed_started = asyncio.Event()
        release_first_feed = asyncio.Event()
        owner_processing_started = asyncio.Event()
        feed_count = 0

        async def run(*args, **kwargs):
            nonlocal feed_count
            if args[:2] == ("feed", "mentions"):
                feed_count += 1
                if feed_count == 1:
                    first_feed_started.set()
                    await release_first_feed.wait()
                return {"ok": True, "data": {"items": [self.COMMENT]}}
            return {"ok": True, "data": {"items": []}}

        async def owner_process():
            owner_processing_started.set()
            return await collect(plugin.bili(Event(), "处理"))

        plugin._run.side_effect = run
        background = asyncio.create_task(plugin._poll_once(force=True))
        await asyncio.wait_for(first_feed_started.wait(), timeout=1)
        manual = asyncio.create_task(owner_process())
        await asyncio.wait_for(owner_processing_started.wait(), timeout=1)
        self.assertEqual(feed_count, 1)
        release_first_feed.set()
        background_result, manual_result = await asyncio.wait_for(asyncio.gather(background, manual), timeout=1)
        self.assertEqual(background_result, ["生成的回复"])
        self.assertIn("没有需要回复的新消息", manual_result)
        writes = [call for call in plugin._run.await_args_list if call.args[:2] == ("comment", "reply")]
        self.assertEqual(len(writes), 1)
        plugin._generate_reply.assert_awaited_once()
        plugin._notify.assert_awaited_once()
        self.assertIn("comment:1", plugin.seen)

    async def test_waiting_poll_rechecks_pause_and_offline_after_acquiring_lock(self):
        for blocked_by in ("pause", "offline"):
            with self.subTest(blocked_by=blocked_by), patch.object(PLUGIN, "logger", Mock()):
                plugin = self.plugin()
                plugin._poll_lock = asyncio.Lock()
                await plugin._poll_lock.acquire()
                waiting = asyncio.create_task(plugin._poll_once(force=True))
                await asyncio.sleep(0)
                if blocked_by == "pause":
                    plugin._pause_reason = "等待期间暂停"
                else:
                    plugin._offline = Mock(return_value=True)
                plugin._poll_lock.release()
                self.assertEqual(await asyncio.wait_for(waiting, timeout=1), [])
                plugin._run.assert_not_awaited()
                plugin._generate_reply.assert_not_awaited()

    async def test_poll_crossing_offline_boundary_does_not_start_cloud_provider(self):
        plugin = self.plugin()
        plugin._offline = Mock(side_effect=[False, True])
        del plugin._generate_reply
        provider = types.SimpleNamespace(text_chat=AsyncMock())
        plugin.context = types.SimpleNamespace(get_using_provider=lambda: provider)
        plugin._run.side_effect = [
            {"ok": True, "data": {"items": [self.COMMENT]}},
            {"ok": True, "data": {"items": []}},
            {"ok": True, "data": {"items": []}},
        ]
        self.assertEqual(await plugin._poll_once(force=True), [])
        self.assertEqual(plugin._offline.call_count, 2)
        provider.text_chat.assert_not_awaited()
        self.assertEqual(plugin.seen, set())
        self.assertTrue(all(call.args[:2] != ("comment", "reply") for call in plugin._run.await_args_list))

    async def test_sqlite_offline_failure_blocks_poll_and_provider_but_can_recover(self):
        plugin = self.plugin()
        del plugin._offline
        del plugin._generate_reply
        provider = types.SimpleNamespace(text_chat=AsyncMock())
        plugin.context = types.SimpleNamespace(get_using_provider=lambda: provider)
        tools = types.SimpleNamespace(get_data_dir=lambda name: self.root)
        with patch.object(PLUGIN, "StarTools", tools), patch.object(PLUGIN, "logger", Mock()) as log:
            with patch.object(PLUGIN, "read_offline", side_effect=sqlite3.OperationalError("database is locked")):
                self.assertEqual(await plugin._poll_once(force=True), [])
                self.assertEqual(await plugin._generate_reply("comment", "公开评论"), "")
            plugin._run.assert_not_awaited()
            provider.text_chat.assert_not_awaited()
            self.assertIn("跳过本次", log.warning.call_args.args[0])
            self.assertIn("database is locked", log.warning.call_args.args[0])
            with patch.object(PLUGIN, "read_offline", return_value={"offline": False}):
                self.assertEqual(await plugin._poll_once(force=True), [])
            self.assertEqual(plugin._run.await_count, 3)
            self.assertIsNone(plugin._pause_reason)

    async def test_four_blocking_errors_pause_later_polls_force_and_direct_auto_replies(self):
        for code in self.CODES:
            with self.subTest(code=code):
                plugin = self.plugin()
                plugin._run.return_value = self.error(code)
                self.assertEqual(await plugin._poll_once(), [])
                self.assertIn(code, plugin._pause_reason)
                for force in (False, True):
                    self.assertEqual(await plugin._poll_once(force=force), [])
                self.assertIsNone(await plugin._reply_comment(self.COMMENT))
                self.assertIsNone(await plugin._reply_dm(self.DM))
                self.assertEqual(await PLUGIN.Main._generate_reply(plugin, "comment", "后续消息"), "")
                plugin._run.assert_awaited_once()
                plugin._generate_reply.assert_not_awaited()
                plugin._notify.assert_awaited_once()
                self.assertIn("/bili 恢复", plugin._notify.await_args.args[0])

    async def test_blocking_errors_pause_from_second_feed_and_dm_read(self):
        ok = {"ok": True, "data": {"items": []}}
        for code in self.CODES:
            for index in (1, 2):
                with self.subTest(code=code, failed_read=index):
                    plugin = self.plugin()
                    plugin._run.side_effect = [ok] * index + [self.error(code)]
                    self.assertEqual(await plugin._poll_once(force=True), [])
                    self.assertIn(code, plugin._pause_reason)
                    self.assertEqual(plugin._run.await_count, index + 1)
                    self.assertEqual(await plugin._poll_once(force=True), [])
                    self.assertEqual(plugin._run.await_count, index + 1)
                    plugin._notify.assert_awaited_once()
                    plugin._generate_reply.assert_not_awaited()

    async def test_auto_send_errors_pause_without_handling_next_item_or_feed(self):
        ok = {"ok": True, "data": {"items": []}}
        for code in self.CODES:
            for kind in ("comment", "dm"):
                with self.subTest(code=code, kind=kind):
                    plugin = self.plugin()
                    if kind == "comment":
                        messages = {"ok": True, "data": {"items": [self.COMMENT, {**self.COMMENT, "rpid": "2"}]}}
                        plugin._run.side_effect = [messages, self.error(code)]
                        count = 2
                    else:
                        messages = {"ok": True, "data": {"items": [self.DM, self.DM]}}
                        plugin._run.side_effect = [ok, ok, messages, self.error(code)]
                        count = 4
                    self.assertEqual(await plugin._poll_once(force=True), [])
                    self.assertIn(code, plugin._pause_reason)
                    self.assertEqual(plugin._run.await_count, count)
                    plugin._generate_reply.assert_awaited_once()
                    plugin._notify.assert_awaited_once()
                    plugin._remember.assert_not_called()
                    self.assertEqual(plugin.seen, set())
                    self.assertIsNone(await plugin._reply_comment(self.COMMENT))
                    self.assertIsNone(await plugin._reply_dm(self.DM))
                    self.assertEqual(await plugin._poll_once(force=True), [])
                    self.assertEqual(plugin._run.await_count, count)
                    plugin._generate_reply.assert_awaited_once()

    async def test_model_result_is_not_sent_if_another_operation_paused_the_account(self):
        for handler, item in (("_reply_comment", self.COMMENT), ("_reply_dm", self.DM)):
            with self.subTest(handler=handler):
                plugin = self.plugin()
                async def generate(*args, **kwargs):
                    plugin._pause_reason = "测试期间被另一个操作暂停"
                    return "刚生成的回复"
                plugin._generate_reply.side_effect = generate
                self.assertIsNone(await getattr(plugin, handler)(item))
                plugin._run.assert_not_awaited()
                plugin._remember.assert_not_called()

    async def test_paused_poll_loop_does_not_invoke_poll_once(self):
        plugin = self.plugin()
        plugin._pause_reason = "已暂停"
        plugin._poll_once = AsyncMock()
        with patch.object(PLUGIN.asyncio, "sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await plugin._poll_loop()
        plugin._poll_once.assert_not_awaited()
        plugin._run.assert_not_awaited()

    async def test_temporary_read_errors_do_not_pause_future_polls(self):
        plugin = self.plugin()
        plugin._run.return_value = self.error("network_error")
        self.assertEqual(await plugin._poll_once(force=True), [])
        self.assertIsNone(plugin._pause_reason)
        self.assertEqual(plugin._run.await_count, 3)
        plugin._notify.assert_not_awaited()
        plugin._run.return_value = {"ok": True, "data": {"items": []}}
        self.assertEqual(await plugin._poll_once(force=True), [])
        self.assertEqual(plugin._run.await_count, 6)
        plugin._generate_reply.assert_not_awaited()

    async def test_resume_requires_trusted_private_chat(self):
        plugin = self.plugin()
        plugin._pause_reason = "已暂停"
        for event in (Event("visitor"), Event(private=False), Event(private=False, admin=True), Event(platform="telegram")):
            self.assertIn("私聊", await collect(plugin.bili(event, "恢复")))
        plugin._run.assert_not_awaited()
        self.assertEqual(plugin._pause_reason, "已暂停")

    async def test_failed_or_logged_out_auth_status_preserves_pause(self):
        for payload in (self.error("auth_expired"), self.error("risk_control"), {"ok": True, "data": {"logged_in": False}}):
            with self.subTest(payload=payload):
                plugin = self.plugin()
                plugin._pause_reason = "原有暂停原因"
                plugin._run.return_value = payload
                result = await collect(plugin.bili(Event(), "恢复"))
                self.assertIn("未解除暂停", result)
                self.assertEqual(plugin._pause_reason, "原有暂停原因")
                plugin._run.assert_awaited_once_with("auth", "status", timeout=60)
                plugin._generate_reply.assert_not_awaited()
                plugin._notify.assert_not_awaited()

    async def test_successful_resume_only_checks_auth_and_allows_future_poll(self):
        for event in (Event(), Event("admin", platform="telegram", admin=True)):
            with self.subTest(event=vars(event)):
                plugin = self.plugin()
                plugin._pause_reason = "原有暂停原因"
                plugin._run.return_value = {"ok": True, "data": {"logged_in": True}}
                result = await collect(plugin.bili(event, "恢复"))
                self.assertIn("暂停状态已解除", result)
                self.assertIn("未拉取或发送消息", result)
                self.assertIsNone(plugin._pause_reason)
                plugin._run.assert_awaited_once_with("auth", "status", timeout=60)
                plugin._generate_reply.assert_not_awaited()
                plugin._notify.assert_not_awaited()
                plugin._run.reset_mock()
                plugin._run.return_value = {"ok": True, "data": {"items": []}}
                self.assertEqual(await plugin._poll_once(), [])
                self.assertEqual(plugin._run.await_count, 3)

    async def test_status_and_forced_processing_show_pause_without_silent_resume(self):
        plugin = self.plugin()
        plugin._pause_reason = "暂停原因标记"
        plugin._run.return_value = {"ok": True, "data": {"logged_in": True}}
        status = await collect(plugin.bili(Event(), "状态"))
        self.assertIn("自动回复：已暂停", status)
        self.assertIn("暂停原因标记", status)
        self.assertIn("/bili 恢复", status)
        plugin._run.reset_mock()
        result = await collect(plugin.bili(Event(), "处理"))
        self.assertIn("已暂停", result)
        self.assertNotIn("处理完成", result)
        plugin._run.assert_not_awaited()
        self.assertEqual(plugin._pause_reason, "暂停原因标记")

    async def test_manual_commands_and_login_confirmation_keep_existing_behavior(self):
        plugin = self.plugin()
        plugin._pause_reason = "暂停原因标记"
        plugin._run.return_value = {"ok": True, "data": {"logged_in": True}}
        await collect(plugin.bili(Event("visitor", private=False), "搜", "公开关键词"))
        plugin._run.assert_awaited_once_with("search", "video", "公开关键词", "--size", "10", timeout=90)
        plugin._run.reset_mock()
        await collect(plugin.bili(Event(), "回复", "BVexample 1 主人的手动回复"))
        plugin._run.assert_awaited_once_with("comment", "reply", "BVexample", "1", "主人的手动回复", timeout=90, dry_run=True)
        plugin._run.reset_mock()
        await collect(plugin.bili(Event(), "确认"))
        self.assertEqual(plugin._pause_reason, "暂停原因标记")
        plugin._generate_reply.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
