from __future__ import annotations

import asyncio
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from plugin_support import load_plugin

from fatfish_core.memory import MemoryStore
from fatfish_story.review import ReviewQueue


components = types.ModuleType("astrbot.api.message_components")
components.Image = types.SimpleNamespace(fromFileSystem=lambda path: {"image": path})
components.Video = types.SimpleNamespace(fromFileSystem=lambda path: {"video": path})
PLUGIN = load_plugin("astrbot_plugin_fatfish_story", module_overrides={"astrbot.api.message_components": components})


class Event:
    def __init__(self, *, sender="owner", private=True, platform="aiocqhttp", admin=False):
        self.sender, self.private, self.platform, self.admin = sender, private, platform, admin
        self.unified_msg_origin = "napcat:FriendMessage:" + sender
        self.send = AsyncMock()

    def is_private_chat(self): return self.private
    def is_admin(self): return self.admin
    def get_sender_id(self): return self.sender
    def get_platform_name(self): return self.platform
    def plain_result(self, text): return text
    def chain_result(self, chain): return chain


class StoryPluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = MemoryStore(self.root / "memory.db")
        self.bili = types.SimpleNamespace(config={"owner_qq": "owner"}, exe="bili", home=self.root / "bili")
        plugins = {"astrbot_plugin_fatfish_bili": self.bili, "astrbot_plugin_fatfish_memory": types.SimpleNamespace(store=self.store)}
        self.plugin = PLUGIN.Main.__new__(PLUGIN.Main)
        self.plugin.context = types.SimpleNamespace(get_registered_star=lambda name: types.SimpleNamespace(star_cls=plugins[name], activated=True) if name in plugins else None)
        self.plugin.config = {"tags": "公开话题,短视频", "zone": 1, "tid": 17}
        self.plugin.directory = self.root
        self.plugin.queue = ReviewQueue(self.root / "reviews")
        self.plugin._lock = asyncio.Lock()
        self.plugin._growth = Mock()
        self.event = Event()
        video, cover = self.root / "film.mp4", self.root / "film.jpg"
        video.write_bytes(b"video")
        cover.write_bytes(b"cover")
        report = video.with_suffix(".result.json")
        report.write_text(json.dumps({"schema_version": 1, "status": "completed", "video": str(video), "cover": str(cover), "report": str(report)}), encoding="utf-8")
        self.row = self.plugin.queue.create(video, self.plugin._metadata(topic="公开选题", title="标题"), topic="公开选题", **self.plugin._identity(self.event))

    async def invoke(self, action, text="", event=None):
        return [result async for result in self.plugin.video(event or self.event, action, text)]

    async def test_only_owner_qq_private_can_operate(self):
        for event in (Event(private=False), Event(sender="stranger", admin=True), Event(platform="telegram")):
            result = await self.invoke("确认", self.row["id"], event)
            self.assertIn("只在老板", result[0])
        self.assertEqual(self.plugin.queue.get(self.row["id"], **self.plugin._identity(self.event))["status"], "pending_preview")

    async def test_preview_sends_video_and_metadata_then_enables_approval(self):
        result = await self.invoke("预览", self.row["id"])
        self.assertEqual(result, [])
        self.assertEqual(self.event.send.await_count, 3)
        self.assertEqual(self.event.send.call_args_list[0].args[0][0]["image"], self.row["cover"])
        self.assertEqual(self.event.send.call_args_list[1].args[0][0]["video"], self.row["video"])
        self.assertIn("/视频 确认 " + self.row["id"], self.event.send.call_args_list[2].args[0])
        self.assertEqual(self.plugin.queue.get(self.row["id"], **self.plugin._identity(self.event))["status"], "awaiting_approval")
        self.plugin._growth.assert_called_with("review", "success")

    async def test_failed_send_never_enables_approval(self):
        self.event.send.side_effect = RuntimeError("platform send failed")
        result = await self.invoke("预览", self.row["id"])
        self.assertIn("失败", result[0])
        self.assertEqual(self.plugin.queue.get(self.row["id"], **self.plugin._identity(self.event))["status"], "pending_preview")
        self.plugin._growth.assert_called_with("review", "failed", "service_error")

    async def test_config_change_generates_new_review_and_approval_code(self):
        self.plugin.config["tags"] = "更新标签"
        await self.invoke("预览", self.row["id"])
        original = self.plugin.queue.get(self.row["id"], **self.plugin._identity(self.event))
        self.assertEqual(original["status"], "superseded")
        updated = self.plugin.queue.get(original["replaced_by"], **self.plugin._identity(self.event))
        self.assertEqual(updated["metadata"]["tags"], ["更新标签"])
        self.assertEqual(updated["status"], "awaiting_approval")

    async def test_public_topic_list_excludes_private_events(self):
        self.store.remember("PUBLIC_TOPIC", scope="public", kind="video")
        self.store.remember("PRIVATE_SECRET", scope="private", kind="video")
        output = await self.invoke("选题")
        self.assertIn("PUBLIC_TOPIC", output[0])
        self.assertNotIn("PRIVATE_SECRET", output[0])

    async def test_confirmation_calls_publisher_only_after_preview(self):
        await self.invoke("预览", self.row["id"])
        with patch("fatfish_story.review.publish", return_value=Mock(as_dict=lambda: {"url": "https://www.bilibili.com/video/BV1234567890"})) as upload:
            output = await self.invoke("确认", self.row["id"])
        upload.assert_called_once()
        self.assertIn("已提交审核", output[0])
        self.plugin._growth.assert_called_with("publish", "success")

    async def test_concurrent_work_returns_busy_without_spawning_another_render(self):
        async with self.plugin._lock:
            with patch.object(self.plugin, "_create", new_callable=AsyncMock) as create:
                result = await self.invoke("制作", "公开话题")
                create.assert_not_awaited()
        self.assertIn("还在处理", result[0])


if __name__ == "__main__":
    unittest.main()
