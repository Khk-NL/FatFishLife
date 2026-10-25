from __future__ import annotations

import asyncio
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from plugin_support import load_plugin


class At:
    def __init__(self, qq):
        self.qq = qq


class Plain:
    def __init__(self, text):
        self.text = text


class Reply:
    def __init__(self, id=None):
        self.id = id


class Poke:
    def __init__(self, target):
        self.id = target

    def target_id(self):
        return self.id


class Image:
    pass


components = types.ModuleType("astrbot.api.message_components")
components.At, components.Plain, components.Reply = At, Plain, Reply
core_message = types.ModuleType("astrbot.core.message")
results = types.ModuleType("astrbot.core.message.message_event_result")
results.MessageChain = lambda chain: types.SimpleNamespace(chain=chain)
PLUGIN = load_plugin(
    "astrbot_plugin_fatfish_offline",
    module_overrides={
        "astrbot.api.message_components": components,
        "astrbot.core.message": core_message,
        "astrbot.core.message.message_event_result": results,
    },
)


class Event:
    def __init__(self, *, group="group", message=(), text="", raw=None):
        self.group = group
        self.unified_msg_origin = f"test:{group or 'private'}"
        self.message_obj = types.SimpleNamespace(message=list(message), message_str=text, raw_message=raw or {})
        self.message_str = text
        self.is_at_or_wake_command = any(isinstance(component, At) and component.qq == "bot" for component in message)
        self.stopped = False
        self.extras = {}
        self.send = AsyncMock()

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_self_id(self):
        return "bot"

    def get_sender_id(self):
        return "visitor"

    def get_sender_name(self):
        return "访客"

    def get_group_id(self):
        return self.group

    def is_private_chat(self):
        return not self.group

    def stop_event(self):
        self.stopped = True


def poke_raw(target):
    return {"post_type": "notice", "notice_type": "notify", "sub_type": "poke", "target_id": target}


