from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from plugin_support import load_plugin


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fatfish_core.memory import MemoryStore  # noqa: E402
from fatfish_core.growth import record_capability  # noqa: E402


PLUGIN = load_plugin("astrbot_plugin_fatfish_life")
DAY = "2026-10-23"
PRIVATE_MARKER = "PRIVATE_MARKER_ONLY_FOR_DIARY"
JOURNAL_MARKER = "JOURNAL_MARKER_NEVER_PUBLIC"


class Event:
    def __init__(self, *, private=True, admin=False, sender="owner", platform="aiocqhttp", sent=False, text="回复内容"):
        self.private, self.admin = private, admin
        self.sender, self.platform, self.text = sender, platform, text
        self._has_send_oper = sent

    def is_private_chat(self):
        return self.private

    def is_admin(self):
        return self.admin

    def get_sender_id(self):
        return self.sender

    def get_platform_name(self):
        return self.platform

    def get_session_id(self):
        return "synthetic-session"

    def get_result(self):
        return types.SimpleNamespace(get_plain_text=lambda: self.text)

    def plain_result(self, text):
        return text


class LifePluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = MemoryStore(Path(self.directory.name) / "memory.db")
        self.store.add_owner("qq", "owner")
        self.public_id = self.store.remember(
            "和大家聊了苹果派，PUBLIC_ACTOR 与 PUBLIC_SESSION 都在讨论。",
            platform="qq", scope="public", actor="PUBLIC_ACTOR", session="PUBLIC_SESSION",
        )
        self.store.remember(PRIVATE_MARKER, platform="qq", scope="private", actor="PRIVATE_ACTOR", session="PRIVATE_SESSION")
        with self.store._connect() as connection:
            connection.execute("UPDATE events SET created_at=?", (DAY + "T15:00:00+08:00",))
        self.store.add_journal("手工札记也不能放进公开请求", day=DAY, source="manual")
        self.memory = types.SimpleNamespace(store=self.store, config={"record_all_messages": True})
        self.bili = types.SimpleNamespace(publish_dynamic=AsyncMock(return_value={"ok": True, "status": "sent", "id": "bili-receipt"}))
        self.proposal = {
            "wants_to_share": True, "probability_adjustment": 0,
            "platform_weights": {"bilibili": 45, "qzone": 45, "both": 10},
            "reason": "今天有一段真实的公开讨论，想聊两句。",
            "text": "今天和大家聊了苹果派。老板们还挺有精神嘛。",
            "evidence_ids": [str(self.public_id)],
        }

        def response(*, prompt, system_prompt):
            content = {"journal": JOURNAL_MARKER} if prompt.startswith("用第一人称") else self.proposal
            return types.SimpleNamespace(usage=None, role="assistant", completion_text=json.dumps(content, ensure_ascii=False))

        self.provider = types.SimpleNamespace(text_chat=AsyncMock(side_effect=response))
        self.database = types.SimpleNamespace(db_path=str(Path(self.directory.name) / "missing-usage.db"))
        instances = {"astrbot_plugin_fatfish_memory": self.memory, "astrbot_plugin_fatfish_bili": self.bili}
        self.context = types.SimpleNamespace(
            get_registered_star=lambda name: types.SimpleNamespace(star_cls=instances[name], activated=True) if name in instances else None,
            get_using_provider_async=AsyncMock(return_value=self.provider),
            get_db=lambda: self.database,
        )
        self.plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        self.plugin.context = self.context
        self.plugin.config = {"persona": "TEST_PERSONA", "publish_enabled": True, "qq_bot_id": "1670515707"}
        self.plugin.state = PLUGIN.DailyLifeState(Path(self.directory.name) / "daily.json", rng=Mock(random=Mock(return_value=0)))
        self.plugin._lock = asyncio.Lock()
        self.plugin._task = None
        self.plugin._hour, self.plugin._minute = 23, 50
        self.qzone = AsyncMock(return_value={"ok": True, "status": "sent", "id": "qzone-receipt"})
        self.qzone_patch = patch.object(PLUGIN, "publish_qzone", self.qzone)
        self.qzone_patch.start()
        self.addCleanup(self.qzone_patch.stop)

    async def command(self, event, action="", text=""):
        with patch.object(PLUGIN, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 10, 23, 23, 50, tzinfo=PLUGIN.BEIJING)
            return [item async for item in self.plugin.life(event, action, text)]

    async def test_private_diary_material_never_enters_public_generation(self):
        await self.plugin._reflect(DAY)
        calls = self.provider.text_chat.await_args_list
        self.assertEqual(len(calls), 2)
        private = calls[0].kwargs
        public = calls[1].kwargs
        self.assertIn(PRIVATE_MARKER, private["prompt"])
        self.assertIn("私人日记", private["system_prompt"])
        public_request = public["prompt"] + public["system_prompt"]
        for marker in (PRIVATE_MARKER, JOURNAL_MARKER, "PRIVATE_ACTOR", "PRIVATE_SESSION", "PUBLIC_ACTOR", "PUBLIC_SESSION", "手工札记", '"actor"', '"session"', '"journal"'):
            self.assertNotIn(marker, public_request)
        self.assertIn("public_facts", public["prompt"])
        self.assertIn("和大家聊了苹果派", public["prompt"])
        self.assertEqual(self.plugin.state.data["days"][DAY]["journal"], JOURNAL_MARKER)
        journals = self.store.journals()
        self.assertEqual(len(journals), 2)
        self.assertIn(JOURNAL_MARKER, [item["content"] for item in journals])

    async def test_capability_results_are_private_reflection_input_but_not_public_material(self):
        record_capability(self.store, "anysearch", "failed", stage="search", error_code="authorization")
        with self.store._connect() as connection:
            connection.execute("UPDATE events SET created_at=? WHERE kind='capability'", (DAY + "T15:00:00+08:00",))
        await self.plugin._reflect(DAY)
        private, public = self.provider.text_chat.await_args_list
        self.assertIn('"capability": "anysearch"', private.kwargs["prompt"])
        self.assertIn('"status": "failed"', private.kwargs["prompt"])
        self.assertNotIn('"capabilities"', public.kwargs["prompt"])
        self.assertNotIn("资料检索", public.kwargs["prompt"])
        self.assertEqual(self.plugin.state.data["days"][DAY]["capabilities"][0]["stage"], "search")

    async def test_growth_command_has_same_owner_private_boundary(self):
        for event in (Event(sender="visitor"), Event(private=False)):
            self.assertEqual(await self.command(event, "成长"), ["日记和生活设置只在老大私聊里看。"])
        record_capability(self.store, "tts", "success", stage="generate")
        with self.store._connect() as connection:
            connection.execute("UPDATE events SET created_at=? WHERE kind='capability'", (DAY + "T15:00:00+08:00",))
        replies = await self.command(Event(), "成长")
        self.assertIn("语音表达：成功 1 次（generate）", replies[0])

    async def test_tool_observer_stores_outcome_without_arguments_or_response(self):
        await self.plugin.record_tool(Event(), types.SimpleNamespace(name="anysearch_batch_search"), {"query": "PRIVATE_QUERY"},
                                      types.SimpleNamespace(isError=False, content=[types.SimpleNamespace(type="text", text="错误：SECRET_KEY")]))
        rows = self.store.recent(scopes=("private",), kinds=("capability",))
        self.assertEqual(len(rows), 1)
        self.assertIn("失败", rows[0]["content"])
        self.assertNotIn("SECRET", json.dumps(rows))
        self.assertNotIn("PRIVATE_QUERY", json.dumps(rows))
        await self.plugin.record_tool(Event(), types.SimpleNamespace(name="unknown_tool"), {}, None)
        self.assertEqual(len(self.store.recent(scopes=("private",), kinds=("capability",))), 1)

    async def test_voice_delivery_record_requires_sent_voice_and_does_not_store_voice_url(self):
        event = Event(sent=True, text="")
        voice = type("Record", (), {"url": "SECRET_VOICE_URL"})()
        event.get_result = lambda: types.SimpleNamespace(chain=[voice], get_plain_text=lambda: "")
        await self.plugin.record_sent(event)
        rows = self.store.recent(scopes=("private",), kinds=("capability",))
        self.assertEqual(len(rows), 1)
        self.assertIn("delivery", rows[0]["content"])
        self.assertNotIn("SECRET", json.dumps(rows))
        event._has_send_oper = False
        await self.plugin.record_sent(event)
        self.assertEqual(len(self.store.recent(scopes=("private",), kinds=("capability",))), 1)

    async def test_stt_observation_requires_original_audio_replaced_by_text(self):
        event = Event()
        event.message_obj = types.SimpleNamespace(raw_message={"message": [{"type": "record", "data": {"file": "SECRET_AUDIO"}}]})
        plain = type("Plain", (), {"text": "PRIVATE_TRANSCRIPT"})()
        event.get_messages = lambda: [plain]
        await self.plugin.record_transcription(event)
        rows = self.store.recent(scopes=("private",), kinds=("capability",))
        self.assertEqual(len(rows), 1)
        self.assertIn("语音理解", rows[0]["content"])
        self.assertNotIn("PRIVATE", json.dumps(rows))
        event.get_messages = lambda: [type("Record", (), {})()]
        await self.plugin.record_transcription(event)
        self.assertEqual(len(self.store.recent(scopes=("private",), kinds=("capability",))), 1)

    async def test_both_platforms_publish_once_and_real_success_resets_probability(self):
        self.proposal["platform_weights"] = {"both": 100}
        self.plugin.state.data["next_probability"] = 80
        first, second = await asyncio.gather(self.plugin._run_day(DAY), self.plugin._run_day(DAY))
        self.assertIs(first, second)
        self.bili.publish_dynamic.assert_awaited_once_with(self.proposal["text"])
        self.qzone.assert_awaited_once_with(self.context, self.proposal["text"], "napcat", "1670515707")
        self.assertEqual(first["targets"], ["bilibili", "qzone"])
        self.assertEqual(first["results"]["bilibili"]["status"], "sent")
        self.assertEqual(first["results"]["qzone"]["status"], "sent")
        self.assertEqual(self.plugin.state.data["next_probability"], 20)
        self.assertEqual(len(self.provider.text_chat.await_args_list), 2)
        restarted = PLUGIN.DailyLifeState(self.plugin.state.path)
        self.assertEqual(restarted.data["next_probability"], 20)

    async def test_preview_does_not_call_either_publisher_or_reset_probability(self):
        self.proposal["platform_weights"] = {"both": 100}
        self.plugin.state.data["next_probability"] = 60
        record = await self.plugin._run_day(DAY, preview=True)
        self.bili.publish_dynamic.assert_not_awaited()
        self.qzone.assert_not_awaited()
        self.assertEqual({item["status"] for item in record["results"].values()}, {"preview"})
        self.assertEqual(self.plugin.state.data["next_probability"], 80)
        self.assertNotIn("last_success_day", self.plugin.state.data)

    async def test_disabled_publishing_keeps_draft_and_calls_no_publisher(self):
        self.plugin.config["publish_enabled"] = False
        self.proposal["platform_weights"] = {"both": 100}
        record = await self.plugin._run_day(DAY)
        self.bili.publish_dynamic.assert_not_awaited()
        self.qzone.assert_not_awaited()
        self.assertEqual(record["text"], self.proposal["text"])
        self.assertEqual(self.plugin.state.data["next_probability"], 40)

    async def test_bilibili_dry_run_receipt_is_not_real_success(self):
        self.bili.publish_dynamic.return_value = {"ok": True, "status": "preview", "dry_run": True}
        self.plugin.state.data["next_probability"] = 60
        record = await self.plugin._run_day(DAY)
        self.bili.publish_dynamic.assert_awaited_once()
        self.assertEqual(record["results"]["bilibili"]["status"], "preview")
        self.assertEqual(self.plugin.state.data["next_probability"], 80)
        self.assertNotIn("last_success_day", self.plugin.state.data)

    async def test_uncertain_exception_pauses_platform_and_never_retries(self):
        self.bili.publish_dynamic.side_effect = RuntimeError("synthetic failure")
        record = await self.plugin._run_day(DAY)
        self.assertEqual(record["results"]["bilibili"]["status"], "uncertain")
        self.assertIn("bilibili", self.plugin.state.data["paused"])
        await self.plugin._run_day(DAY)
        self.bili.publish_dynamic.assert_awaited_once()
        await self.plugin._run_day("2026-10-24")
        self.bili.publish_dynamic.assert_awaited_once()
        self.assertEqual(self.plugin.state.data["days"]["2026-10-24"]["results"]["bilibili"]["error"]["code"], "paused")

    async def test_partial_success_resets_without_repeating_successful_platform(self):
        self.proposal["platform_weights"] = {"both": 100}
        self.qzone.side_effect = TimeoutError("synthetic timeout")
        self.plugin.state.data["next_probability"] = 80
        record = await self.plugin._run_day(DAY)
        self.assertEqual(record["results"]["bilibili"]["status"], "sent")
        self.assertEqual(record["results"]["qzone"]["status"], "uncertain")
        self.assertIn("qzone", self.plugin.state.data["paused"])
        self.assertNotIn("bilibili", self.plugin.state.data["paused"])
        self.assertEqual(self.plugin.state.data["next_probability"], 20)
        await self.plugin._publish(DAY)
        self.bili.publish_dynamic.assert_awaited_once()
        self.qzone.assert_awaited_once()

    async def test_non_owner_and_group_commands_do_not_expose_diary_or_resume(self):
        self.plugin.state.begin(DAY)["journal"] = PRIVATE_MARKER
        self.plugin.state.data["paused"]["qzone"] = "check receipt"
        self.plugin._run_day = AsyncMock()
        for event in (Event(sender="visitor"), Event(private=False, admin=True), Event(private=False, sender="owner")):
            for action in ("日记", "草稿", "预览", "恢复", ""):
                with self.subTest(private=event.private, admin=event.admin, action=action):
                    replies = await self.command(event, action, "qzone")
                    self.assertEqual(replies, ["日记和生活设置只在老大私聊里看。"])
                    self.assertNotIn(PRIVATE_MARKER, "".join(replies))
        self.plugin._run_day.assert_not_awaited()
        self.assertIn("qzone", self.plugin.state.data["paused"])

    async def test_owner_private_can_read_diary_and_resume_only_named_platform(self):
        self.plugin.state.begin(DAY)["journal"] = PRIVATE_MARKER
        self.plugin.state.data["paused"].update({"qzone": "pending", "bilibili": "pending"})
        self.assertEqual(await self.command(Event(), "日记"), [PRIVATE_MARKER])
        await self.command(Event(), "恢复", "qzone")
        self.assertNotIn("qzone", self.plugin.state.data["paused"])
        self.assertIn("bilibili", self.plugin.state.data["paused"])
        await self.command(Event(), "恢复", "invalid")
        self.assertIn("bilibili", self.plugin.state.data["paused"])

    async def test_private_admin_is_authorized_without_owner_registration(self):
        self.plugin.state.begin(DAY)["journal"] = PRIVATE_MARKER
        replies = await self.command(Event(admin=True, sender="unregistered"), "日记")
        self.assertEqual(replies, [PRIVATE_MARKER])

    async def test_preview_command_never_publishes(self):
        self.proposal["platform_weights"] = {"both": 100}
        replies = await self.command(Event(), "预览")
        self.assertIn("本命令不发布", replies[0])
        self.bili.publish_dynamic.assert_not_awaited()
        self.qzone.assert_not_awaited()

    async def test_outgoing_record_requires_actual_sent_flag_and_qq_platform(self):
        original = self.store.stats()["events"]
        for event in (Event(sent=False), Event(sent=True, platform="bilibili"), Event(sent=True, text=" ")):
            await self.plugin.record_sent(event)
        self.assertEqual(self.store.stats()["events"], original)
        self.memory.config["record_all_messages"] = False
        await self.plugin.record_sent(Event(sent=True))
        self.assertEqual(self.store.stats()["events"], original)

    async def test_sent_private_qq_reply_stays_private_and_group_reply_is_public(self):
        await self.plugin.record_sent(Event(sent=True, text="机器人私聊回复"))
        await self.plugin.record_sent(Event(sent=True, private=False, text="机器人群聊回复"))
        private = self.store.recall("机器人私聊回复", scopes=("private",))
        public = self.store.recall("机器人群聊回复", scopes=("public",))
        self.assertEqual([(row["actor"], row["session"]) for row in private], [("bot", "synthetic-session")])
        self.assertEqual([(row["actor"], row["session"]) for row in public], [("bot", "synthetic-session")])
        self.assertEqual(self.store.recall("机器人私聊回复", scopes=("public",)), [])

    async def test_missing_provider_leaves_reflection_incomplete_and_does_not_publish(self):
        self.context.get_using_provider_async.return_value = None
        with self.assertRaisesRegex(RuntimeError, "没有可用"):
            await self.plugin._run_day(DAY)
        self.assertNotEqual(self.plugin.state.data["days"][DAY]["status"], "complete")
        self.bili.publish_dynamic.assert_not_awaited()
        self.qzone.assert_not_awaited()

    async def test_cancel_during_publish_is_persisted_as_uncertain_on_reload(self):
        self.bili.publish_dynamic.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.plugin._run_day(DAY)
        self.assertEqual(self.plugin.state.data["days"][DAY]["results"]["bilibili"]["status"], "sending")
        restarted = PLUGIN.DailyLifeState(self.plugin.state.path)
        self.assertEqual(restarted.data["days"][DAY]["results"]["bilibili"]["status"], "uncertain")
        self.assertIn("bilibili", restarted.data["paused"])

    async def test_terminate_cancels_and_awaits_background_task(self):
        started, stopped = asyncio.Event(), asyncio.Event()

        async def background():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        self.plugin._task = asyncio.create_task(background())
        await started.wait()
        await self.plugin.terminate()
        self.assertTrue(self.plugin._task.cancelled())
        self.assertTrue(stopped.is_set())
        await self.plugin.terminate()


if __name__ == "__main__":
    unittest.main()
