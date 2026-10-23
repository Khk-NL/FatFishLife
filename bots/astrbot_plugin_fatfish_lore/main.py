"""Keep /设定 as a small adapter to AstrBot's verified native knowledge base."""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.kb_name = str(self.config.get("kb_name") or "苹果乐设定")
        self.max_chars = max(300, min(5000, int(self.config.get("max_chars", 1800))))

    @filter.command("设定")
    async def lore(self, event: AstrMessageEvent, text: GreedyStr = GreedyStr("")):
        query = str(text or "").strip()
        if not query or query in ("目录", "列表", "list", "建库", "入库", "同步知识库"):
            yield event.plain_result(f"使用原生知识库「{self.kb_name}」。查询：/设定 <问题>；文档和索引在 AstrBot 知识库页面管理。")
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