class OfflinePluginTriggerTests(unittest.IsolatedAsyncioTestCase):
    def quote_event(self, *, group='group', message_id='101', text='你好', message=()):
        event=Event(group=group,text=text,message=message)
        event.message_obj.message_id=message_id
        return event

    async def test_simple_group_chat_does_not_quote_by_default(self):
        plugin=self.plugin();event=self.quote_event();chain=[Plain('在呢')]
        plugin._note_quote_message(event)
        self.assertIs(plugin._quote_chain(event,chain),chain)

    async def test_quote_request_or_incoming_quote_references_current_event_not_old_id(self):
        plugin=self.plugin()
        for event in (self.quote_event(text='引用这条消息回复'),self.quote_event(message=[Reply(id='old')])):
            reply=plugin._quote_chain(event,[Plain('知道啦')])
            self.assertIsInstance(reply[0],Reply)
            self.assertEqual(reply[0].id,'101')

    async def test_intervening_message_quotes_delayed_reply_without_crossing_sessions(self):
        plugin=self.plugin();first=self.quote_event();newer=self.quote_event(message_id='102')
        plugin._note_quote_message(first);plugin._note_quote_message(newer)
        self.assertEqual(plugin._quote_chain(first,[Plain('回答第一条')])[0].id,'101')
        self.assertIsInstance(plugin._quote_chain(newer,[Plain('回答第二条')])[0],Plain)
        other=self.quote_event(group='other',message_id='103');plugin._note_quote_message(other)
        self.assertIsInstance(plugin._quote_chain(newer,[Plain('还是第二条')])[0],Plain)

    async def test_keyword_interjection_quotes_but_private_media_commands_and_optout_do_not(self):
        plugin=self.plugin();event=self.quote_event();plugin._set_trigger(event,'visitor','keyword')
        self.assertEqual(plugin._quote_chain(event,[Plain('苹果派！')])[0].id,'101')
        for blocked,chain in ((self.quote_event(group='',text='引用这条消息回复'),[Plain('私聊')]),
                              (self.quote_event(message_id=''),[Plain('没有ID')]),
                              (self.quote_event(message=[Reply(id='old')]),[Reply(id='existing'),Plain('已有引用')]),
                              (self.quote_event(text='引用回复'),[type('Record',(),{})()]),
                              (self.quote_event(text='不要引用回复'),[Plain('好的')])):
            self.assertIs(plugin._quote_chain(blocked,chain),chain)
        result=types.SimpleNamespace(chain=[Plain('命令结果')],is_llm_result=lambda:False)
        event.get_result=lambda:result
        await plugin.quote_when_needed(event)
        self.assertIsInstance(result.chain[0],Plain)

    async def test_quote_message_tracking_is_bounded(self):
        plugin=self.plugin()
        for index in range(270):plugin._note_quote_message(self.quote_event(group=str(index)))
        self.assertEqual(len(plugin._quote_latest),256)

    def plugin(self, offline=False):
        plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        plugin.config = {}
        plugin.context = types.SimpleNamespace()
        plugin.enabled = True
        plugin.hourly_model_limit = 0
        plugin.scheduler = types.SimpleNamespace(tz=timezone.utc)
        plugin._decision = Mock(return_value=PLUGIN.Decision(offline, "test" if offline else None))
        plugin.state = types.SimpleNamespace(publish_offline=Mock(), bump_usage=Mock(return_value=1))
        plugin.engagement = PLUGIN.GroupEngagement(PLUGIN.GroupConfig(random_probability=0))
        plugin.engine = types.SimpleNamespace(handle=Mock(return_value="离线普通回复"))
        plugin._local_warm = False
        plugin._local_mode_task = None
        plugin._published_mode = None
        plugin._mode_timer_task = None
        plugin.local_model = types.SimpleNamespace(
            enabled=False, warmup=AsyncMock(), unload=AsyncMock(), chat=AsyncMock(return_value=None), close=AsyncMock()
        )
        return plugin

    async def test_keyword_progression_is_per_full_session_and_send_success_controls_reset(self):
        plugin=self.plugin();plugin.config.update(keyword_probability=.1,keyword_probability_step=.1,keyword_probability_max=.3)
        first='napcat:GroupMessage:42';other='other:GroupMessage:42';private='napcat:FriendMessage:42'
        with patch.object(PLUGIN.random,'random',return_value=.99):
            self.assertFalse(plugin._keyword_allowed(first,1000))
            self.assertFalse(plugin._keyword_allowed(first,1001))
            self.assertFalse(plugin._keyword_allowed(first,1002))
            self.assertEqual(plugin._keyword_misses.get(first),3)
            self.assertEqual(plugin._keyword_misses.get(other),0)
            self.assertEqual(plugin._keyword_misses.get(private),0)
        with patch.object(PLUGIN.random,'random',return_value=.25):
            self.assertTrue(plugin._keyword_allowed(first,1003))
            self.assertFalse(plugin._keyword_allowed(other,1003))
        self.assertEqual(plugin._keyword_misses.get(first),4)
        self.assertEqual(plugin._keyword_last[first],1003)
        with patch.object(PLUGIN.random,'random',return_value=0):
            self.assertFalse(plugin._keyword_allowed(first,1003.5))
        self.assertEqual(plugin._keyword_misses.get(first),4)
        plugin._keyword_sent(first,1004)
        self.assertEqual(plugin._keyword_misses.get(first),0)
        self.assertFalse(plugin._keyword_allowed(first,1005))
        self.assertEqual(plugin._keyword_misses.get(first),0)

    async def test_keyword_trigger_reset_follows_real_sent_hook_even_for_media_reply(self):
        plugin=self.plugin();event=Event(group='42',text='能天使今天有什么好玩的')
        event.unified_msg_origin='napcat:GroupMessage:42'
        await plugin.guard(event)
        self.assertEqual(plugin._keyword_misses.get(event.unified_msg_origin),1)
        self.assertEqual(plugin._take_trigger(event)[1],'keyword')
        plugin._set_trigger(event,'visitor','keyword')
        event.get_result=lambda:types.SimpleNamespace(get_plain_text=lambda:'',chain=[types.SimpleNamespace(type='Record')])
        await plugin.remember_bot_turn(event)
        self.assertEqual(plugin._keyword_misses.get(event.unified_msg_origin),0)
        self.assertIn(event.unified_msg_origin,plugin.engagement.last_bot_turn)

    async def test_direct_mention_and_disabled_keyword_do_not_count_as_keyword_chances(self):
        plugin=self.plugin();event=Event(group='42',text='能天使',message=[At('bot')])
        await plugin.guard(event)
        self.assertFalse(hasattr(plugin,'_keyword_misses'))
        plugin.config.update(keyword_probability=0,keyword_probability_step=0)
        self.assertFalse(plugin._keyword_allowed('napcat:GroupMessage:42',1000))
        self.assertFalse(hasattr(plugin,'_keyword_misses'))

    async def test_online_return_unloads_a_previous_local_model(self):
        plugin = self.plugin()
        plugin._local_warm = True
        event = Event(group="", text="下班了吗")
        await plugin.guard(event)
        await asyncio.sleep(0)
        plugin.local_model.unload.assert_awaited_once()
        self.assertFalse(plugin._local_warm)
        self.assertFalse(event.stopped)

    async def test_muted_group_stops_commands_mentions_pokes_and_keywords(self):
        plugin = self.plugin()
        plugin.config["mute_groups"] = ["muted"]
        for event in [Event(group="muted", text="/记忆 状态"), Event(group="muted", message=[At("bot")]),
                      Event(group="muted", raw=poke_raw("bot")), Event(group="muted", text="能天使")]:
            await plugin.guard(event)
            self.assertTrue(event.stopped)
            event.send.assert_not_awaited()

    def test_owner_is_big_boss_but_npc_title_is_preserved(self):
        plugin = self.plugin()
        plugin.context.get_registered_star = lambda _: types.SimpleNamespace(star_cls=types.SimpleNamespace(store=types.SimpleNamespace(is_owner=lambda p, u: u == "visitor")))
        self.assertEqual(plugin._addressed_reply(Event(), "老板，老板大帝来了"), "老大，老板大帝来了")
        plugin.context.get_registered_star = lambda _: None
        self.assertEqual(plugin._addressed_reply(Event(), "老板，怎么啦"), "老板，怎么啦")

    async def test_default_offline_message_uses_local_model_and_stops_cloud_path(self):
        plugin = self.plugin(offline=True)
        plugin.local_model.enabled = True
        plugin.local_model.chat.return_value = "先看看当地预报呀！"
        event = Event(group="", text="你觉得今天适合出门吗")
        await plugin.guard(event)
        await asyncio.sleep(0)
        plugin.local_model.chat.assert_awaited_once()
        _system, _user = plugin.local_model.chat.await_args.args
        self.assertTrue(_system.startswith(PLUGIN.LOCAL_SYSTEM))
        self.assertEqual(_user, event.message_str)
        self.assertEqual(event.send.call_args.args[0].chain[0].text, "先看看当地预报呀！")
        self.assertIn("不得编造当前状况", plugin.local_model.chat.call_args.args[0])
        self.assertTrue(event.stopped)

    async def test_rapid_mode_changes_finish_with_unload_after_warmup(self):
        plugin = self.plugin()
        operations = []
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def warmup():
            entered.set()
            await finish.wait()
            operations.append("warmup")

        async def unload():
            operations.append("unload")

        plugin.local_model.warmup.side_effect = warmup
        plugin.local_model.unload.side_effect = unload
        plugin._sync_local_model(True)
        await entered.wait()
        plugin._sync_local_model(False)
        await asyncio.sleep(0)
        self.assertEqual(operations, [])
        finish.set()
        await plugin._local_mode_task
        self.assertEqual(operations, ["warmup", "unload"])

    async def test_manual_mode_command_publishes_cross_platform_signal_immediately(self):
        plugin = self.plugin(offline=True)
        plugin._is_owner = Mock(return_value=True)
        plugin.state.set_manual = Mock()
        event = Event(group="", text="/离线 开")
        event.plain_result = lambda text: text
        responses = [result async for result in plugin.offline(event, "开")]
        await asyncio.sleep(0)
        plugin.state.set_manual.assert_called_once_with("on")
        plugin.state.publish_offline.assert_called_once_with(True, reason="test", resume_at=None)
        self.assertEqual(len(responses), 1)

    async def test_online_raw_poke_to_bot_replies_locally_in_group_and_private_chat(self):
        for group in ("group", ""):
            with self.subTest(group=group):
                plugin = self.plugin()
                event = Event(group=group, raw=poke_raw("bot"))
                await plugin.guard(event)
                self.assertEqual(event.message_str, "")
                self.assertTrue(event.stopped)
                event.send.assert_awaited_once()
                self.assertIn(event.send.call_args.args[0].chain[0].text, PLUGIN.POKE_REPLIES)
                plugin.state.bump_usage.assert_not_called()
                if group:
                    self.assertEqual(event.get_extra("fatfish_engagement_trigger"), ("visitor", "poke"))

    async def test_offline_poke_to_bot_sends_poke_reply_in_group_and_private_chat(self):
        for group in ("group", ""):
            with self.subTest(group=group):
                plugin = self.plugin(offline=True)
                event = Event(group=group, message=[Poke("bot")], raw=poke_raw("bot"))
                await plugin.guard(event)
                self.assertTrue(event.stopped)
                event.send.assert_awaited_once()
                self.assertIn(event.send.call_args.args[0].chain[0].text, PLUGIN.POKE_REPLIES)
                plugin.engine.handle.assert_not_called()

    async def test_component_target_and_legacy_id_are_supported(self):
        legacy_poke = type("Poke", (), {"id": "bot"})()
        for component in (Poke("bot"), legacy_poke):
            plugin = self.plugin()
            event = Event(message=[component])
            await plugin.guard(event)
            self.assertTrue(event.stopped)
            event.send.assert_awaited_once()
            self.assertIn(event.send.call_args.args[0].chain[0].text, PLUGIN.POKE_REPLIES)

    async def test_poking_someone_else_never_triggers_model_or_local_reply(self):
        for offline in (True, False):
            for group in ("group", ""):
                for message in ([], [Poke("other")], [Poke("bot")]):
                    with self.subTest(offline=offline, group=group, message=message):
                        plugin = self.plugin(offline)
                        event = Event(group=group, message=message, raw=poke_raw("other"))
                        await plugin.guard(event)
                        self.assertTrue(event.stopped)
                        self.assertFalse(event.is_at_or_wake_command)
                        event.send.assert_not_called()
                        plugin.engine.handle.assert_not_called()
                        plugin.state.bump_usage.assert_not_called()

    async def test_unknown_poke_target_is_ignored(self):
        event = Event(raw={"post_type": "notice", "notice_type": "notify", "sub_type": "poke"})
        await self.plugin().guard(event)
        self.assertTrue(event.stopped)
        event.send.assert_not_called()

    async def test_empty_at_has_separate_local_reply_online_and_offline(self):
        for offline in (True, False):
            for message in ([At("bot")], [At("bot"), Plain("  ")]):
                with self.subTest(offline=offline, components=len(message)):
                    plugin = self.plugin(offline)
                    event = Event(message=message)
                    await plugin.guard(event)
                    self.assertTrue(event.stopped)
                    event.send.assert_awaited_once()
                    self.assertIn(event.send.call_args.args[0].chain[0].text, PLUGIN.EMPTY_MENTION_REPLIES)
                    self.assertEqual(event.message_str, "")
                    plugin.engine.handle.assert_not_called()
                    self.assertEqual(event.get_extra("fatfish_engagement_trigger"), ("visitor", "mention"))
                    plugin.state.bump_usage.assert_not_called()

    async def test_at_with_text_is_mention_even_if_text_says_poke(self):
        plugin = self.plugin()
        event = Event(message=[At("bot"), Plain("戳一戳是什么")], text="戳一戳是什么")
        await plugin.guard(event)
        self.assertEqual(event.message_str, "戳一戳是什么")
        self.assertEqual(event.get_extra("fatfish_engagement_trigger"), ("visitor", "mention"))
        self.assertFalse(event.stopped)
        event.send.assert_not_called()

    async def test_queued_turns_in_same_group_keep_their_own_engagement_targets(self):
        plugin = self.plugin()
        plugin.engagement.on_bot_sent = Mock()
        first = Event(message=[At("bot"), Plain("first")], text="first")
        second = Event(message=[At("bot"), Plain("second")], text="second")
        first.get_sender_id = lambda: "user-a"
        second.get_sender_id = lambda: "user-b"
        first.get_result = lambda: types.SimpleNamespace(get_plain_text=lambda: "reply-a")
        second.get_result = lambda: types.SimpleNamespace(get_plain_text=lambda: "reply-b")
        await plugin.guard(first)
        await plugin.guard(second)
        await plugin.remember_bot_turn(first)
        self.assertEqual(plugin.engagement.on_bot_sent.call_args.kwargs["target_user"], "user-a")
        await plugin.remember_bot_turn(second)
        self.assertEqual(plugin.engagement.on_bot_sent.call_args.kwargs["target_user"], "user-b")
        self.assertIsNone(first.get_extra("fatfish_engagement_trigger"))
        self.assertIsNone(second.get_extra("fatfish_engagement_trigger"))

    async def test_at_with_image_is_not_treated_as_empty_at_or_poke(self):
        plugin = self.plugin()
        event = Event(message=[At("bot"), Image()])
        await plugin.guard(event)
        self.assertEqual(event.get_extra("fatfish_engagement_trigger"), ("visitor", "mention"))
        self.assertEqual(event.message_str, "")
        event.send.assert_not_called()

    async def test_at_someone_else_is_not_a_poke_or_empty_bot_mention(self):
        for offline in (True, False):
            plugin = self.plugin(offline)
            event = Event(message=[At("other")])
            await plugin.guard(event)
            self.assertFalse(event.is_at_or_wake_command)
            self.assertIsNone(event.get_extra("fatfish_engagement_trigger"))
            event.send.assert_not_called()
            plugin.engine.handle.assert_not_called()

    async def test_model_quota_exhaustion_routes_poke_to_local_reply(self):
        plugin = self.plugin()
        plugin.hourly_model_limit = 1
        plugin.state.bump_usage.return_value = 2
        event = Event(raw=poke_raw("bot"))
        await plugin.guard(event)
        self.assertTrue(event.stopped)
        self.assertFalse(event.is_at_or_wake_command)
        self.assertIn(event.send.call_args.args[0].chain[0].text, PLUGIN.POKE_REPLIES)
        plugin.state.bump_usage.assert_not_called()

    async def test_work_time_special_replies_include_actual_resume_without_crossing_trigger_types(self):
        from datetime import datetime, timedelta

        for message, raw, kind, choices in (
            ([At("bot"), Plain(" ")], None, "mention", PLUGIN.EMPTY_MENTION_REPLIES),
            ([], poke_raw("bot"), "poke", PLUGIN.POKE_REPLIES),
        ):
            with self.subTest(kind=kind):
                plugin = self.plugin(offline=True)
                resume = datetime.now(timezone.utc) + timedelta(hours=1)
                plugin._decision.return_value = PLUGIN.Decision(True, "high_cost", resume)
                event = Event(message=message, raw=raw)
                await plugin.guard(event)
                reply = event.send.call_args.args[0].chain[0].text
                self.assertTrue(any(reply.startswith(choice) for choice in choices))
                self.assertIn("企鹅物流上班", reply)
                self.assertIn(PLUGIN.format_resume(resume, datetime.now(timezone.utc)), reply)
                self.assertEqual(event.get_extra("fatfish_engagement_trigger"), ("visitor", kind))
                self.assertTrue(event.stopped)
                plugin.state.bump_usage.assert_not_called()


