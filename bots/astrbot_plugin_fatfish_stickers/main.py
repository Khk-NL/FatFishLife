"""AstrBot plugin: 苹果乐/能天使表情包库。

/表情                 随机发一张
/表情 <关键词>        按标签或文件名发一张
/表情 收藏 [标签]     把当前消息里的图片收进库（主人直接入库，其他人待审）
/表情 待审            主人查看待审核
/表情 通过 <id> [标签] 主人通过并可选改标签
/表情 拒绝 <id>       主人拒绝
/表情 列表 [关键词]   查看已入库表情
"""

from __future__ import annotations

from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.filter.command import GreedyStr

from .library import StickerLibrary

PLUGIN_NAME = "astrbot_plugin_fatfish_stickers"
HELP_TEXT = """表情包命令：
/表情                随机一张
/表情 苹果乐         按关键词找
/表情 收藏 [标签]    收下当前图片（主人直接入库，其他人待审）
/表情 待审           主人查看待审核
/表情 通过 <id> [标签]
/表情 拒绝 <id>
/表情 列表 [关键词]"""


def _split_tags(raw: str) -> list[str]:
    return [tag.strip() for tag in raw.replace("，", ",").split(",") if tag.strip()]


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        self.library = StickerLibrary(self.data_dir)
        logger.info(
            f"sticker library ready: approved={len(self.library.approved())} "
            f"pending={len(self.library.pending())}"
        )

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        if event.is_admin():
            return True
        owner_qq = str(self.config.get("owner_qq") or "").strip()
        return bool(owner_qq) and str(event.get_sender_id() or "") == owner_qq

    async def _message_images(self, event: AstrMessageEvent) -> list[Path]:
        results: list[Path] = []
        for component in getattr(event.message_obj, "message", None) or []:
            if not isinstance(component, Image):
                continue
            try:
                path = Path(await component.convert_to_file_path())
            except Exception as exc:
                logger.warning(f"读取图片失败：{exc}")
                continue
            if path.exists():
                results.append(path)
        return results

    async def _send_sticker(self, event: AstrMessageEvent, keyword: str = "") -> None:
        picked = self.library.pick(keyword)
        if not picked:
            hint = "还没有能发的表情，发图并带上 /表情 收藏 就能入库。" if not keyword else f"没找到「{keyword}」相关的表情。"
            await event.send(MessageChain([Plain(hint)]))
            return
        sticker_id, item = picked
        path = self.library.path(item)
        if not path.exists():
            await event.send(MessageChain([Plain(f"表情 {sticker_id} 的文件丢了。")]))
            return
        await event.send(MessageChain([Image.fromFileSystem(str(path))]))

    @filter.command("表情")
    async def sticker(self, event: AstrMessageEvent, action: str = "", text: GreedyStr = GreedyStr("")):
        command = (action or "").strip()
        argument = str(text or "").strip()

        if command in ("", "随机", "来一个"):
            await self._send_sticker(event)
            return
        if command in ("帮助", "help"):
            await event.send(MessageChain([Plain(HELP_TEXT)]))
            return
        if command in ("收藏", "添加"):
            images = await self._message_images(event)
            if not images:
                await event.send(MessageChain([Plain("把图片和 /表情 收藏 一起发，或先发图再加标签。")]))
                return
            owner = self._is_owner(event)
            tags = _split_tags(argument) or ["未分类"]
            saved = []
            for image in images:
                saved.append(self.library.add(image, tags, owner, source="qq", added_by=str(event.get_sender_id())))
            if owner:
                await event.send(MessageChain([Plain(f"已入库 {len(saved)} 张，标签：{'、'.join(tags)}")]))
            else:
                await event.send(MessageChain([Plain(f"收到 {len(saved)} 张，等主人审核。")]))
            return
        if command in ("待审", "审核"):
            if not self._is_owner(event):
                await event.send(MessageChain([Plain("只有主人能看待审队列。")]))
                return
            pending = self.library.pending()
            if not pending:
                await event.send(MessageChain([Plain("没有待审核的表情。")]))
                return
            lines = [f"待审核 {len(pending)} 张："]
            for sticker_id, item in list(pending.items())[:30]:
                lines.append(f"{sticker_id}：{'、'.join(item.get('tags') or ['未分类'])}")
            lines.append("/表情 通过 <id> [标签] 或 /表情 拒绝 <id>")
            await event.send(MessageChain([Plain("\n".join(lines))]))
            return
        if command in ("通过", "approve"):
            if not self._is_owner(event):
                await event.send(MessageChain([Plain("只有主人能审核。")]))
                return
            parts = argument.split(maxsplit=1)
            if not parts:
                await event.send(MessageChain([Plain("用法：/表情 通过 3 苹果乐,能天使")]))
                return
            tags = _split_tags(parts[1]) if len(parts) > 1 else None
            item = self.library.approve(parts[0], tags)
            if not item:
                await event.send(MessageChain([Plain(f"没有编号 {parts[0]} 的表情。")]))
                return
            await event.send(MessageChain([Plain(f"已通过 {parts[0]}：{'、'.join(item.get('tags') or [])}")]))
            return
        if command in ("拒绝", "reject"):
            if not self._is_owner(event):
                await event.send(MessageChain([Plain("只有主人能审核。")]))
                return
            if self.library.reject(argument.split(maxsplit=1)[0] if argument else ""):
                await event.send(MessageChain([Plain(f"已拒绝 {argument}。")]))
            else:
                await event.send(MessageChain([Plain(f"没有编号 {argument} 的表情。")]))
            return
        if command in ("列表", "list"):
            approved = self.library.approved()
            if not approved:
                await event.send(MessageChain([Plain("库里还没有表情。")]))
                return
            lines = [f"已入库 {len(approved)} 张："]
            for sticker_id, item in list(approved.items())[:40]:
                lines.append(f"{sticker_id}：{'、'.join(item.get('tags') or ['未分类'])}")
            await event.send(MessageChain([Plain("\n".join(lines))]))
            return

        keyword = f"{command} {argument}".strip()
        await self._send_sticker(event, keyword)
