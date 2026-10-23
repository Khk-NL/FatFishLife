import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from plugin_support import load_plugin


class LoreAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_command_uses_native_retrieval_and_bounds_output(self):
        module = load_plugin("astrbot_plugin_fatfish_lore")
        plugin = module.Main.__new__(module.Main)
        plugin.context = SimpleNamespace(kb_manager=SimpleNamespace(retrieve=AsyncMock(return_value={"context_text": "资料" * 1000})))
        plugin.kb_name, plugin.max_chars = "苹果乐设定", 300
        event = SimpleNamespace(plain_result=lambda text: text)
        result = [item async for item in plugin.lore(event, "人物关系")]
        self.assertEqual(len(result[0]), 300)
        self.assertEqual(plugin.context.kb_manager.retrieve.await_args.kwargs["query"], "人物关系")
        self.assertFalse(hasattr(plugin, "sections"))
        self.assertFalse(hasattr(plugin, "lore_lookup"))
