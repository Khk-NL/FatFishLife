from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from plugin_support import load_plugin

PLUGIN = load_plugin("astrbot_plugin_fatfish_bili")
MEMORY = load_plugin("astrbot_plugin_fatfish_memory")
DiscoveryStore = PLUGIN.DiscoveryStore
discover = PLUGIN.discover
A = "BV1xx411c7mD"
B = "BV1xx411c7mE"


def payload(*items):
    return {"ok": True, "data": {"items": list(items)}}


def video(bvid=A, title="公开剧情选题", play=10):
    return {"bvid": bvid, "title": title, "author": {"name": "公开 UP"}, "play": play, "pubdate": "2026-10-23T08:00:00+08:00"}


async def collect(results):
    return "\n".join([result async for result in results])


class Event:
    def __init__(self, owner=True, private=True, admin=False):
        self.owner, self.private, self.admin = owner, private, admin

    def is_admin(self):
        return self.admin

    def get_platform_name(self):
        return "aiocqhttp"

    def get_sender_id(self):
        return "owner" if self.owner else "visitor"

    def is_private_chat(self):
        return self.private

    def plain_result(self, text):
        return text


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "discovery.db"
        self.store = DiscoveryStore(self.path)
        self.remember = Mock(return_value=True)

    async def test_subscriptions_are_persistent_and_duplicate_targets_reuse_id(self):
        first = self.store.subscribe("keyword", "崩铁  新剧情")
        self.assertEqual(self.store.subscribe("keyword", "崩铁 新剧情"), first)
        second = self.store.subscribe("up", "123456")
        reopened = DiscoveryStore(self.path)
        self.assertEqual([row["id"] for row in reopened.subscriptions()], [first, second])
        self.assertTrue(reopened.unsubscribe(first))
        self.assertFalse(reopened.unsubscribe(first))
        self.assertEqual(len(self.store.subscriptions()), 1)
        with self.assertRaises(ValueError):
            self.store.subscribe("up", "not-a-uid")

    async def test_multiple_sources_merge_duplicates_rank_by_play_and_remain_seen_after_restart(self):
        self.store.subscribe("keyword", "崩铁")
        self.store.subscribe("up", "123456")
        run = AsyncMock(side_effect=[payload(video(A, play=20)), payload(video(A, play=25), video(B, play=100))])
        result = await discover(self.store, run, self.remember)
        self.assertEqual([item["bvid"] for item in result["candidates"]], [B, A])
        self.assertEqual(result["candidates"][1]["sources"], ["关键词：崩铁", "UP：123456"])
        self.assertEqual(self.remember.call_count, 2)
        for call in self.remember.call_args_list:
            self.assertEqual(call.kwargs, {"scope": "public", "kind": "video"})
        run.assert_any_await("search", "video", "崩铁", "--order", "new", "--size", "5", timeout=90)
        run.assert_any_await("user", "videos", "123456", "--order", "new", "--size", "5", timeout=90)
        run = AsyncMock(return_value=payload(video(A), video(B)))
        repeated = await discover(DiscoveryStore(self.path), run, self.remember)
        self.assertEqual(repeated["candidates"], [])
        self.assertEqual(self.remember.call_count, 2)

    async def test_one_failed_source_preserves_other_results_and_does_not_mark_failure_as_seen(self):
        self.store.subscribe("keyword", "失败源")
        self.store.subscribe("up", "123456")
        run = AsyncMock(side_effect=[{"ok": False, "error": {"code": "network_error", "message": "来源超时"}, "data": {"items": [video(A)]}}, payload(video(B))])
        result = await discover(self.store, run, self.remember)
        self.assertEqual([item["bvid"] for item in result["candidates"]], [B])
        self.assertIn("network_error", result["errors"][0])
        self.assertFalse(self.store.contains(A))
        self.assertTrue(self.store.contains(B))
        retried = await discover(self.store, AsyncMock(side_effect=[payload(video(A)), payload(video(B))]), self.remember)
        self.assertEqual([item["bvid"] for item in retried["candidates"]], [A])

    async def test_invalid_response_is_reported_instead_of_treated_as_no_results(self):
        self.store.subscribe("keyword", "崩铁")
        result = await discover(self.store, AsyncMock(return_value={"ok": True, "data": {}}), self.remember)
        self.assertEqual(result["candidates"], [])
        self.assertIn("items", result["errors"][0])
        self.remember.assert_not_called()

    async def test_memory_failure_keeps_candidate_available_for_retry(self):
        self.store.subscribe("keyword", "崩铁")
        self.remember.return_value = False
        result = await discover(self.store, AsyncMock(return_value=payload(video())), self.remember)
        self.assertEqual(result["candidates"], [])
        self.assertIn("公开记忆", result["errors"][0])
        self.assertFalse(self.store.contains(A))
        self.remember.return_value = True
        result = await discover(self.store, AsyncMock(return_value=payload(video())), self.remember)
        self.assertEqual(len(result["candidates"]), 1)

    def plugin(self):
        plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        plugin.config = {"owner_qq": "owner"}
        plugin.discovery = self.store
        plugin._discovery_lock = asyncio.Lock()
        plugin._run = AsyncMock(return_value=payload(video()))
        plugin.memory_db = Path(self.directory.name) / "memory.db"
        return plugin

    async def test_new_commands_require_owner_or_admin_private_chat(self):
        plugin = self.plugin()
        for event in (Event(owner=False), Event(private=False), Event(owner=False, private=False, admin=True)):
            for action, text in (("订阅", "关键词 崩铁"), ("退订", "1"), ("发现", "")):
                output = await collect(plugin.bili(event, action, text))
                self.assertIn("私聊", output)
        self.assertEqual(self.store.subscriptions(), [])
        plugin._run.assert_not_awaited()

    async def test_subscription_commands_list_and_remove_without_network_calls(self):
        plugin = self.plugin()
        self.assertIn("已保存", await collect(plugin.bili(Event(), "订阅", "关键词 崩铁")))
        listing = await collect(plugin.bili(Event(), "订阅", ""))
        self.assertIn("1. 关键词 崩铁", listing)
        self.assertIn("已保存", await collect(plugin.bili(Event(owner=False, admin=True), "订阅", "UP 123456")))
        self.assertIn("数字 UID", await collect(plugin.bili(Event(), "订阅", "UP wrong")))
        self.assertIn("已退订", await collect(plugin.bili(Event(), "退订", "1")))
        self.assertEqual(len(self.store.subscriptions()), 1)
        plugin._run.assert_not_awaited()

    async def test_discovery_command_writes_only_public_candidates_without_reading_private_memory(self):
        plugin = self.plugin()
        memory = MEMORY.MemoryStore(plugin.memory_db)
        memory.remember("PRIVATE_TOPIC_TOKEN", scope="private", kind="note")
        self.store.subscribe("keyword", "崩铁")
        output = await collect(plugin.bili(Event(), "发现", ""))
        self.assertIn(A, output)
        self.assertIn("https://www.bilibili.com/video/" + A, output)
        self.assertNotIn("PRIVATE_TOPIC_TOKEN", output)
        rows = memory.recall("公开剧情选题", scopes=("public",))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "video")
        self.assertIn("PRIVATE_TOPIC_TOKEN", memory.recall("", scopes=("private",))[0]["content"])
        self.assertNotIn("PRIVATE_TOPIC_TOKEN", repr(plugin._run.await_args_list))


if __name__ == "__main__":
    unittest.main()
