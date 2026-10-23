from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

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
        plugin.seen_path = seen_path or self.root / "seen.json"
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
        self.assertTrue(self.plugin.seen_path.is_file())

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


if __name__ == "__main__":
    unittest.main()
