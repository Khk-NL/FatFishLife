"""Small request hygiene and measured cost reports; no extra model self-checks."""
import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import json

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.agent.message import TextPart
from fatfish_core import MemoryStore, resolve_shared_db
from fatfish_core.context_policy import normalize_history
from fatfish_core.costs import read_cost_report


class Main(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self.directory = StarTools.get_data_dir("astrbot_plugin_fatfish_context")
        self.data = self.directory.parent.parent
        self.store = MemoryStore(resolve_shared_db(self.data))
        self._task = asyncio.create_task(self._monitor())

    @filter.on_llm_request(priority=-500)
    async def bounded_history(self, event: AstrMessageEvent, req):
        if not self.config.get("enabled", True):
            return
        req.contexts, stats = normalize_history(req.contexts, image_turns=max(0, min(2, int(self.config.get("image_history_turns", 1)))))
        images = list(req.image_urls or [])
        limit = max(1, min(4, int(self.config.get("max_current_images", 2))))
        if len(images) > limit:
            req.image_urls = images[:limit]
            req.extra_user_content_parts.append(TextPart(text=f"本次有{len(images)}张图片，仅处理前{limit}张；请简短说明其余图片需要分次发送。"))
        if any(stats.values()):
            logger.info("上下文媒体整理：" + json.dumps(stats))

    def report(self):
        now = datetime.now(timezone.utc)
        return read_cost_report(self.data / "data_v4.db", now - timedelta(hours=24), now,
                                local_provider_ids={"fatfish_context_local"},
                                warning_cny=float(self.config.get("cost_warning_cny", 5)))

    @filter.command("成本")
    async def costs(self, event: AstrMessageEvent):
        qq = str(event.get_platform_name()).startswith(("aiocqhttp", "qq_official"))
        if not qq or not event.is_private_chat() or not self.store.is_owner("qq", str(event.get_sender_id())):
            yield event.plain_result("成本统计请由老大私聊查看。")
            return
        report = await asyncio.to_thread(self.report)
        if not report["available"]:
            yield event.plain_result("暂时读不到用量统计。")
            return
        total = report["totals"]
        rate = total["cache_hit_ratio"]
        cost = total["estimate_cny"]
        price = f"约{cost['low']:.2f}～{cost['high']:.2f}元" if cost else "费用统计不完整"
        yield event.plain_result(f"近24小时 {total['calls']} 次，{total['total_tokens']:,} tokens。\n"
                                 + (f"输入缓存命中 {rate:.1%}；" if rate is not None else "") + price
                                 + "。仅统计已记录调用，实际扣费以账单为准。")

    async def _monitor(self):
        await asyncio.sleep(45)
        while True:
            try:
                report = await asyncio.to_thread(self.report)
                self.directory.mkdir(parents=True, exist_ok=True)
                (self.directory / "cost-latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("成本统计未更新：" + type(exc).__name__)
            await asyncio.sleep(max(300, int(self.config.get("monitor_interval_seconds", 3600))))

    async def terminate(self):
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