class OfflineClockTests(unittest.IsolatedAsyncioTestCase):
    async def test_unattended_clock_crosses_start_and_end_without_rewriting_unchanged_signal(self):
        plugin = OfflinePluginTriggerTests().plugin()
        plugin.scheduler = PLUGIN.Scheduler(["09:00-12:00", "14:00-18:00"], holiday_source="manual")
        plugin.reason = "high_cost"
        plugin._decision = PLUGIN.Main._decision.__get__(plugin)
        moments = [
            datetime(2026, 10, 23, hour, minute, second, tzinfo=plugin.scheduler.tz)
            for hour, minute, second in ((13, 59, 59), (14, 0, 0), (14, 1, 0), (17, 59, 59), (18, 0, 0))
        ]
        current = [moments[0]]

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return current[0].astimezone(tz) if tz else current[0]

        sleeps = []
        real_sleep = asyncio.sleep

        async def advance(delay):
            sleeps.append(delay)
            await real_sleep(0)
            if len(sleeps) == len(moments):
                raise asyncio.CancelledError
            current[0] = moments[len(sleeps)]

        with tempfile.TemporaryDirectory() as directory:
            plugin.state = PLUGIN.StateStore(Path(directory))
            plugin.state.publish_offline = Mock(wraps=plugin.state.publish_offline)
            plugin.state.bump_usage = Mock(wraps=plugin.state.bump_usage)
            with patch.object(PLUGIN, "datetime", Clock), patch.object(PLUGIN.asyncio, "sleep", advance):
                with self.assertRaises(asyncio.CancelledError):
                    await plugin._mode_loop()
                await plugin._local_mode_task
            transitions = [call.args[0] for call in plugin.state.publish_offline.call_args_list]
            self.assertEqual(transitions, [False, True, False])
            self.assertEqual(sleeps, [1, 60, 60, 1, 60])
            plugin.state.bump_usage.assert_not_called()
            plugin.local_model.warmup.assert_awaited_once()
            plugin.local_model.unload.assert_awaited_once()
            self.assertFalse(plugin.state.runtime.get("offline", "signal")["offline"])

    async def test_terminate_cancels_both_independent_timers(self):
        plugin = OfflinePluginTriggerTests().plugin()
        started = []
        stopped = []

        async def timer(name):
            started.append(name)
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(name)

        plugin._mode_timer_task = asyncio.create_task(timer("mode"))
        plugin._daily_apple_pie_task = asyncio.create_task(timer("daily"))
        await asyncio.sleep(0)
        await plugin.terminate()
        self.assertCountEqual(started, ["mode", "daily"])
        self.assertCountEqual(stopped, ["mode", "daily"])
        self.assertTrue(plugin._mode_timer_task.cancelled())
        self.assertTrue(plugin._daily_apple_pie_task.cancelled())
        plugin.local_model.unload.assert_awaited_once()
        plugin.local_model.close.assert_awaited_once()


class DailyApplePiePluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.plugin_count = 0
        self.now = datetime(2026, 10, 23, 18, 1, tzinfo=PLUGIN.Scheduler([]).tz)

    def plugin(self, *, state_directory=None):
        self.plugin_count += 1
        plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        plugin.config = {
            "daily_apple_pie_group_id": "123456",
            "daily_apple_pie_platform_id": "test-qq",
        }
        path = state_directory or Path(self.directory.name) / str(self.plugin_count)
        plugin.state = PLUGIN.StateStore(path)
        plugin.daily_apple_pie = PLUGIN.DailyApplePie(plugin.state, Mock(random=Mock(return_value=0)))
        plugin.context = types.SimpleNamespace(
            get_platform_inst=Mock(return_value=object()),
            send_message=AsyncMock(return_value=True),
        )
        plugin._daily_apple_pie_task = None
        plugin._local_mode_task = None
        plugin._mode_timer_task = None
        plugin.local_model = types.SimpleNamespace(unload=AsyncMock(), close=AsyncMock())
        return plugin

    async def test_empty_group_does_not_draw_or_send(self):
        plugin = self.plugin()
        plugin.config["daily_apple_pie_group_id"] = "  "
        self.assertTrue(await plugin._daily_apple_pie_once(self.now))
        plugin.daily_apple_pie.rng.random.assert_not_called()
        plugin.context.get_platform_inst.assert_not_called()
        plugin.context.send_message.assert_not_called()
        self.assertEqual(plugin.state.daily_apple_pie_state(), {})

    async def test_invalid_group_is_rejected_without_send(self):
        for group in ("not-a-group", "-123456", "0", "１２３４５６", "123 456"):
            with self.subTest(group=group):
                plugin = self.plugin()
                plugin.config["daily_apple_pie_group_id"] = group
                with self.assertRaises(ValueError):
                    await plugin._daily_apple_pie_once(self.now)
                plugin.daily_apple_pie.rng.random.assert_not_called()
                plugin.context.send_message.assert_not_called()
                self.assertEqual(plugin.state.daily_apple_pie_state(), {})

    async def test_platform_not_ready_does_not_consume_draw(self):
        plugin = self.plugin()
        plugin.context.get_platform_inst.return_value = None
        self.assertFalse(await plugin._daily_apple_pie_once(self.now))
        plugin.context.get_platform_inst.assert_called_once_with("test-qq")
        plugin.daily_apple_pie.rng.random.assert_not_called()
        plugin.context.send_message.assert_not_called()
        self.assertEqual(plugin.state.daily_apple_pie_state(), {})
        plugin.context.get_platform_inst.return_value = object()
        self.assertTrue(await plugin._daily_apple_pie_once(self.now))
        plugin.context.send_message.assert_awaited_once()

    async def test_send_uses_only_fixed_line_and_configured_group_session(self):
        plugin = self.plugin()
        self.assertTrue(await plugin._daily_apple_pie_once(self.now))
        plugin.context.send_message.assert_awaited_once()
        target, message = plugin.context.send_message.call_args.args
        self.assertEqual(target, "test-qq:GroupMessage:123456")
        self.assertEqual(len(message.chain), 1)
        self.assertIsInstance(message.chain[0], Plain)
        self.assertEqual(message.chain[0].text, "啊噗噜派！")
        self.assertEqual(plugin.state.daily_apple_pie_state()["status"], "sent")

    async def test_same_day_repeated_ticks_reload_and_changed_group_do_not_resend(self):
        plugin = self.plugin()
        await plugin._daily_apple_pie_once(self.now)
        await plugin._daily_apple_pie_once(self.now.replace(hour=19))
        plugin.config["daily_apple_pie_group_id"] = "654321"
        await plugin._daily_apple_pie_once(self.now.replace(hour=20))
        plugin.context.send_message.assert_awaited_once()
        plugin.daily_apple_pie.rng.random.assert_called_once()
        reloaded = self.plugin(state_directory=plugin.state.dir)
        await reloaded._daily_apple_pie_once(self.now.replace(hour=23))
        reloaded.context.send_message.assert_not_called()
        reloaded.daily_apple_pie.rng.random.assert_not_called()
        self.assertEqual(reloaded.state.daily_apple_pie_state()["status"], "sent")

    async def test_false_or_exception_marks_failed_without_retry(self):
        for failure in (False, RuntimeError("mock send failure")):
            with self.subTest(failure=failure):
                plugin = self.plugin()
                if isinstance(failure, Exception):
                    plugin.context.send_message.side_effect = failure
                else:
                    plugin.context.send_message.return_value = failure
                self.assertTrue(await plugin._daily_apple_pie_once(self.now))
                self.assertEqual(plugin.state.daily_apple_pie_state()["status"], "failed")
                await plugin._daily_apple_pie_once(self.now.replace(hour=19))
                plugin.context.send_message.assert_awaited_once()
                reloaded = self.plugin(state_directory=plugin.state.dir)
                await reloaded._daily_apple_pie_once(self.now.replace(hour=23))
                reloaded.context.send_message.assert_not_called()
                self.assertEqual(reloaded.state.daily_apple_pie_state()["status"], "failed")

    async def test_cancelled_send_leaves_pending_claim_and_does_not_retry(self):
        plugin = self.plugin()
        entered_send = asyncio.Event()

        async def wait_in_send(*args):
            entered_send.set()
            await asyncio.Event().wait()

        plugin.context.send_message.side_effect = wait_in_send
        task = asyncio.create_task(plugin._daily_apple_pie_once(self.now))
        await asyncio.wait_for(entered_send.wait(), timeout=1)
        self.assertEqual(plugin.state.daily_apple_pie_state()["status"], "pending")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        reloaded = self.plugin(state_directory=plugin.state.dir)
        await reloaded._daily_apple_pie_once(self.now.replace(hour=19))
        reloaded.context.send_message.assert_not_called()
        reloaded.daily_apple_pie.rng.random.assert_not_called()
        self.assertEqual(reloaded.state.daily_apple_pie_state()["status"], "pending")

    async def test_terminate_cancels_and_awaits_scheduler_task(self):
        plugin = self.plugin()
        started, finalized = asyncio.Event(), asyncio.Event()

        async def scheduler():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finalized.set()

        plugin._daily_apple_pie_task = asyncio.create_task(scheduler())
        await asyncio.wait_for(started.wait(), timeout=1)
        await plugin.terminate()
        self.assertTrue(finalized.is_set())
        self.assertTrue(plugin._daily_apple_pie_task.done())
        self.assertTrue(plugin._daily_apple_pie_task.cancelled())

    async def test_terminate_without_scheduler_is_safe(self):
        await self.plugin().terminate()


if __name__ == "__main__":
    unittest.main()
