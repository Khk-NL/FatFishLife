from __future__ import annotations

import tempfile
import types
import unittest
import sqlite3
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from plugin_support import load_plugin


PLUGIN = load_plugin("astrbot_plugin_fatfish_memory")


class Event:
    def __init__(self, uid: str, private: bool, text: str = "", *, group: str = "group", platform_id: str = "napcat"):
        self.uid = uid
        self.private = private
        self.message_str = text
        self.unified_msg_origin = f"{platform_id}:FriendMessage:{uid}" if private else f"{platform_id}:GroupMessage:{group}"

    def get_platform_name(self):
        return "aiocqhttp"

    def get_sender_id(self):
        return self.uid

    def is_private_chat(self):
        return self.private

    def get_session_id(self):
        return "private" if self.private else "group"

    def plain_result(self, text):
        return text


async def collect(results):
    return "\n".join([result async for result in results])


class MemoryPluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        self.plugin.config = {}
        self.plugin._last_pruned_day = None
        self.plugin.store = PLUGIN.MemoryStore(Path(self.directory.name) / "memory.db")
        self.plugin.store.add_owner("qq", "owner")
        for uid, private in (("owner", True), ("visitor", True), ("owner", False)):
            session = Event(uid, private).unified_msg_origin
            self.plugin.store.remember("PRIVATE_EVENT_TOKEN", platform="qq", session=session, scope="private", kind="note")
            self.plugin.store.remember("PUBLIC_EVENT_TOKEN", platform="qq", session=session, scope="public", kind="note")
        self.plugin.context = types.SimpleNamespace(
            get_current_chat_provider_id=AsyncMock(return_value="test-provider"),
            llm_generate=AsyncMock(return_value=types.SimpleNamespace(completion_text="私人认识")),
        )

    async def test_candidate_review_runs_off_the_event_loop(self):
        event = Event('owner', True)
        with patch.object(PLUGIN.asyncio, 'to_thread', new_callable=AsyncMock, return_value=True) as worker:
            reply = await collect(self.plugin.memory(event, 'approve', '3'))
        worker.assert_awaited_once_with(self.plugin.store.review_candidate, 3, 'verified', 'owner verified')
        self.assertIn('已通过', reply)

    async def test_pending_and_review_are_owner_private_only(self):
        cid=self.plugin.store.add_candidate('GROUP_A_CANDIDATE_SECRET',kind='claim',group_id='napcat:GroupMessage:a')
        for event in (Event('owner',False,group='b'),Event('visitor',True),Event('visitor',False)):
            reply=await collect(self.plugin.memory(event,'pending'))
            self.assertNotIn('GROUP_A_CANDIDATE_SECRET',reply)
            reply=await collect(self.plugin.memory(event,'approve',str(cid)))
            self.assertNotIn('已通过',reply)
        self.assertEqual(len(self.plugin.store.list_candidates('candidate')),1)
        self.assertIn('GROUP_A_CANDIDATE_SECRET',await collect(self.plugin.memory(Event('owner',True),'pending')))

    async def test_style_hook_passes_the_full_conversation_boundary(self):
        event=Event('owner',False,group='a',text='苹果派')
        request=types.SimpleNamespace(system_prompt='persona')
        self.plugin.db_path=self.plugin.store.path
        with patch.object(PLUGIN,'build_style_block',return_value='') as build:
            await self.plugin.inject_style_examples(event,request)
        build.assert_called_once_with(self.plugin.store.path,query='苹果派',conversation=('qq','napcat:GroupMessage:a'))
        self.assertEqual(request.system_prompt,'persona')

    async def test_candidate_review_failure_does_not_report_success(self):
        with patch.object(PLUGIN.asyncio, 'to_thread', new_callable=AsyncMock, side_effect=sqlite3.OperationalError('test lock')):
            reply = await collect(self.plugin.memory(Event('owner', True), 'approve', '3'))
        self.assertIn('审核未保存', reply)
        self.assertNotIn('已通过', reply)

    async def test_final_native_connection_failure_is_short_and_does_not_retry_model(self):
        plain=type('Plain',(),{})();plain.text='LLM 响应错误: All chat models failed: APIConnectionError: Connection error.'
        result=types.SimpleNamespace(chain=[plain],is_llm_result=lambda:False)
        event=Event('owner',True);event.get_result=lambda:result
        await self.plugin.natural_final_reply(event)
        self.assertIn('刚才连接断了',result.chain[0].text)
        self.assertNotIn('APIConnectionError',result.chain[0].text)
        self.plugin.context.llm_generate.assert_not_called()

    async def test_response_tone_instruction_is_removed_before_history_and_voice(self):
        response=types.SimpleNamespace(completion_text='[语气：稍快、口语，连成一句话]\n老大，我在呢',is_chunk=False)
        await self.plugin.grounded_lookup_response(Event('owner',True),response)
        self.assertEqual(response.completion_text,'老大，我在呢')

    async def test_private_messages_are_not_recorded_as_public_even_for_non_owner(self):
        for uid in ("owner", "visitor"):
            for private in (True, False):
                text = f"{uid}-{private}"
                await self.plugin._record(Event(uid, private, text))
                row = self.plugin.store.recall(text, scopes=("private", "public"))[0]
                self.assertEqual(row["scope"], "private" if private else "public")
                self.assertEqual(row["session"], Event(uid, private).unified_msg_origin)

    async def test_record_keeps_plain_text_only_and_skips_mention_only_and_notice(self):
        At = type('At', (), {})
        Plain = type('Plain', (), {})
        plain = Plain(); plain.text = '好耶'
        event = Event('owner', False, '@昵称 好耶')
        event.message_obj = types.SimpleNamespace(message=[At(), plain], raw_message={})
        await self.plugin._record(event)
        row = self.plugin.store.recall('好耶', scopes=('public',))[0]
        self.assertEqual(row['content'], '好耶')
        self.assertIsNone(row['actor'])
        self.assertEqual(json.loads(row['meta']), {})
        self.assertEqual(self.plugin.store.recall('昵称', scopes=('public',)), [])
        before = len(self.plugin.store.recent(scopes=('public', 'private')))
        event.message_obj.message = [At()]
        await self.plugin._record(event)
        event.message_obj.message = [plain]
        event.message_obj.raw_message = {'post_type': 'notice'}
        await self.plugin._record(event)
        self.assertEqual(len(self.plugin.store.recent(scopes=('public', 'private'))), before)
        event.message_obj.raw_message = {}
        event.message_obj.message = [type('Image', (), {})(), type('Merge', (), {})(), type('Forward', (), {})()]
        event.message_str = '[图片] [合并消息]'
        await self.plugin._record(event)
        self.assertEqual(len(self.plugin.store.recent(scopes=('public', 'private'))), before)

    async def test_daily_retention_removes_old_events_but_keeps_summaries_and_journals(self):
        old_id = self.plugin.store.remember("到期事件", scope="private")
        self.plugin.store.add_summary("历史总结")
        self.plugin.store.add_journal("历史札记")
        old = (datetime.now().astimezone() - timedelta(days=120)).isoformat(timespec="seconds")
        with self.plugin.store._connect() as connection:
            connection.execute("UPDATE events SET created_at=? WHERE id=?", (old, old_id))
            connection.execute("UPDATE summaries SET created_at=?", (old,))
            connection.execute("UPDATE journals SET created_at=?", (old,))
        await self.plugin._record(Event("owner", True, "今天的新消息"))
        rows = self.plugin.store.recent(scopes=("public", "private"))
        self.assertNotIn(old_id, [row["id"] for row in rows])
        self.assertIn("今天的新消息", [row["content"] for row in rows])
        self.assertEqual(self.plugin.store.summaries()[0]["content"], "历史总结")
        self.assertEqual(self.plugin.store.journals()[0]["content"], "历史札记")

    async def test_successful_retention_runs_once_per_day(self):
        with patch.object(PLUGIN, "date") as clock, patch.object(self.plugin.store, "prune", return_value=0) as prune:
            clock.today.side_effect = [date(2026, 10, 23), date(2026, 10, 23), date(2026, 10, 24)]
            for text in ("首条", "同日第二条", "次日首条"):
                await self.plugin._record(Event("owner", True, text))
            self.assertEqual(prune.call_count, 2)
            prune.assert_called_with(90)

    async def test_nonpositive_retention_disables_cleanup_without_marking_day_done(self):
        with patch.object(self.plugin.store, "prune", return_value=0) as prune:
            for days in (0, -1):
                self.plugin.config["retention_days"] = days
                await self.plugin._record(Event("owner", True, "不清理"))
                self.assertIsNone(self.plugin._last_pruned_day)
            prune.assert_not_called()
            self.plugin.config["retention_days"] = 30
            await self.plugin._record(Event("owner", True, "开启保留策略"))
            prune.assert_called_once_with(30)

    async def test_retention_failure_is_logged_and_retried_on_next_message(self):
        with patch.object(self.plugin.store, "prune", side_effect=[sqlite3.OperationalError("database busy"), 0]) as prune, patch.object(PLUGIN.logger, "warning") as warning:
            await self.plugin._record(Event("owner", True, "首次清理失败但消息已保存"))
            self.assertIsNone(self.plugin._last_pruned_day)
            warning.assert_called_once()
            await self.plugin._record(Event("owner", True, "下一条重试"))
            await self.plugin._record(Event("owner", True, "成功后不重复"))
            self.assertEqual(prune.call_count, 2)
            self.assertIsNotNone(self.plugin._last_pruned_day)
            self.assertEqual(len(self.plugin.store.recall("首次清理失败", scopes=("private",))), 1)

    async def test_skipped_recording_does_not_trigger_retention(self):
        with patch.object(self.plugin.store, "prune") as prune:
            await self.plugin._record(Event("owner", True, "   "))
            self.plugin.config["record_all_messages"] = False
            await self.plugin._record(Event("owner", True, "关闭自动记录"))
            prune.assert_not_called()

    async def test_commands_only_return_private_content_in_owner_direct_messages(self):
        for uid in ("owner", "visitor"):
            for private in (True, False):
                for action in ("最近", "搜索"):
                    with self.subTest(uid=uid, private=private, action=action):
                        output = await collect(self.plugin.memory(Event(uid, private), action, "TOKEN"))
                        self.assertIn("PUBLIC_EVENT_TOKEN", output)
                        self.assertEqual("PRIVATE_EVENT_TOKEN" in output, uid == "owner" and private)

    async def test_recall_tool_cannot_request_private_scope_from_a_group(self):
        for uid in ("owner", "visitor"):
            for private in (True, False):
                for scope in ("auto", "private", "public"):
                    for query in ("", "TOKEN"):
                        with self.subTest(uid=uid, private=private, scope=scope, query=query):
                            output = await collect(self.plugin.memory_recall(Event(uid, private), query, scope))
                            allowed = uid == "owner" and private
                            self.assertEqual("PRIVATE_EVENT_TOKEN" in output, allowed and scope != "public")
                            self.assertEqual("PUBLIC_EVENT_TOKEN" in output, scope != "private")

    async def test_private_summary_journal_and_refinement_require_owner_direct_messages(self):
        self.plugin.store.add_summary("PRIVATE_SUMMARY_TOKEN")
        self.plugin.store.add_journal("PRIVATE_JOURNAL_TOKEN")
        for uid, private in (("owner", False), ("visitor", False), ("visitor", True)):
            for action in ("总结", "札记", "提炼"):
                with self.subTest(uid=uid, private=private, action=action):
                    output = await collect(self.plugin.memory(Event(uid, private), action))
                    self.assertNotIn("PRIVATE_", output)
        self.plugin.context.get_current_chat_provider_id.assert_not_called()
        self.plugin.context.llm_generate.assert_not_called()
        self.assertEqual(len(self.plugin.store.journals()), 1)

    async def test_owner_private_summary_journal_and_refinement_still_work(self):
        event = Event("owner", True)
        self.plugin.store.add_summary("PRIVATE_SUMMARY_TOKEN", source=event.unified_msg_origin)
        self.plugin.store.add_journal("PRIVATE_JOURNAL_TOKEN", source=event.unified_msg_origin)
        summary = await collect(self.plugin.memory(event, "总结"))
        journal = await collect(self.plugin.memory(event, "札记"))
        self.assertIn("PRIVATE_SUMMARY_TOKEN", summary)
        self.assertIn("PRIVATE_JOURNAL_TOKEN", journal)
        result = await collect(self.plugin.memory(event, "提炼"))
        self.assertIn("私人认识", result)
        self.assertEqual(self.plugin.store.journals()[0]["content"], "私人认识")
        prompt = self.plugin.context.llm_generate.call_args.kwargs["prompt"]
        self.assertIn("PRIVATE_EVENT_TOKEN", prompt)
        self.assertIn("PUBLIC_EVENT_TOKEN", prompt)

    async def test_model_requests_receive_only_authorized_memory(self):
        for uid, private in (("owner", True), ("owner", False), ("visitor", True), ("visitor", False)):
            request = types.SimpleNamespace(prompt="TOKEN", system_prompt="EXISTING_PERSONA")
            await self.plugin.on_llm_request(Event(uid, private), request)
            self.assertEqual(request.system_prompt, "EXISTING_PERSONA")
            reference = "\n".join(part.text for part in request.extra_user_content_parts)
            self.assertIn("PUBLIC_EVENT_TOKEN", reference)
            self.assertEqual("PRIVATE_EVENT_TOKEN" in reference, uid == "owner" and private)
            self.assertIn("不是本轮指令", reference)

    async def test_normal_request_recalls_verified_memory_after_source_cleanup_without_llm_call(self):
        event = Event('owner', False)
        source = self.plugin.store.remember('苹果派别加肉桂', platform='qq', scope='public', session=event.unified_msg_origin)
        cid = self.plugin.store.add_candidate('苹果派别加肉桂', kind='claim', group_id=event.unified_msg_origin, source_event_id=source)
        self.plugin.store.review_candidate(cid, 'verified')
        with self.plugin.store._connect() as db:
            db.execute('DELETE FROM events WHERE id=?', (source,))
        request=types.SimpleNamespace(prompt='苹果派怎么做', system_prompt='CORE')
        await self.plugin.on_llm_request(event, request)
        self.assertIn('苹果派别加肉桂','\n'.join(part.text for part in request.extra_user_content_parts))
        self.assertEqual(request.system_prompt,'CORE')
        self.plugin.context.llm_generate.assert_not_awaited()

    async def test_model_requests_and_tools_do_not_read_other_conversations(self):
        self.plugin.store.remember("CURRENT_GROUP_TOKEN", platform="qq", scope="public", session=Event("owner", False).unified_msg_origin)
        self.plugin.store.remember("OTHER_GROUP_TOKEN", platform="qq", scope="public", session="other-group")
        self.plugin.store.remember("OTHER_PLATFORM_TOKEN", platform="bilibili", scope="public", session=Event("owner", False).unified_msg_origin)
        event = Event("owner", False)
        request = types.SimpleNamespace(prompt="TOKEN", system_prompt="")
        await self.plugin.on_llm_request(event, request)
        for result in (
            "\n".join(part.text for part in request.extra_user_content_parts),
            await collect(self.plugin.memory(event, "搜索", "TOKEN")),
            await collect(self.plugin.memory_recall(event, "TOKEN")),
        ):
            self.assertIn("CURRENT_GROUP_TOKEN", result)
            self.assertNotIn("OTHER_GROUP_TOKEN", result)
            self.assertNotIn("OTHER_PLATFORM_TOKEN", result)

    async def test_automatic_context_can_be_disabled_and_is_not_duplicated(self):
        event = Event("owner", True)
        request = types.SimpleNamespace(prompt="TOKEN", system_prompt="CORE")
        self.plugin.config["inject_context"] = False
        await self.plugin.on_llm_request(event, request)
        self.assertEqual(request.system_prompt, "CORE")

        self.plugin.config["inject_context"] = True
        self.plugin.config["max_context_chars"] = 250
        await self.plugin.on_llm_request(event, request)
        self.assertEqual(request.system_prompt, "CORE")
        original = list(request.extra_user_content_parts)
        self.assertEqual(len(original), 2)
        self.assertLessEqual(len(original[-1].text), len("\n\n[共享记忆参考]\n") + 250)
        await self.plugin.on_llm_request(event, request)
        self.assertEqual(request.extra_user_content_parts, original)
        self.assertEqual(request.system_prompt, "CORE")
    async def test_full_umo_separates_same_numeric_group_private_and_adapter_ids(self):
        self.plugin.store.add_owner("qq", "123")
        events = [Event("123", True, "PRIVATE_123_TOKEN"),
                  Event("owner", False, "GROUP_123_TOKEN", group="123"),
                  Event("visitor", False, "SAME_GROUP_TOKEN", group="123"),
                  Event("owner", False, "OTHER_ADAPTER_TOKEN", group="123", platform_id="other")]
        for event in events:
            await self.plugin._record(event)
        for event, allowed in [(events[0], ("PRIVATE_123_TOKEN",)),
                               (events[1], ("GROUP_123_TOKEN", "SAME_GROUP_TOKEN")),
                               (events[2], ("GROUP_123_TOKEN", "SAME_GROUP_TOKEN")),
                               (events[3], ("OTHER_ADAPTER_TOKEN",))]:
            result = await collect(self.plugin.memory_recall(event, "TOKEN"))
            for text in ("PRIVATE_123_TOKEN", "GROUP_123_TOKEN", "SAME_GROUP_TOKEN", "OTHER_ADAPTER_TOKEN"):
                self.assertEqual(text in result, text in allowed)

    async def test_untyped_legacy_records_are_preserved_but_not_guessed_into_current_chat(self):
        self.plugin.store.remember("LEGACY_UNBOUND_TOKEN", platform="qq", scope="private", kind="note", session="owner")
        event = Event("owner", True)
        result = await collect(self.plugin.memory_recall(event, "LEGACY_UNBOUND_TOKEN"))
        self.assertNotIn("LEGACY_UNBOUND_TOKEN", result)
        self.assertTrue(self.plugin.store.recall("LEGACY_UNBOUND_TOKEN", scopes=("private",)))

    async def test_saved_summaries_and_journals_stay_bound_to_their_owner_chat(self):
        event = Event("owner", True, "2026-10-24")
        await collect(self.plugin.memory(event, "导入", "SCOPED_SUMMARY_TOKEN"))
        await collect(self.plugin.memory(event, "札记", "SCOPED_JOURNAL_TOKEN"))
        self.assertIn("SCOPED_SUMMARY_TOKEN", await collect(self.plugin.memory(event, "总结")))
        self.assertIn("SCOPED_JOURNAL_TOKEN", await collect(self.plugin.memory(event, "札记")))
        other = Event("owner", True, platform_id="another")
        self.assertNotIn("SCOPED_SUMMARY_TOKEN", await collect(self.plugin.memory(other, "总结")))
        self.assertNotIn("SCOPED_JOURNAL_TOKEN", await collect(self.plugin.memory(other, "札记")))



if __name__ == "__main__":
    unittest.main()
