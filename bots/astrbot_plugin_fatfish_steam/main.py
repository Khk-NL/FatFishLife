"""Steam public prices on demand, independent of the existing sale tracker."""

from __future__ import annotations

import asyncio

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.star.filter.command import GreedyStr

from fatfish_core import MemoryStore, resolve_shared_db
from fatfish_core.growth import record_capability
from fatfish_core.steam import SteamError, SteamStore, format_result

PLUGIN_NAME = "astrbot_plugin_fatfish_steam"


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self.store = MemoryStore(resolve_shared_db(StarTools.get_data_dir(PLUGIN_NAME).parent.parent))
        self.client = SteamStore(country=self.config.get("country", "cn"), proxy=self.config.get("proxy", ""))

    async def _lookup(self, query):
        try:
            result = await asyncio.to_thread(self.client.lookup, str(query).strip())
        except SteamError as exc:
            record_capability(self.store, "steam", "failed", stage="search", error_code=exc.code)
            return str(exc) + "。可检查商店连接和插件代理配置后重试。"
        except ValueError as exc:
            return str(exc)
        record_capability(self.store, "steam", "success", stage="search")
        return format_result(result)

    @filter.command("steam")
    async def steam(self, event: AstrMessageEvent, query: GreedyStr = GreedyStr("")):
        text = str(query).strip()
        if text.startswith("价格 "):
            text = text[3:].strip()
        if not text:
            yield event.plain_result("用 /steam <游戏名、appid或商店链接> 查询当前公开价格，如 /steam 620。")
            return
        yield event.plain_result(await self._lookup(text))

    @filter.llm_tool(name="fatfish_steam_price")
    async def price_tool(self, event: AstrMessageEvent, query: str):
        """查询 Steam 当前区域公开价格；不需要 Web API Key。

        Args:
            query(string): 游戏名、appid或Steam商店app链接；名称有歧义时返回候选。
        """
        return await self._lookup(query)
