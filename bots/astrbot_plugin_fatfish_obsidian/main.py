"""Private, owner-only Obsidian knowledge backed by AstrBot's native manager."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.star.filter.command import GreedyStr

from fatfish_core import MemoryStore, RuntimeStore, resolve_shared_db
from fatfish_core.growth import record_capability
from fatfish_core.knowledge_graph import KnowledgeGraph
from fatfish_core.graph_build import file_documents, build_graph
from fatfish_core.usage import record_usage
from .sync import sync_vault

PLUGIN_NAME = "astrbot_plugin_fatfish_obsidian"
BEIJING = timezone(timedelta(hours=8))


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        db_path = resolve_shared_db(StarTools.get_data_dir(PLUGIN_NAME).parent.parent)
        self.store = MemoryStore(db_path)
        self.runtime = RuntimeStore(db_path)
        self.graph = KnowledgeGraph(db_path)
        self._lock = asyncio.Lock()
        self._clock = datetime.strptime(str(self.config.get("sync_time") or "03:00"), "%H:%M")
        self._task = asyncio.create_task(self._loop()) if self.config.get("enabled", True) else None

    def _owner(self, event):
        if not event.is_private_chat():
            return False
        raw = str(event.get_platform_name() or "")
        platform = "qq" if raw.startswith(("aiocqhttp", "qq_official")) else raw
        uid = str(event.get_sender_id() or "")
        owners = str(self.config.get("owner_ids") or "").replace("，", ",").replace("\n", ",").split(",")
        return f"{platform}:{uid}" in {item.strip() for item in owners} or self.store.is_owner(platform, uid)

    @property
    def kb_name(self):
        return str(self.config.get("kb_name") or "FatFish-Obsidian-Private")

    async def _helper(self):
        manager = self.context.kb_manager
        helper = await manager.get_kb_by_name(self.kb_name)
        if helper is None:
            helper = await manager.create_kb(
                kb_name=self.kb_name, description="FatFishLife 独立私人 Obsidian 知识库，仅老大私聊检索。",
                embedding_provider_id=str(self.config.get("embedding_provider_id") or "siliconflow/bge-m3"),
            )
        if getattr(helper, "init_error", None):
            raise RuntimeError("知识库尚未初始化")
        return helper

    async def synchronize(self):
        async with self._lock:
            configured = str(self.config.get("vault_path") or "").strip()
            if not configured:
                record_capability(self.store, "obsidian", "blocked", stage="sync", error_code="not_configured")
                raise ValueError("请先设置 vault_path")
            try:
                helper = await self._helper()
                result = await sync_vault(helper, self.runtime, Path(configured).expanduser(),
                                          limit=max(1, min(200, int(self.config.get("max_files_per_sync", 25)))))
                async def generate(system, text):
                    provider = self.context.get_provider_by_id(str(self.config.get("graph_provider_id") or "fatfish_context_local"))
                    if provider is None:
                        raise RuntimeError("Configured local graph extraction provider is unavailable")
                    response = await asyncio.wait_for(provider.text_chat(system_prompt=system, prompt=text), timeout=90)
                    await record_usage(self.context, provider, response, umo="fatfish:Internal:private_graph", agent_type="fatfish_graph")
                    return response.completion_text
                result["graph"] = await build_graph(self.graph, list(file_documents(Path(configured).expanduser(), "private_obsidian")), generate,
                                                   complete_collections=["private_obsidian"])
            except asyncio.CancelledError:
                raise
            except Exception:
                record_capability(self.store, "obsidian", "failed", stage="sync", error_code="service_error")
                raise
            record_capability(self.store, "obsidian", "failed" if result["failed"] or result.get("graph", {}).get("failed") else "success", stage="sync")
            self.runtime.set(PLUGIN_NAME, "last_result", result)
            return result

    async def _search(self, text):
        # Never register this KB globally or retrieve from other knowledge bases.
        result = await self.context.kb_manager.retrieve(query=text, kb_names=[self.kb_name], top_m_final=3)
        record_capability(self.store, "obsidian", "success", stage="search")
        graph = self.graph.context(text, collection="private_obsidian", max_chars=2200) if hasattr(self, "graph") else ""
        return (graph + ("\n【私人原文补充】\n" if graph else "") + str((result or {}).get("context_text") or "没有检索到相关笔记。"))[:6000]

    @filter.llm_tool(name="fatfish_private_knowledge")
    async def knowledge_tool(self, event: AstrMessageEvent, query: str):
        """在老大私聊中检索独立 Obsidian 笔记。

        Args:
            query(string): 要查找的主题或问题。
        """
        if not self._owner(event):
            return "知识库仅供老大私聊使用。"
        try:
            return await self._search(query)
        except Exception as exc:
            record_capability(self.store, "obsidian", "failed", stage="search", error_code="service_error")
            return f"知识库检索未完成：{type(exc).__name__}。"

    @filter.command("kb", alias={"知识库"})
    async def knowledge(self, event: AstrMessageEvent, action: str = "", text: GreedyStr = GreedyStr):
        if not self._owner(event):
            yield event.plain_result("知识库仅供老大私聊使用。")
            return
        text = "" if text is GreedyStr else str(text or "").strip()
        action = str(action).strip()
        action = {"help": "帮助", "status": "状态", "sync": "同步", "search": "搜索"}.get(action.lower(), action)
        if action == "帮助":
            yield event.plain_result("/kb status - Show private knowledge synchronization status\n"
                                     "/kb sync - Incrementally synchronize the configured private vault\n"
                                     "/kb search <question> - Search private notes\n/kb help")
            return
        if action == "同步":
            try:
                result = await self.synchronize()
                yield event.plain_result("独立知识库同步结果：" + json.dumps(result, ensure_ascii=False))
            except Exception as exc:
                yield event.plain_result(f"知识库同步未完成：{type(exc).__name__}；请检查 vault 路径、Embedding 配置和连接。")
        elif action == "搜索" and str(text).strip():
            yield event.plain_result(await self.knowledge_tool(event, str(text).strip()))
        elif action == "搜索":
            yield event.plain_result("Usage: /kb search <question>.")
        else:
            result = self.runtime.get(PLUGIN_NAME, "last_result", {})
            yield event.plain_result("独立私人知识库；每天北京时间 " + self._clock.strftime("%H:%M") + " 增量同步。\n"
                                     + "上次同步：" + json.dumps(result, ensure_ascii=False)
                                     + "\n/kb sync | search <question> | status | help")

    async def _loop(self):
        await asyncio.sleep(30)
        while True:
            now = datetime.now(BEIJING)
            scheduled = now.replace(hour=self._clock.hour, minute=self._clock.minute, second=0, microsecond=0)
            if now >= scheduled:
                day = now.date().isoformat()
                if self.runtime.get(PLUGIN_NAME, "attempted_day") != day:
                    self.runtime.set(PLUGIN_NAME, "attempted_day", day)
                    try:
                        await self.synchronize()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(f"Obsidian 增量同步未完成：{type(exc).__name__}；老大可用私聊同步命令重试")
                scheduled += timedelta(days=1)
            await asyncio.sleep(max(1, (scheduled - datetime.now(BEIJING)).total_seconds()))

    async def terminate(self):
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
