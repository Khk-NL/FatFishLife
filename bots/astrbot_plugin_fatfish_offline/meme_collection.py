"""Explicit, conversation-scoped collection into the installed meme_manager."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import io
import os
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

CATEGORY = "收藏"
DESCRIPTION = "用户主动收藏的聊天表情，根据图片内容和使用场景检索"


def write_favorite(pack_dir: Path, content: bytes, extension: str) -> Path | None:
    """Deduplicate within favorites; an image may already belong to another category."""
    root = (pack_dir / "memes").resolve()
    directory = root / CATEGORY
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise ValueError("收藏目录无效")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (hashlib.sha256(content).hexdigest() + extension)
    if destination.exists():
        return None
    # Also recognize files saved by the manager's timestamp-based upload naming.
    for previous in directory.glob(f"*_{destination.stem[:12]}{extension}"):
        if hashlib.sha256(previous.read_bytes()).hexdigest() == destination.stem:
            return None
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def resize_meme(content: bytes) -> tuple[bytes, str]:
    """Fit onto an exact 300 px square without cropping; retain animation."""
    if len(content) > 20 * 1024 * 1024:
        raise ValueError("图片不能超过 20 MB")
    with Image.open(io.BytesIO(content)) as source:
        if source.width * source.height > 40_000_000:
            raise ValueError("图片像素过大")
        animated = getattr(source, "is_animated", False)
        frames, durations = [], []
        for frame in ImageSequence.Iterator(source):
            if len(frames) >= 500:
                raise ValueError("动图不能超过 500 帧")
            rgba = ImageOps.exif_transpose(frame).convert("RGBA")
            frames.append(ImageOps.pad(rgba, (300, 300), Image.Resampling.LANCZOS, color=(255, 255, 255, 0)))
            durations.append(frame.info.get("duration", 100))
        output = io.BytesIO()
        if animated:
            options = {"loop": source.info["loop"]} if "loop" in source.info else {}
            frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:],
                           duration=durations, disposal=2, **options)
            return output.getvalue(), ".gif"
        frames[0].save(output, format="PNG")
        return output.getvalue(), ".png"


class MemeCollection:
    def __init__(self, context):
        self.context = context
        self.pending: dict[tuple[str, str], float] = {}

    def _manager(self):
        for star in self.context.get_all_stars():
            if star.root_dir_name == "meme_manager" and star.activated and star.star_cls:
                return star.star_cls
        raise RuntimeError("表情管理器未启用，请先启用 meme_manager")

    async def handle(self, event) -> bool:
        now = time.monotonic()
        self.pending = {key: expires for key, expires in self.pending.items() if expires > now}
        key = (str(event.unified_msg_origin), str(event.get_sender_id()))
        text = str(getattr(event.message_obj, "message_str", "") or event.message_str or "").strip()
        command = text.replace("\\", "/", 1) if text.startswith("\\") else text
        if command in ("/表情 收藏", "/表情 取消"):
            event.stop_event()
            if command.endswith("取消"):
                self.pending.pop(key, None)
                await event.send(event.plain_result("已取消收藏。"))
            else:
                try:
                    self._manager()
                except RuntimeError as exc:
                    await event.send(event.plain_result(str(exc)))
                    return True
                self.pending[key] = now + 300
                await event.send(event.plain_result("请在 5 分钟内发送下一张图片，我会调整到 300×300 并存入表情管理器的「收藏」分类。"))
            return True
        if key not in self.pending:
            return False
        from astrbot.api.message_components import Image as MessageImage

        images = [part for part in event.get_messages() if isinstance(part, MessageImage)]
        if not images:
            return False
        self.pending.pop(key)
        event.stop_event()
        try:
            async with asyncio.timeout(120):
                source = Path(await images[0].convert_to_file_path())
                if source.stat().st_size > 20 * 1024 * 1024:
                    raise ValueError("图片不能超过 20 MB")
                content, extension = await asyncio.to_thread(resize_meme, await asyncio.to_thread(source.read_bytes))
            message = await self._save(event, content, extension)
        except Exception as exc:
            from astrbot.api import logger

            logger.warning(f"主动收藏表情失败：{type(exc).__name__}")
            message = "收藏失败，请重新输入 \\表情 收藏 后发送图片。请检查图片格式、大小及表情包是否正在执行其他任务。"
        await event.send(event.plain_result(message))
        return True

    async def _save(self, event, content: bytes, extension: str) -> str:
        plugin = self._manager()
        package = type(plugin).__module__.rsplit(".", 1)[0]
        collection = importlib.import_module(f"{package}.backend.auto_collect")
        storage = importlib.import_module(f"{package}.backend.semantic.storage")
        route = plugin._resolve_runtime_pack_context(event=event)
        pack_id, pack_dir = route["pack_id"], Path(route["pack_dir"])
        decision = {}
        try:
            async with asyncio.timeout(60):
                vision_id = plugin.semantic_vision_provider_id or plugin.auto_collect_manager.vision_provider_id
                if not vision_id:
                    vision_id = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
                classifier = collection.AutoCollectManager(plugin, {"vision_provider_id": vision_id})
                decision = await classifier._classify(content, extension, {CATEGORY: DESCRIPTION})
            if not decision.get("caption") or not decision.get("tags"):
                decision = {}
        except Exception as exc:
            from astrbot.api import logger

            logger.warning(f"收藏图片语义识别未完成：{type(exc).__name__}")
        if decision:
            # The category is explicitly chosen by the user, rather than inferred.
            decision["semantic_category"] = CATEGORY
        tasks = plugin.semantic_task_manager
        tasks.begin_external_pack_operation(pack_id, "主动收藏表情")
        try:
            storage._ensure_pack_category(pack_dir, CATEGORY, DESCRIPTION)
            saved = await asyncio.to_thread(write_favorite, pack_dir, content, extension)
            if saved is None:
                return "这张图片已在「收藏」分类中，无需重复收藏。"
            try:
                storage.save_collected_image_semantic(pack_dir, saved, decision, manual_confirmed=True)
            except Exception:
                saved.unlink(missing_ok=True)
                raise
        finally:
            tasks.end_external_pack_operation(pack_id)
        try:
            await plugin.reload_emotions()
        except Exception:
            return "图片已保存到「收藏」分类（300×300），但表情管理器刷新失败，请在管理页重新加载。"
        if not decision:
            return "已收藏到「收藏」分类，尺寸 300×300；语义识别暂未成功，可在表情管理器中重试生成描述。"
        try:
            async with asyncio.timeout(60):
                await tasks.rebuild_index(pack_id, force=False)
        except Exception:
            return "已收藏到「收藏」分类，尺寸 300×300，描述和标签已生成；检索索引暂未更新，可在表情管理器中重试。"
        return "已收藏到「收藏」分类，尺寸 300×300，语义描述、标签和检索索引均已更新。"
