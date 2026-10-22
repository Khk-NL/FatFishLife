from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

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
        self.plugin.seen.clear()
        await self.plugin._reply_comment(item)
        rows = self.store.recall("TOKEN", scopes=("public",), kinds=("message",), conversation=("bilibili", "comment:BVexample"))
        self.assertEqual({row["content"] for row in rows}, {"ACTUAL_REPLY_TOKEN", "INCOMING_MESSAGE_TOKEN"})
        self.assertTrue(all(row["session"] == "comment:BVexample" for row in rows))


if __name__ == "__main__":
    unittest.main()
