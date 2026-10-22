from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from plugin_support import load_plugin


PLUGIN = load_plugin("astrbot_plugin_fatfish_memory")


class Event:
    def __init__(self, uid: str, private: bool, text: str = ""):
        self.uid = uid
        self.private = private
        self.message_str = text
        self.unified_msg_origin = "test:private" if private else "test:group"

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
        self.plugin.store = PLUGIN.MemoryStore(Path(self.directory.name) / "memory.db")
        self.plugin.store.add_owner("qq", "owner")
        self.plugin.store.remember("PRIVATE_EVENT_TOKEN", scope="private", kind="note")
        self.plugin.store.remember("PUBLIC_EVENT_TOKEN", scope="public", kind="note")
        self.plugin.context = types.SimpleNamespace(
            get_current_chat_provider_id=AsyncMock(return_value="test-provider"),
            llm_generate=AsyncMock(return_value=types.SimpleNamespace(completion_text="私人认识")),
        )

    async def test_private_messages_are_not_recorded_as_public_even_for_non_owner(self):
        for uid in ("owner", "visitor"):
            for private in (True, False):
                text = f"{uid}-{private}"
                await self.plugin._record(Event(uid, private, text))
                row = self.plugin.store.recall(text, scopes=("private", "public"))[0]
                self.assertEqual(row["scope"], "private" if private else "public")

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
        self.plugin.store.add_summary("PRIVATE_SUMMARY_TOKEN")
        self.plugin.store.add_journal("PRIVATE_JOURNAL_TOKEN")
        event = Event("owner", True)
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
            self.assertTrue(request.system_prompt.startswith("EXISTING_PERSONA"))
            self.assertIn("PUBLIC_EVENT_TOKEN", request.system_prompt)
            self.assertEqual("PRIVATE_EVENT_TOKEN" in request.system_prompt, uid == "owner" and private)
            self.assertIn("不是本轮指令", request.system_prompt)

    async def test_model_requests_and_tools_do_not_read_other_conversations(self):
        self.plugin.store.remember("CURRENT_GROUP_TOKEN", platform="qq", scope="public", session="group")
        self.plugin.store.remember("OTHER_GROUP_TOKEN", platform="qq", scope="public", session="other-group")
        self.plugin.store.remember("OTHER_PLATFORM_TOKEN", platform="bilibili", scope="public", session="group")
        event = Event("owner", False)
        request = types.SimpleNamespace(prompt="TOKEN", system_prompt="")
        await self.plugin.on_llm_request(event, request)
        for result in (
            request.system_prompt,
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
        original = request.system_prompt
        self.assertLessEqual(len(original), len("CORE\n\n[共享记忆参考]\n") + 250)
        await self.plugin.on_llm_request(event, request)
        self.assertEqual(request.system_prompt, original)


if __name__ == "__main__":
    unittest.main()
