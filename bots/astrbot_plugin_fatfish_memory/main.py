"""AstrBot plugin: one shared memory for the QQ and Bilibili bots."""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.star.filter.command import GreedyStr

from fatfish_core import MemoryStore, build_context, resolve_shared_db

PLUGIN_NAME = "astrbot_plugin_fatfish_memory"
PLATFORM_ALIASES = {
    "aiocqhttp": "qq",
    "qq_official": "qq",
    "qq_official_webhook": "qq",
    "bilibili": "bilibili",
    "bili": "bilibili",
}


def _platform(event: AstrMessageEvent) -> str:
    raw = str(event.get_platform_name() or "").lower()
    for key, value in PLATFORM_ALIASES.items():
        if raw.startswith(key):
            return value
    return raw or "unknown"


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        configured = str(self.config.get("db_path") or "").strip()
        path = resolve_shared_db(StarTools.get_data_dir(PLUGIN_NAME).parent.parent, configured)
        self.store = MemoryStore(path)
        self._last_pruned_day: date | None = None
        self._sync_configured_owners()
        logger.info(f"fatfish shared memory ready: {path}")

    def _sync_configured_owners(self) -> None:
        raw = str(self.config.get("owner_ids") or "")
        for item in re.split(r"[,，\s]+", raw):
            if ":" not in item:
                continue
            platform, uid = item.split(":", 1)
            platform, uid = platform.strip().lower(), uid.strip()
            if platform and uid:
                try:
                    self.store.add_owner(platform, uid, "config")
                except ValueError:
                    continue

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        return self.store.is_owner(_platform(event), str(event.get_sender_id() or ""))

    def _can_access_private(self, event: AstrMessageEvent) -> bool:
        return self._is_owner(event) and event.is_private_chat()

    def _scopes(self, event: AstrMessageEvent) -> tuple[str, ...]:
        return ("public", "private") if self._can_access_private(event) else ("public",)

    def _conversation(self, event: AstrMessageEvent) -> tuple[str, str]:
        return _platform(event), str(event.get_session_id() or "")

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not bool(self.config.get("inject_context", True)):
            return
        marker = "\n\n[共享记忆参考]\n"
        if marker in (req.system_prompt or ""):
            return
        try:
            context = build_context(
                self.store,
                str(req.prompt or event.message_str or ""),
                scopes=self._scopes(event),
                conversation=self._conversation(event),
                max_chars=int(self.config.get("max_context_chars", 1800)),
            )
        except (sqlite3.Error, OSError, ValueError) as exc:
            logger.warning(f"检索共享记忆失败，本次请求未注入记忆：{exc}")
            return
        if context:
            req.system_prompt = (req.system_prompt or "") + marker + context

    def _prune_if_due(self) -> None:
        today = date.today()
        if self._last_pruned_day == today:
            return
        try:
            days = int(self.config.get("retention_days", 90))
            if days <= 0:
                return
            self.store.prune(days)
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            logger.warning(f"清理过期记忆失败，后续消息会重试：{exc}")
            return
        self._last_pruned_day = today

    async def _record(self, event: AstrMessageEvent) -> None:
        if not bool(self.config.get("record_all_messages", True)):
            return
        text = str(event.message_str or "").strip()
        if not text:
            return
        scope = "private" if event.is_private_chat() else "public"
        try:
            self.store.remember(
                text,
                platform=_platform(event),
                scope=scope,
                kind="message",
                session=event.get_session_id(),
                actor=str(event.get_sender_id() or ""),
                limit=int(self.config.get("max_content_chars", 500)),
            )
        except (sqlite3.Error, ValueError, OSError) as exc:
            logger.warning(f"记录消息失败：{exc}")
            return
        self._prune_if_due()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        await self._record(event)

    @filter.command("记忆")
    async def memory(self, event: AstrMessageEvent, action: str = "", text: GreedyStr = ""):
        command = (action or "").strip()
        body = str(text or "").strip()
        owner = self._is_owner(event)
        if command in ("", "帮助", "help"):
            yield event.plain_result(
                "记忆用法：\n"
                "/记忆 搜索 <关键词>\n"
                "/记忆 最近\n"
                "/记忆 状态\n"
                "/记忆 记住 <内容>    仅主人\n"
                "/记忆 公开 <内容>    仅主人\n"
                "/记忆 人设 [内容]    仅主人可改\n"
                "/记忆 导入 <总结>    仅主人\n"
                "/记忆 总结           仅主人\n"
                "/记忆 札记 [内容]    查看或写成长札记\n"
                "/记忆 提炼           从最近记录提炼札记，仅主人\n"
                "/记忆 绑定 <B站UID>  仅主人"
            )
            return
        if command == "搜索":
            if not body:
                yield event.plain_result("请给出关键词，例如 /记忆 搜索 直播")
                return
            rows = self.store.recall(body, scopes=self._scopes(event), limit=10, conversation=self._conversation(event))
            if not rows:
                yield event.plain_result("没有找到相关记忆。")
                return
            lines = [f"[{row['created_at'][:16]}] {row['platform']} {row['content'][:120]}" for row in rows]
            yield event.plain_result("找到的记忆：\n" + "\n".join(lines))
            return
        if command == "最近":
            rows = self.store.recent(scopes=self._scopes(event), limit=10, conversation=self._conversation(event))
            if not rows:
                yield event.plain_result("还没有记忆。")
                return
            lines = [f"[{row['created_at'][:16]}] {row['platform']}/{row['scope']} {row['content'][:100]}" for row in rows]
            yield event.plain_result("最近记忆：\n" + "\n".join(lines))
            return
        if command == "状态":
            stats = self.store.stats()
            yield event.plain_result(
                f"共享记忆：{stats['events']} 条事件（私人 {stats['private']} / 公开 {stats['public']}）\n"
                f"人设 {stats['persona_chars']} 字，主人 {stats['owners']} 个\n"
                f"最近写入：{stats['last_event'] or '无'}\n"
                f"数据库：{stats['path']}"
            )
            return
        if command in ("记住", "公开"):
            if not owner:
                yield event.plain_result("只有主人可以写入记忆。")
                return
            if not body:
                yield event.plain_result("请给出要记住的内容。")
                return
            scope = "private" if command == "记住" else "public"
            self.store.remember(
                body,
                platform=_platform(event),
                scope=scope,
                kind="note",
                session=event.get_session_id(),
                actor=str(event.get_sender_id() or ""),
                limit=int(self.config.get("max_content_chars", 500)),
            )
            yield event.plain_result("已写入" + ("私人" if scope == "private" else "公开") + "记忆。")
            return
        if command == "人设":
            if not body:
                persona = self.store.get_persona()
                yield event.plain_result(persona or "还没有设置人设。")
                return
            if not owner:
                yield event.plain_result("只有主人可以修改人设。")
                return
            self.store.set_persona(body)
            yield event.plain_result(f"人设已更新，共 {len(body)} 字。")
            return
        if command == "导入":
            if not owner:
                yield event.plain_result("只有主人可以导入每日总结。")
                return
            if not body:
                yield event.plain_result("请把总结内容跟在命令后面。")
                return
            self.store.add_summary(body, period=event.message_str[:10], source=f"{_platform(event)}:{event.get_sender_id()}")
            self.store.remember(body, platform=_platform(event), scope="private", kind="summary", session=event.get_session_id(), actor=str(event.get_sender_id()), limit=4000)
            yield event.plain_result("每日总结已导入私人记忆。")
            return
        if command == "总结":
            if not self._can_access_private(event):
                yield event.plain_result("私人总结只能在主人的私聊中查看。")
                return
            rows = self.store.summaries(limit=5)
            if not rows:
                yield event.plain_result("还没有导入过总结。")
                return
            lines = [f"[{row['created_at'][:16]}] {row['content'][:200]}" for row in rows]
            yield event.plain_result("最近的总结：\n" + "\n".join(lines))
            return
        if command == "札记":
            if not body:
                if not self._can_access_private(event):
                    yield event.plain_result("成长札记只能在主人的私聊中查看。")
                    return
                rows = self.store.journals(limit=8)
                if not rows:
                    yield event.plain_result("还没有成长札记。主人可以写一条，或用 /记忆 提炼。")
                    return
                lines = [f"[{row['day']}] {row['content']}" for row in rows]
                yield event.plain_result("成长札记：\n" + "\n".join(lines))
                return
            if not owner:
                yield event.plain_result("只有主人可以写札记。")
                return
            self.store.add_journal(body, source=f"{_platform(event)}:{event.get_sender_id()}")
            yield event.plain_result("札记已保存。")
            return
        if command == "提炼":
            if not self._can_access_private(event):
                yield event.plain_result("请在主人的私聊中提炼札记。")
                return
            rows = self.store.recent(scopes=("private", "public"), limit=40, conversation=self._conversation(event))
            if not rows:
                yield event.plain_result("最近没有可提炼的记忆。")
                return
            material = "\n".join(f"- [{row['created_at'][:16]}] {row['content'][:160]}" for row in reversed(rows))
            prompt = (
                "下面是大肥鱼最近和主人、观众的相处记录。请从中提炼 1 到 3 条「认识」或「下次怎么回应」，"
                "每条一行，不要编号，不要复述原文，不要编造没有出现的事实。"
                "如果没有值得沉淀的内容，只输出一行：无。\n\n" + material
            )
            try:
                provider_id = await self.context.get_current_chat_provider_id(umo=event.unified_msg_origin)
                response = await self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt)
                text = str(getattr(response, "completion_text", "") or "").strip()
            except Exception as exc:  # provider errors must not crash the command
                yield event.plain_result(f"提炼失败：{exc}")
                return
            lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
            lines = [line for line in lines if line and line != "无"][:3]
            if not lines:
                yield event.plain_result("这轮没有值得沉淀的内容。")
                return
            for line in lines:
                self.store.add_journal(line, source="auto")
            yield event.plain_result("已写入札记：\n" + "\n".join(lines))
            return
        if command == "绑定":
            if not owner:
                yield event.plain_result("只有主人可以绑定 B 站账号。")
                return
            uid = body.strip()
            if not uid.isdigit():
                yield event.plain_result("请给出数字 B 站 UID，例如 /记忆 绑定 123456")
                return
            self.store.add_owner("bilibili", uid, "bound in chat")
            yield event.plain_result(f"已把 B 站 UID {uid} 绑定为主人。")
            return
        yield event.plain_result("未知操作，发送 /记忆 帮助 查看用法。")

    @filter.llm_tool(name="memory_recall")
    async def memory_recall(self, event: AstrMessageEvent, query: str = "", scope: str = "auto"):
        """检索大肥鱼的共享记忆。私人记忆只能在主人的私聊中读取。

        Args:
            query(string): 要检索的关键词或问题片段，留空表示最近记忆
            scope(string): auto、private 或 public；默认 auto
        """
        scopes = self._scopes(event)
        if scope == "public":
            scopes = ("public",)
        elif scope == "private":
            if not self._can_access_private(event):
                yield event.plain_result("私人记忆只能在主人的私聊中读取。")
                return
            scopes = ("private",)
        rows = self.store.recall(query, scopes=scopes, limit=8, conversation=self._conversation(event)) if query else self.store.recent(scopes=scopes, limit=8, conversation=self._conversation(event))
        if not rows:
            yield event.plain_result("没有找到相关记忆。")
            return
        lines = [f"- [{row['created_at'][:16]}] {row['platform']}/{row['scope']}：{row['content'][:160]}" for row in rows]
        yield event.plain_result("共享记忆检索结果：\n" + "\n".join(lines))

    @filter.llm_tool(name="memory_remember")
    async def memory_remember(self, event: AstrMessageEvent, content: str, scope: str = "private"):
        """把值得长期记住的事写入共享记忆，只有主人可以调用。

        Args:
            content(string): 要记住的完整内容
            scope(string): private 或 public，默认 private
        """
        if not self._is_owner(event):
            yield event.plain_result("只有主人可以写入共享记忆。")
            return
        if scope not in ("private", "public"):
            scope = "private"
        self.store.remember(
            content,
            platform=_platform(event),
            scope=scope,
            kind="note",
            session=event.get_session_id(),
            actor=str(event.get_sender_id() or ""),
            limit=int(self.config.get("max_content_chars", 500)),
        )
        yield event.plain_result("已写入共享记忆。")

    async def terminate(self) -> None:
        logger.info("fatfish shared memory stopped")
