"""Keep /设定 as a small adapter to AstrBot's verified native knowledge base."""

from pathlib import Path

import asyncio

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr

from .prts import fetch_page

DEFAULT_KNOWLEDGE_DIR = Path("D:/Code/Projects/FatFishLife/docs/knowledge")
DEFAULT_PERSONA_DIR = Path("D:/Code/Projects/FatFishLife/docs/persona")


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.kb_name = str(self.config.get("kb_name") or "苹果乐设定")
        self.max_chars = max(300, min(5000, int(self.config.get("max_chars", 1800))))

    @filter.llm_tool(name="prts_lookup")
    async def prts_lookup(self, event: AstrMessageEvent, title: str):
        """查询明日方舟 PRTS wiki 的角色、势力、剧情设定。只在需要时查，不要凭记忆编。

        Args:
            title(string): PRTS 页面标题，例如「能天使」「德克萨斯」「拉特兰」「能天使/语音记录」
        """
        try:
            text = await asyncio.to_thread(fetch_page, title)
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(f"PRTS 查不到「{title}」：{exc}")
            return
        yield event.plain_result(text[: self.max_chars])

    async def _import_docs(self, event: AstrMessageEvent):
        helper = await self.context.kb_manager.get_kb_by_name(self.kb_name)
        if not helper:
            yield event.plain_result(f"知识库「{self.kb_name}」不存在，请先在 AstrBot 知识库页面创建。")
            return
        files = sorted(DEFAULT_KNOWLEDGE_DIR.rglob("*.md"))
        voice = DEFAULT_PERSONA_DIR / "exusiai-voice.md"
        if voice.is_file():
            files.append(voice)
        imported, failed = [], []
        for path in files:
            try:
                await helper.upload_document(
                    file_name=path.name,
                    file_content=path.read_bytes(),
                    file_type="md",
                )
                imported.append(path.name)
            except Exception as exc:
                logger.exception("导入知识库文档失败：%s", path)
                failed.append(f"{path.name}：{exc}")
        lines = [f"导入完成，共 {len(imported)} 个文件："]
        lines += [f"- {name}" for name in imported]
        if failed:
            lines.append("失败：")
            lines += [f"- {item}" for item in failed]
        yield event.plain_result("\n".join(lines))

    @filter.command("设定")
    async def lore(self, event: AstrMessageEvent, text: GreedyStr = GreedyStr("")):
        query = str(text or "").strip()
        if query in ("导入", "同步", "导入资料"):
            if not event.is_private_chat():
                yield event.plain_result("导入只在私聊里执行。")
                return
            async for message in self._import_docs(event):
                yield message
            return
        if not query or query in ("目录", "列表", "list", "建库", "入库", "同步知识库"):
            yield event.plain_result(f"使用原生知识库「{self.kb_name}」。查询：/设定 <问题>；导入：/设定 导入。")
            return
        try:
            result = await self.context.kb_manager.retrieve(
                query=query, kb_names=[self.kb_name], top_k_fusion=20, top_m_final=3,
            )
        except Exception:
            logger.exception("原生设定知识库检索失败")
            yield event.plain_result("知识库暂时无法检索，请检查嵌入服务和索引；先不编。")
            return
        content = (result or {}).get("context_text") or "设定库里没有找到相关资料，先不编。"
        yield event.plain_result(content[:self.max_chars])
