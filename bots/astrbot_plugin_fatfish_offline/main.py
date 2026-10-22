"""AstrBot plugin: stop cloud LLM calls during configured peak-price windows and
keep a small local voice in chat. The persona itself stays untouched."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain, Reply
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.filter.command import GreedyStr

from .engagement import GroupConfig, GroupEngagement, GroupMessage
from .logic import Decision, Scheduler, format_resume
from .state import StateStore
from .templates import OfflineConfig, OfflineReplyEngine

PLUGIN_NAME = "astrbot_plugin_fatfish_offline"
POKE_REPLIES = ["嘿嘿！别戳啦！", "在的在的！", "呜哇！痒！", "戳一下就想跑？"]
EMPTY_MENTION_REPLIES = ["在！", "嗯？", "诶？", "来啦来啦！", "叫我？", "在这在这！"]
LOCAL_COMMANDS = ("/记忆", "/bili", "/设定", "/重置", "/reset", "/help", "/帮助", "/表情", "/sid", "/离线")
HELP_TEXT = """苹果乐命令：
/记忆 状态 | 搜索 <词> | 最近 | 记住 <内容> | 公开 <内容> | 人设 | 导入 <总结> | 札记 | 提炼 | 绑定 <B站UID>
/bili 状态 | 收件箱 | 看 <BV号> | 搜 <词> | 回复 <BV号> <评论ID> <内容> | 私信 <UID> <内容> | 处理
/设定 <关键词>   查角色设定，/设定 目录 看章节
/离线 状态 | 开 | 关 | 自动
/reset           清空当前会话
/reset 群:<群号>  清空指定群聊上下文
/reset qq:<QQ号>  清空指定私聊上下文
/help 或 /帮助    本菜单"""


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
        self.engagement = GroupEngagement(
            GroupConfig(
                random_probability=float(self.config.get("ambient_chance") or 0.025),
                random_cooldown=float(self.config.get("ambient_cooldown") or 300),
                random_hourly_limit=int(self.config.get("ambient_hourly_limit") or 3),
            )
        )
        self._pending_trigger: dict[str, tuple[str | None, str]] = {}
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

    async def _addressed(self, event: AstrMessageEvent) -> bool:
        if event.is_private_chat():
            return True
        self_id = str(event.get_self_id() or "")
        message = getattr(getattr(event, "message_obj", None), "message", []) or []
        for component in message:
            if isinstance(component, At) and str(getattr(component, "qq", "")) == self_id:
                return True
        for component in message:
            if not isinstance(component, Reply):
                continue
            try:
                data = await event.bot.call_action("get_msg", message_id=component.id)
            except Exception:
                continue
            sender = (data or {}).get("sender") or {}
            if str(sender.get("user_id") or "") == self_id:
                return True
        return False

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        if event.is_admin():
            return True
        owner_qq = str(self.config.get("owner_qq") or "").strip()
        return bool(owner_qq) and str(event.get_sender_id() or "") == owner_qq

    def _is_bot(self, event: AstrMessageEvent) -> bool:
        raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
        if isinstance(raw, dict):
            sender = raw.get("sender") or {}
            if sender.get("is_robot") or sender.get("isRobot"):
                return True
        uid = str(event.get_sender_id() or "")
        ignored = {item.strip() for item in str(self.config.get("ignore_uids") or "").split(",") if item.strip()}
        return bool(uid) and uid in ignored

    def _has_at_bot(self, event: AstrMessageEvent) -> bool:
        self_id = str(event.get_self_id() or "")
        for component in getattr(event.message_obj, "message", None) or []:
            if isinstance(component, At) and str(getattr(component, "qq", "")) == self_id:
                return True
        return False

    def _poke_target(self, event: AstrMessageEvent) -> str | None:
        raw = getattr(event.message_obj, "raw_message", None)
        if isinstance(raw, dict) and raw.get("post_type") == "notice" and raw.get("sub_type") == "poke":
            target = raw.get("target_id")
            if target is not None:
                return str(target).strip()
        for component in getattr(event.message_obj, "message", None) or []:
            if type(component).__name__ != "Poke":
                continue
            getter = getattr(component, "target_id", None)
            target = getter() if callable(getter) else getattr(component, "id", "")
            return str(target or "").strip()
        return "" if isinstance(raw, dict) and raw.get("post_type") == "notice" and raw.get("sub_type") == "poke" else None

    def _is_empty_mention(self, event: AstrMessageEvent) -> bool:
        if not self._has_at_bot(event):
            return False
        self_id = str(event.get_self_id() or "")
        return all(
            (isinstance(component, At) and str(component.qq) == self_id)
            or (isinstance(component, Plain) and not component.text.strip())
            for component in (getattr(event.message_obj, "message", None) or [])
        )

    @filter.after_message_sent()
    async def remember_bot_turn(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            return
        result = event.get_result()
        text = ""
        if result is not None:
            try:
                text = str(result.get_plain_text() or "").strip()
            except Exception:
                text = ""
        if not text:
            return
        target, kind = self._pending_trigger.pop(group_id, (None, "reply"))
        self.engagement.on_bot_sent(
            group_id=group_id,
            text=text,
            target_user=target,
            trigger_kind=kind,
        )

    async def _send_help(self, event: AstrMessageEvent) -> None:
        await event.send(MessageChain([Plain(HELP_TEXT)]))

    async def _reset_target(self, event: AstrMessageEvent, argument: str) -> None:
        if not self._is_owner(event):
            await event.send(MessageChain([Plain("只有主人可以清空指定会话。")]))
            return
        target = argument.strip().replace("：", ":")
        platform = str(event.get_platform_name() or "napcat")
        if target.startswith(("群:", "group:")):
            target_id = target.split(":", 1)[1].strip()
            umo = f"{platform}:GroupMessage:{target_id}"
            label = f"群 {target_id}"
        elif target.lower().startswith(("qq:", "user:", "私聊:")):
            target_id = target.split(":", 1)[1].strip()
            umo = f"{platform}:FriendMessage:{target_id}"
            label = f"私聊 {target_id}"
        else:
            await event.send(MessageChain([Plain("格式：/reset 群:123456 或 /reset qq:123456")]))
            return
        if not target_id:
            await event.send(MessageChain([Plain("目标不能为空。")]))
            return
        try:
            await self.context.conversation_manager.delete_conversations_by_user_id(umo)
        except Exception as exc:
            logger.warning(f"清空会话失败：{exc}")
            await event.send(MessageChain([Plain(f"清空失败：{exc}")]))
            return
        await event.send(MessageChain([Plain(f"已清空{label}的上下文。")]))
        logger.info(f"清空会话 {umo}")

    # ---------- message guard ----------

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def guard(self, event: AstrMessageEvent):
        if not self.enabled:
            return
        if self._is_bot(event):
            # Never answer another bot's @ or reply, and never spend a model call on it.
            event.stop_event()
            return
        poke_target = self._poke_target(event)
        if poke_target is not None and (not event.get_self_id() or poke_target != str(event.get_self_id())):
            # A notice about two other users is not a message addressed to this bot.
            event.stop_event()
            return
        now = datetime.now(self.scheduler.tz)
        decision = self._decision()
        if self._is_empty_mention(event):
            self.state.publish_offline(decision.offline, reason=decision.reason, resume_at=decision.resume_at)
            await event.send(MessageChain([Plain(random.choice(EMPTY_MENTION_REPLIES))]))
            event.stop_event()
            return
        if not decision.offline:
            hour_key = now.strftime("%Y-%m-%dT%H")
            count = self.state.bump_usage(hour_key)
            if self.hourly_model_limit > 0 and count > self.hourly_model_limit:
                decision = Decision(True, "usage_limit", self._next_hour(now), None)
            else:
                self.state.publish_offline(False)
                group_key = str(event.get_group_id() or "")
                if poke_target is not None:
                    if group_key:
                        self._pending_trigger[group_key] = (str(event.get_sender_id() or ""), "poke")
                    event.message_str = "（戳了戳你）"
                    event.message_obj.message_str = event.message_str
                    event.is_at_or_wake_command = True
                    return
                if group_key:
                    incoming = str(
                        getattr(getattr(event, "message_obj", None), "message_str", "")
                        or event.message_str
                        or ""
                    ).strip()
                    trigger = self.engagement.handle_message(
                        GroupMessage(
                            group_id=group_key,
                            user_id=str(event.get_sender_id() or ""),
                            text=incoming,
                            nickname=str(event.get_sender_name() or ""),
                            at_bot=self._has_at_bot(event),
                            has_media=any(
                                type(component).__name__ in ("Image", "Record", "Video", "File")
                                for component in (getattr(event.message_obj, "message", None) or [])
                            ),
                            timestamp=now.timestamp(),
                        ),
                        wake_matched=bool(event.is_at_or_wake_command) and not self._has_at_bot(event),
                    )
                    if trigger:
                        self._pending_trigger[group_key] = (trigger.target_user, trigger.kind)
                        if trigger.kind in ("random", "continuation"):
                            event.is_at_or_wake_command = True
                            logger.info(f"{trigger.kind} 触发 group={group_key}")
                return
        self.state.publish_offline(decision.offline, reason=decision.reason, resume_at=decision.resume_at)

        if poke_target is not None:
            await event.send(MessageChain([Plain(random.choice(POKE_REPLIES))]))
            event.stop_event()
            return

        text = str(
            getattr(getattr(event, "message_obj", None), "message_str", "")
            or event.message_str
            or ""
        ).strip()

        if text.startswith("/"):
            if text.startswith(("/help", "/帮助")):
                await self._send_help(event)
                event.stop_event()
                return
            parts = text.split(maxsplit=1)
            if parts[0] in ("/reset", "/重置") and len(parts) > 1:
                await self._reset_target(event, parts[1])
                event.stop_event()
                return
            # Let AstrBot's own command handlers run, including /离线 itself.
            if any(text.startswith(command) for command in LOCAL_COMMANDS):
                return
            event.stop_event()
            return

        group = str(event.get_group_id() or f"private:{event.get_sender_id()}")
        user = str(event.get_sender_id() or "unknown")
        addressed = await self._addressed(event)
        if not addressed:
            # Silence in groups unless directly @-ed or replied to.
            event.stop_event()
            return
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
            self.engagement.on_bot_sent(
                group_id=group,
                text=reply,
                target_user=user,
                trigger_kind="mention" if addressed else "reply",
            )
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
