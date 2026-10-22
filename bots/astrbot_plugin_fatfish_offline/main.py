"""AstrBot plugin: stop cloud LLM calls during configured peak-price windows and
keep a small local voice in chat. The persona itself stays untouched."""

from __future__ import annotations

import random
from datetime import datetime

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.filter.command import GreedyStr

from .logic import Scheduler, ShortContext, Throttle, detect_intent, format_resume
from .state import StateStore
from .templates import pick

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
        )
        self.reason = str(self.config.get("reason") or "high_cost")
        self.throttle = Throttle(
            group_cooldown=self.config.get("group_cooldown", 30),
            user_cooldown=self.config.get("user_cooldown", 300),
            max_per_hour=self.config.get("max_per_hour", 8),
        )
        self.contexts = ShortContext(ttl_seconds=self.config.get("context_ttl", 600))
        self.state = StateStore(StarTools.get_data_dir(PLUGIN_NAME))
        self.rng = random.Random()
        logger.info(
            f"fatfish offline ready: enabled={self.enabled} windows={[f'{w.start}-{w.end}' for w in self.scheduler.windows]}"
        )
        try:
            decision = self._decision()
            self.state.publish_offline(decision.offline, reason=decision.reason, resume_at=decision.resume_at)
        except Exception as exc:  # never block startup
            logger.warning(f"发布初始离线状态失败：{exc}")

    # ---------- decision ----------

    def _decision(self):
        manual = self.state.manual
        now = datetime.now(self.scheduler.tz)
        if manual == "on":
            from .logic import Decision

            resume = self.scheduler.next_window(now)
            return Decision(True, "manual", resume, None)
        if manual == "off":
            from .logic import Decision

            return Decision(False)
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
        return "苹果乐" in text or "苹果" in text

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
        decision = self._decision()
        self.state.publish_offline(decision.offline, reason=decision.reason, resume_at=decision.resume_at)
        if not decision.offline:
            return

        text = str(event.message_str or "").strip()
        if text.startswith("/") and not text.startswith("/离线"):
            if any(text.startswith(command) for command in LOCAL_COMMANDS):
                return
            event.stop_event()
            return

        group = str(event.get_group_id() or f"private:{event.get_sender_id()}")
        user = str(event.get_sender_id() or "unknown")
        addressed = self._addressed(event)
        now = datetime.now(self.scheduler.tz)
        follow_up = self.contexts.is_follow_up(group, user, now)
        intent = detect_intent(text, addressed=addressed, follow_up=follow_up)
        if intent == "none" and not addressed and not follow_up:
            event.stop_event()
            return

        resume_text = format_resume(decision.resume_at, now) if decision.resume_at else "晚点"
        day = now.date().isoformat()
        is_question = intent in ("when_resume", "why_silent")
        use_notice = is_question and not self.state.notified_today(group, day)
        if use_notice:
            intent = "first_notice"

        if not self.throttle.allow(group, user, now):
            event.stop_event()
            return

        line = pick(
            decision.reason or self.reason,
            intent,
            name=str(event.get_sender_name() or "老板"),
            resume=resume_text,
            recent=self.state.recent_lines(group),
            rng=self.rng,
        )
        try:
            await event.send(MessageChain([Plain(line)]))
        except Exception as exc:  # sending must not crash the pipeline
            logger.warning(f"离线回复发送失败：{exc}")
            event.stop_event()
            return
        if use_notice:
            self.state.mark_notified(group, day)
        self.state.add_recent(group, line)
        self.throttle.mark(group, user, now)
        self.contexts.set(group, user=user, intent=intent, reply=line, now=now)
        logger.info(f"离线回复 group={group} user={user} intent={intent} reason={decision.reason}")
        event.stop_event()

    # ---------- commands ----------

    @filter.command("离线")
    async def offline(self, event: AstrMessageEvent, action: str = "", text: GreedyStr = GreedyStr("")):
        command = (action or "").strip()
        if command in ("", "状态", "status"):
            decision = self._decision()
            next_window = self.scheduler.next_window()
            lines = [
                f"模块：{'开启' if self.enabled else '关闭'}",
                f"当前：{'离线（' + str(decision.reason) + '）' if decision.offline else '正常 AI'}",
                f"恢复：{format_resume(decision.resume_at) if decision.resume_at else '不在离线时段'}",
                f"下一时段：{next_window.strftime('%m-%d %H:%M') if next_window else '无'}",
                f"手动覆盖：{self.state.manual or '无'}",
                "时段：" + "、".join(f"{w.start}-{w.end}" for w in self.scheduler.windows),
            ]
            yield event.plain_result("\n".join(lines))
            return
        if command in ("开", "开启", "on"):
            if not self._is_owner(event):
                yield event.plain_result("只有主人可以切换离线模式。")
                return
            self.state.set_manual("on")
            yield event.plain_result("已强制进入离线模式。发送 /离线 关 恢复。")
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
