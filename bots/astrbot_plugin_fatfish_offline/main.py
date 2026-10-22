"""AstrBot plugin: stop cloud LLM calls during configured peak-price windows and
keep a small local voice in chat. The persona itself stays untouched."""

from __future__ import annotations

from datetime import datetime, timedelta

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.filter.command import GreedyStr

from .logic import Decision, Scheduler, format_resume
from .state import StateStore
from .templates import OfflineConfig, OfflineReplyEngine

PLUGIN_NAME = "astrbot_plugin_fatfish_offline"
LOCAL_COMMANDS = ("/记忆", "/bili", "/设定", "/重置", "/reset", "/help", "/sid", "/离线")


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        windows = self.config.get("windows") or ["08:00-12:00", "14:00-18:00"]
        self.scheduler = Scheduler(
            windows,
            weekdays=self.config.get("weekdays") or [0, 1, 2, 3, 4],
            holidays=self.config.get("holidays") or [],
            workdays=self.config.get("workdays") or [],
            holiday_source=str(self.config.get("holiday_source") or "auto"),
        )
        self.reason = str(self.config.get("reason") or "high_cost")
        self.hourly_model_limit = int(self.config.get("hourly_model_limit", 350) or 0)
        self.state = StateStore(StarTools.get_data_dir(PLUGIN_NAME))
        self.engine = OfflineReplyEngine(
            OfflineConfig(
                timezone=str(self.config.get("timezone") or "Asia/Shanghai"),
                notice_once_per_day=bool(self.config.get("notify_once_per_day", True)),
                group_cooldown=float(self.config.get("group_cooldown", 2)),
                user_cooldown=float(self.config.get("user_cooldown", 2)),
                context_ttl=float(self.config.get("context_ttl", 600)),
            ),
            state_file=StarTools.get_data_dir(PLUGIN_NAME) / "engine.json",
        )
        logger.info(
            f"fatfish offline ready: enabled={self.enabled} "
            f"windows={[f'{w.start}-{w.end}' for w in self.scheduler.windows]} "
            f"hourly_model_limit={self.hourly_model_limit}"
        )
        try:
            decision = self._decision()
            self.state.publish_offline(decision.offline, reason=decision.reason, resume_at=decision.resume_at)
        except Exception as exc:  # never block startup
            logger.warning(f"发布初始离线状态失败：{exc}")

    # ---------- decision ----------

    @staticmethod
    def _next_hour(now: datetime) -> datetime:
        return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    def _decision(self) -> Decision:
        now = datetime.now(self.scheduler.tz)
        manual = self.state.manual
        if manual == "on":
            return Decision(True, "manual", self.scheduler.next_resume(now), None)
        if manual == "off":
            return Decision(False)
        if self.hourly_model_limit > 0:
            hour_key = now.strftime("%Y-%m-%dT%H")
            if self.state.usage_count(hour_key) >= self.hourly_model_limit:
                return Decision(True, "usage_limit", self._next_hour(now), None)
        decision = self.scheduler.check(now)
        if decision.offline and decision.reason is None:
            decision.reason = self.reason
        return decision

    def _addressed(self, event: AstrMessageEvent) -> bool:
        if event.is_private_chat():
            return True
        self_id = str(event.get_self_id() or "")
        for component in getattr(getattr(event, "message_obj", None), "message", []) or []:
            if isinstance(component, At) and str(getattr(component, "qq", "")) == self_id:
                return True
        text = str(event.message_str or "")
        return "苹果乐" in text or "蕾缪乐" in text or "能天使" in text

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        if event.is_admin():
            return True
        owner_qq = str(self.config.get("owner_qq") or "").strip()
        return bool(owner_qq) and str(event.get_sender_id() or "") == owner_qq

    # ---------- message guard ----------

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def guard(self, event: AstrMessageEvent):
        if not self.enabled:
            return
        now = datetime.now(self.scheduler.tz)
        decision = self._decision()
        if not decision.offline:
            hour_key = now.strftime("%Y-%m-%dT%H")
            count = self.state.bump_usage(hour_key)
            if self.hourly_model_limit > 0 and count > self.hourly_model_limit:
                decision = Decision(True, "usage_limit", self._next_hour(now), None)
            else:
                self.state.publish_offline(False)
                return
        self.state.publish_offline(decision.offline, reason=decision.reason, resume_at=decision.resume_at)

        text = str(event.message_str or "").strip()
        if text.startswith("/") and not text.startswith("/离线"):
            if any(text.startswith(command) for command in LOCAL_COMMANDS):
                return
            event.stop_event()
            return

        group = str(event.get_group_id() or f"private:{event.get_sender_id()}")
        user = str(event.get_sender_id() or "unknown")
        addressed = self._addressed(event)
        resume_text = format_resume(decision.resume_at, now) if decision.resume_at else "晚点"
        reply = self.engine.handle(
            group_id=group,
            user_id=user,
            message=text,
            reason=decision.reason or self.reason,
            resume=resume_text,
            nickname=str(event.get_sender_name() or ""),
            at_bot=addressed,
        )
        if reply is None:
            event.stop_event()
            return
        try:
            await event.send(MessageChain([Plain(reply)]))
        except Exception as exc:  # sending must not crash the pipeline
            logger.warning(f"离线回复发送失败：{exc}")
            event.stop_event()
            return
        logger.info(f"离线回复 group={group} user={user} reason={decision.reason} chars={len(reply)}")
        event.stop_event()

    # ---------- commands ----------

    @filter.command("离线")
    async def offline(self, event: AstrMessageEvent, action: str = "", text: GreedyStr = GreedyStr("")):
        command = (action or "").strip()
        if command in ("帮助", "help"):
            yield event.plain_result("用法：\n/离线 状态\n/离线 开    强制离线\n/离线 关    强制在线\n/离线 自动  按时段判断")
            return
        if command in ("", "状态", "status"):
            decision = self._decision()
            now = datetime.now(self.scheduler.tz)
            hour_key = now.strftime("%Y-%m-%dT%H")
            count = self.state.usage_count(hour_key)
            next_window = self.scheduler.next_window(now)
            lines = [
                f"模块：{'开启' if self.enabled else '关闭'}",
                f"当前：{'高峰（离线）' if decision.offline else '空闲（正常 AI）'}",
                f"原因：{decision.reason or '不在高峰时段'}",
                f"今日工作日：{'是' if self.scheduler.is_workday(now) else '否'}（节假日源：{self.scheduler.holiday_source}）",
                f"恢复：{format_resume(decision.resume_at, now) if decision.resume_at else '不在离线时段'}",
                f"下一时段：{next_window.strftime('%m-%d %H:%M') if next_window else '无'}",
                f"本小时用量：{count}/{self.hourly_model_limit or '不限'}",
                f"手动覆盖：{self.state.manual or '无'}",
                "时段：" + "、".join(f"{w.start}-{w.end}" for w in self.scheduler.windows),
                "用法：/离线 开 | 关 | 自动",
            ]
            yield event.plain_result("\n".join(lines))
            return
        if command in ("开", "开启", "on"):
            if not self._is_owner(event):
                yield event.plain_result("只有主人可以切换离线模式。")
                return
            self.state.set_manual("on")
            yield event.plain_result("已强制进入离线模式。发送 /离线 关 强制在线，或 /离线 自动 按时段判断。")
            return
        if command in ("关", "关闭", "off"):
            if not self._is_owner(event):
                yield event.plain_result("只有主人可以切换离线模式。")
                return
            self.state.set_manual("off")
            yield event.plain_result("已强制退出离线模式。发送 /离线 自动 恢复按时段判断。")
            return
        if command in ("自动", "auto"):
            if not self._is_owner(event):
                yield event.plain_result("只有主人可以切换离线模式。")
                return
            self.state.set_manual(None)
            yield event.plain_result("已恢复按时段自动判断。")
            return
        yield event.plain_result("用法：/离线 状态 | 开 | 关 | 自动")

    async def terminate(self) -> None:
        logger.info("fatfish offline stopped")
