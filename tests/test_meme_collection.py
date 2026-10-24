from __future__ import annotations

import importlib.util
import io
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("meme_collection", ROOT / "bots/astrbot_plugin_fatfish_offline/meme_collection.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MessageImage:
    def __init__(self, path):
        self.convert_to_file_path = AsyncMock(return_value=str(path))


def event(text="", *, user="alice", session="group:one", images=()):
    return types.SimpleNamespace(
        unified_msg_origin=session, message_obj=types.SimpleNamespace(message_str=text), message_str=text,
        get_sender_id=lambda: user, get_messages=lambda: images, stop_event=Mock(),
        plain_result=lambda value: value, send=AsyncMock(),
    )


def png(color="red", size=(600, 150)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


class ResizeTests(unittest.TestCase):
    def test_exact_square_without_crop_or_stretch(self):
        content, extension = module.resize_meme(png())
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual(image.size, (300, 300))
            self.assertEqual(image.getpixel((0, 0))[3], 0)
            self.assertEqual(image.getpixel((150, 150)), (255, 0, 0, 255))
            self.assertEqual(image.getbbox(), (0, 112, 300, 187))
        self.assertEqual(extension, ".png")

    def test_animation_and_per_frame_timing(self):
        stream = io.BytesIO()
        Image.new("RGB", (120, 60), "red").save(
            stream, format="GIF", save_all=True, append_images=[Image.new("RGB", (120, 60), "blue")],
            duration=[80, 170], loop=2,
        )
        content, extension = module.resize_meme(stream.getvalue())
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual((image.size, image.n_frames, image.info["loop"]), ((300, 300), 2, 2))
            self.assertEqual(image.info["duration"], 80)
            image.seek(1)
            self.assertEqual(image.info["duration"], 170)
        self.assertEqual(extension, ".gif")

    def test_invalid_file_rejected(self):
        with self.assertRaises(OSError):
            module.resize_meme(b"invalid")

    def test_favorites_deduplicate_without_removing_other_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory)
            other = pack / "memes/其他"
            other.mkdir(parents=True)
            content = png()
            (other / "original.png").write_bytes(content)
            saved = module.write_favorite(pack, content, ".png")
            self.assertEqual(saved.parent.name, "收藏")
            self.assertTrue((other / "original.png").exists())
            self.assertIsNone(module.write_favorite(pack, content, ".png"))


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.collector = module.MemeCollection(Mock())
        self.collector._manager = Mock(return_value=object())
        self.collector._save = AsyncMock(return_value="已收藏")
        components = types.ModuleType("astrbot.api.message_components")
        components.Image = MessageImage
        self.patcher = patch.dict("sys.modules", {"astrbot.api.message_components": components})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_only_next_image_from_same_user_and_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.png"
            path.write_bytes(png())
            image = MessageImage(path)
            command = event("\\表情 收藏")
            self.assertTrue(await self.collector.handle(command))
            command.stop_event.assert_called_once()
            self.assertFalse(await self.collector.handle(event(images=[image], user="bob")))
            self.assertFalse(await self.collector.handle(event(images=[image], session="group:two")))
            self.assertFalse(await self.collector.handle(event("下一条发图")))
            incoming = event(images=[image, image])
            self.assertTrue(await self.collector.handle(incoming))
            self.collector._save.assert_awaited_once()
            image.convert_to_file_path.assert_awaited_once()
            incoming.stop_event.assert_called_once()
            self.assertFalse(await self.collector.handle(event(images=[image])))

    async def test_cancel_and_expiration(self):
        await self.collector.handle(event("/表情 收藏"))
        await self.collector.handle(event("\\表情 取消"))
        self.assertFalse(self.collector.pending)
        await self.collector.handle(event("/表情 收藏"))
        with patch.object(module.time, "monotonic", return_value=10**12):
            self.assertFalse(await self.collector.handle(event(images=[MessageImage("unused")])))
        self.collector._save.assert_not_awaited()


class SaveTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_uses_manager_lock_metadata_and_index(self):
        plugin = Mock()
        plugin.semantic_vision_provider_id = "vision"
        plugin._resolve_runtime_pack_context.return_value = {"pack_id": "pack", "pack_dir": "/pack"}
        plugin.reload_emotions = AsyncMock()
        plugin.semantic_task_manager.rebuild_index = AsyncMock()
        classifier = Mock()
        classifier._classify = AsyncMock(return_value={"caption": "开心大笑", "tags": ["开心"]})
        collection = Mock()
        collection.AutoCollectManager.return_value = classifier
        collection.AutoCollectManager._write_pack_image.return_value = Path("/pack/memes/收藏/test.png")
        storage = Mock()
        collector = module.MemeCollection(Mock())
        collector._manager = Mock(return_value=plugin)
        with patch.object(module.importlib, "import_module", side_effect=[collection, storage]), patch.object(module, "write_favorite", return_value=Path("/pack/memes/收藏/test.png")):
            result = await collector._save(event(), png(), ".png")
        self.assertIn("语义描述、标签和检索索引均已更新", result)
        plugin.semantic_task_manager.begin_external_pack_operation.assert_called_once()
        plugin.semantic_task_manager.end_external_pack_operation.assert_called_once()
        plugin.semantic_task_manager.rebuild_index.assert_awaited_once_with("pack", force=False)
        decision = storage.save_collected_image_semantic.call_args.args[2]
        self.assertEqual(decision["semantic_category"], "收藏")

    async def test_caption_failure_still_collects_and_reports_pending(self):
        plugin = Mock()
        plugin.semantic_vision_provider_id = "vision"
        plugin._resolve_runtime_pack_context.return_value = {"pack_id": "pack", "pack_dir": "/pack"}
        plugin.reload_emotions = AsyncMock()
        classifier = Mock()
        classifier._classify = AsyncMock(side_effect=RuntimeError("unavailable"))
        collection, storage = Mock(), Mock()
        collection.AutoCollectManager.return_value = classifier
        collection.AutoCollectManager._write_pack_image.return_value = Path("/pack/memes/收藏/test.png")
        logger_module = types.ModuleType("astrbot.api")
        logger_module.logger = Mock()
        collector = module.MemeCollection(Mock())
        collector._manager = Mock(return_value=plugin)
        with patch.dict("sys.modules", {"astrbot.api": logger_module}):
            with patch.object(module.importlib, "import_module", side_effect=[collection, storage]), patch.object(module, "write_favorite", return_value=Path("/pack/memes/收藏/test.png")):
                result = await collector._save(event(), png(), ".png")
        self.assertIn("已收藏", result)
        self.assertIn("语义识别暂未成功", result)
        self.assertEqual(storage.save_collected_image_semantic.call_args.args[2], {})
        plugin.semantic_task_manager.end_external_pack_operation.assert_called_once()
