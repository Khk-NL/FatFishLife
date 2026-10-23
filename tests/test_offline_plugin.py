from __future__ import annotations

import types
import unittest
from datetime import timezone
from unittest.mock import AsyncMock, Mock

from plugin_support import load_plugin


class At:
    def __init__(self, qq):
        self.qq = qq


class Plain:
    def __init__(self, text):
        self.text = text


class Reply:
    pass


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
        self.message_obj = types.SimpleNamespace(message=list(message), message_str=text, raw_message=raw or {})
        self.message_str = text
        self.is_at_or_wake_command = any(isinstance(component, At) and component.qq == "bot" for component in message)
        self.stopped = False
        self.send = AsyncMock()

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
    def plugin(self, offline=False):
        plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        plugin.config = {}
        plugin.enabled = True
        plugin.hourly_model_limit = 0
        plugin.scheduler = types.SimpleNamespace(tz=timezone.utc)
        plugin._decision = Mock(return_value=PLUGIN.Decision(offline, "test" if offline else None))
        plugin.state = types.SimpleNamespace(publish_offline=Mock(), bump_usage=Mock(return_value=1))
        plugin.engagement = PLUGIN.GroupEngagement(PLUGIN.GroupConfig(random_probability=0))
        plugin._pending_trigger = {}
        plugin.engine = types.SimpleNamespace(handle=Mock(return_value="离线普通回复"))
        return plugin

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
                    self.assertEqual(plugin._pending_trigger[group], ("visitor", "poke"))

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
                    self.assertEqual(plugin._pending_trigger, {"group": ("visitor", "mention")})
                    plugin.state.bump_usage.assert_not_called()

    async def test_at_with_text_is_mention_even_if_text_says_poke(self):
        plugin = self.plugin()
        event = Event(message=[At("bot"), Plain("戳一戳是什么")], text="戳一戳是什么")
        await plugin.guard(event)
        self.assertEqual(event.message_str, "戳一戳是什么")
        self.assertEqual(plugin._pending_trigger["group"], ("visitor", "mention"))
        self.assertFalse(event.stopped)
        event.send.assert_not_called()

    async def test_at_with_image_is_not_treated_as_empty_at_or_poke(self):
        plugin = self.plugin()
        event = Event(message=[At("bot"), Image()])
        await plugin.guard(event)
        self.assertEqual(plugin._pending_trigger["group"], ("visitor", "mention"))
        self.assertEqual(event.message_str, "")
        event.send.assert_not_called()

    async def test_at_someone_else_is_not_a_poke_or_empty_bot_mention(self):
        for offline in (True, False):
            plugin = self.plugin(offline)
            event = Event(message=[At("other")])
            await plugin.guard(event)
            self.assertFalse(event.is_at_or_wake_command)
            self.assertEqual(plugin._pending_trigger, {})
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
                self.assertEqual(plugin._pending_trigger["group"], ("visitor", kind))
                self.assertTrue(event.stopped)
                plugin.state.bump_usage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
