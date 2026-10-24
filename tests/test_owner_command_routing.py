"""Owner commands must reach their own permission checks during offline hours."""
import types
import unittest
from unittest.mock import AsyncMock, Mock

import test_offline_plugin as offline_fixture

Event = offline_fixture.Event


class OwnerCommandRoutingTests(unittest.IsolatedAsyncioTestCase):
    def plugin(self):
        return offline_fixture.OfflinePluginTriggerTests().plugin(offline=True)

    async def test_supported_management_commands_are_not_silently_swallowed_offline(self):
        for command in ("/生活 日记", "/视频 状态", "/成本", "/语气 状态", "/知识库 搜索 测试", "/steam 帮助"):
            with self.subTest(command=command):
                plugin = self.plugin()
                event = Event(group="", text=command)
                await plugin.guard(event)
                self.assertFalse(event.stopped)
                event.send.assert_not_awaited()
                plugin.local_model.chat.assert_not_awaited()

    async def test_registered_community_command_reuses_native_permission_routing(self):
        plugin = self.plugin()
        event = Event(group="", text="/community_status")
        handler = types.SimpleNamespace(event_filters=[type("CommandFilter", (), {})()])
        event.get_extra = lambda key, default=None: [handler] if key == "activated_handlers" else default
        await plugin.guard(event)
        self.assertFalse(event.stopped)
        event.send.assert_not_awaited()

    async def test_unknown_command_prefix_is_not_treated_as_a_known_command(self):
        plugin = self.plugin()
        event = Event(group="", text="/bilinotacommand")
        await plugin.guard(event)
        self.assertTrue(event.stopped)
        plugin.local_model.chat.assert_not_awaited()
        event.send.assert_not_awaited()

    async def test_reset_targets_adapter_id_instead_of_platform_type(self):
        plugin = self.plugin()
        plugin._is_owner = Mock(return_value=True)
        manager = types.SimpleNamespace(delete_conversations_by_user_id=AsyncMock())
        plugin.context.conversation_manager = manager
        event = Event(group="", text="/reset 群:123456")
        event.get_platform_id = lambda: "napcat-main"
        event.get_platform_name = lambda: "aiocqhttp"
        for argument, expected in (("群:123456", "napcat-main:GroupMessage:123456"),
                                   ("qq:123456", "napcat-main:FriendMessage:123456")):
            await plugin._reset_target(event, argument)
            manager.delete_conversations_by_user_id.assert_awaited_with(expected)

    async def test_reset_still_denies_non_owner(self):
        plugin = self.plugin()
        plugin._is_owner = Mock(return_value=False)
        manager = types.SimpleNamespace(delete_conversations_by_user_id=AsyncMock())
        plugin.context.conversation_manager = manager
        await plugin._reset_target(Event(group=""), "群:123456")
        manager.delete_conversations_by_user_id.assert_not_awaited()
