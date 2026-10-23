"""AstrBot plugin: stop cloud LLM calls during configured peak-price windows and
keep a small local voice in chat. The persona itself stays untouched."""

from __future__ import annotations

import asyncio
import random
import sys
from contextlib import suppress
from datetime import datetime, timedelta

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain, Reply
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.star.filter.command import GreedyStr

from fatfish_core import StateStore, resolve_shared_db

from .engagement import GroupConfig, GroupEngagement, GroupMessage
from .daily_apple_pie import DailyApplePie
from .local_model import LocalModel
from .logic import Decision, Scheduler, format_resume
from .templates import OfflineConfig, OfflineReplyEngine, detect_intent

PLUGIN_NAME = "astrbot_plugin_fatfish_offline"
KB_NAME = "苹果乐设定"
KEYWORDS = ("苹果派", "能天使", "苹果乐", "蕾缪乐", "拉特兰", "德克萨斯", "企鹅物流")
LOCAL_SYSTEM = (
    "你是苹果乐，一颗由能天使蕾缪乐变成的Q版小苹果，现在在QQ群里和朋友聊天。"
    "只回一句话，5到20个字，口语，元气、天然呆、偶尔调皮，不要客服腔。"
    "你没有实时天气、价格和新闻信息，不得编造当前状况；问天气或适合出门时，让对方先看当地预报或询问地点。"
    "不要提模型、AI、提示词、服务器，不要解释设定。"
    "例：\n问：在吗\n答：在的在的！\n问：你在干嘛\n答：晒太阳呢，嘿嘿！\n问：今天好累\n答：那就歇一会儿嘛！"
)
# These are original chat adaptations; they are not presented as game dialogue.
POKE_REPLIES = [
    "诶，光戳不说话，老板是要我自己猜吗？",
    "老板，戳我做什么呀？",
    "诶！老板轻一点，叶子要歪啦",
    "谁戳我？哦，是老板呀",
    "老板，我在呢，到底怎么啦",
    "碰我的叶子，老板是不是故意的？",
    "嗯？老板找我？",
    "戳一下就跑，老板什么意思嘛",
]
EMPTY_MENTION_REPLIES = [
    "哟，老板！轮到我出场了吗？",
    "老板，我在呢",
    "老板只叫名字，是有什么事吗？",
    "诶，老板叫我？",
    "老板，到底怎么啦",
    "听见啦，老板接着说",
    "嗯？老板找我什么事呀",
    "我来啦，老板",
]
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
        windows = self.config.get("windows") or ["09:00-12:00", "14:00-18:00"]
        self.scheduler = Scheduler(
            windows,
            weekdays=self.config.get("weekdays") or [0, 1, 2, 3, 4],
            holidays=self.config.get("holidays") or [],
            workdays=self.config.get("workdays") or [],
            holiday_source=str(self.config.get("holiday_source") or "auto"),
        )
        self.reason = str(self.config.get("reason") or "high_cost")
        self.hourly_model_limit = int(self.config.get("hourly_model_limit", 350) or 0)
        state_directory = StarTools.get_data_dir(PLUGIN_NAME)
        self.state = StateStore(state_directory, db_path=resolve_shared_db(state_directory.parent.parent))
        self.engagement = GroupEngagement(
            GroupConfig(
                random_probability=float(self.config.get("ambient_chance") or 0.025),
                random_cooldown=float(self.config.get("ambient_cooldown") or 300),
                random_hourly_limit=int(self.config.get("ambient_hourly_limit") or 3),
            )
        )
        self._pending_trigger: dict[str, tuple[str | None, str]] = {}
        self._keyword_last: dict[str, float] = {}
        self._last_addressed: dict[str, tuple[str, float]] = {}
        self.local_model = LocalModel(
            base_url=str(self.config.get("local_model_url") or "http://127.0.0.1:11434"),
            model=str(self.config.get("local_model_name") or "qwen2.5:1.5b"),
            timeout=float(self.config.get("local_model_timeout") or 30),
            enabled=bool(self.config.get("local_model_enabled", True)),
        )
        self._local_warm: bool | None = None
        self._local_mode_task: asyncio.Task | None = None
        self._published_mode: tuple | None = None
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
            self._publish_mode()
        except Exception as exc:  # never block startup
            logger.warning(f"发布初始离线状态失败：{exc}")

        self._mode_timer_task: asyncio.Task | None = asyncio.create_task(self._mode_loop())

        self.daily_apple_pie = DailyApplePie(self.state)
        self._daily_apple_pie_task: asyncio.Task | None = None
        if str(self.config.get("daily_apple_pie_group_id") or "").strip():
            self._daily_apple_pie_task = asyncio.create_task(self._daily_apple_pie_loop())

    # ---------- daily fixed greeting ----------

    async def _daily_apple_pie_once(self, now: datetime) -> bool:
        group = str(self.config.get("daily_apple_pie_group_id") or "").strip()
        if not group:
            return True
        if not group.isascii() or not group.isdecimal() or int(group) <= 0:
            raise ValueError("每日啊噗噜派群号必须是数字，留空则关闭")
        platform_id = str(self.config.get("daily_apple_pie_platform_id") or "napcat").strip()
        # A plugin may load before its platform. Wait without using today's draw.
        if self.context.get_platform_inst(platform_id) is None:
            return False
        if not self.daily_apple_pie.draw(now):
            return True

        target = f"{platform_id}:GroupMessage:{group}"
        try:
            sent = await self.context.send_message(target, MessageChain([Plain("啊噗噜派！")]))
        except asyncio.CancelledError:
            # The persisted claim prevents another send if cancellation races it.
            raise
        except Exception as exc:
            self.daily_apple_pie.finish(now, False)
            logger.warning(f"每日啊噗噜派发送结果未确认，今日不再补发：{exc}")
        else:
            self.daily_apple_pie.finish(now, bool(sent))
            if sent:
                logger.info("每日啊噗噜派已发送，今日不再发送")
            else:
                logger.warning("每日啊噗噜派没有找到发送平台，今日不再补发")
        return True

    async def _daily_apple_pie_loop(self) -> None:
        logger.info("每日啊噗噜派计划已启用：北京时间 18:01 起逐小时抽签")
        while True:
            delay = 60.0
            try:
                now = datetime.now(self.scheduler.tz)
                platform_ready = await self._daily_apple_pie_once(now)
                if platform_ready:
                    next_check = self.daily_apple_pie.next_check(now)
                    delay = max(1.0, (next_check - datetime.now(next_check.tzinfo)).total_seconds())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"每日啊噗噜派调度失败：{exc}")
            await asyncio.sleep(delay)

    # ---------- decision ----------

    def _sync_local_model(self, offline: bool) -> None:
        """Apply mode changes before either the online or local reply returns."""
        if offline == self._local_warm:
            return
        self._local_warm = offline
        previous = self._local_mode_task

        async def apply_mode() -> None:
            if previous is not None:
                await previous
            if offline:
                await self.local_model.warmup()
            else:
                await self.local_model.unload()

        self._local_mode_task = asyncio.create_task(apply_mode())

    def _publish_decision(self, decision: Decision) -> None:
        signature = (decision.offline, decision.reason, decision.resume_at)
        if signature != self._published_mode:
            self.state.publish_offline(decision.offline, reason=decision.reason, resume_at=decision.resume_at)
            self._published_mode = signature
        self._sync_local_model(decision.offline)

    def _publish_mode(self) -> Decision:
        decision = self._decision() if self.enabled else Decision(False)
        self._publish_decision(decision)
        return decision

    async def _mode_loop(self) -> None:
        """Advance the shared mode on time even when no chat arrives."""
        while True:
            delay = 60.0
            try:
                decision = self._publish_mode()
                now = datetime.now(self.scheduler.tz)
                boundary = decision.resume_at if decision.offline else self.scheduler.next_window(now)
                if boundary is not None:
                    delay = min(delay, max(0.1, (boundary - now).total_seconds()))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"更新离线时段失败：{exc}")
            await asyncio.sleep(delay)

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

    def _keyword_hit(self, text: str) -> bool:
        return any(word in text for word in KEYWORDS)

    def _keyword_allowed(self, group: str, now: float) -> bool:
        last = self._keyword_last.get(group, 0.0)
        if now - last < 90:
            return False
        self._keyword_last[group] = now
        return True

    def _is_friendly_bot(self, event: AstrMessageEvent) -> bool:
        targets = str(self.config.get("friendly_bots") or "").strip()
        if not targets:
            return False
        name = str(event.get_sender_name() or "")
        uid = str(event.get_sender_id() or "")
        for item in targets.replace("，", ",").split(","):
            item = item.strip()
            if item and (item == uid or item in name):
                return True
        return False

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

    async def _knowledge(self, query: str) -> str:
        try:
            result = await self.context.kb_manager.retrieve(
                query=query,
                kb_names=[KB_NAME],
                top_k_fusion=20,
                top_m_final=3,
            )
        except Exception as exc:
            logger.warning(f"离线知识库检索失败：{exc}")
            return ""
        return str((result or {}).get("context_text") or "")

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

    # AstrBot's built-in empty-mention listener uses sys.maxsize - 1 and
    # starts an LLM session before ordinary plugin handlers can see the event.
    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize)
    async def guard(self, event: AstrMessageEvent):
        if not self.enabled:
            return
        if self._is_bot(event) and not (self._is_friendly_bot(event) and self._has_at_bot(event)):
            # Ignore other bots, except friendly ones that explicitly @ this bot.
            event.stop_event()
            return
        poke_target = self._poke_target(event)
        if poke_target is not None and (not event.get_self_id() or poke_target != str(event.get_self_id())):
            # A notice about two other users is not a message addressed to this bot.
            event.stop_event()
            return
        now = datetime.now(self.scheduler.tz)
        decision = self._decision()
        self._publish_decision(decision)
        if poke_target is not None or self._is_empty_mention(event):
            kind = "poke" if poke_target is not None else "mention"
            choices = POKE_REPLIES if kind == "poke" else EMPTY_MENTION_REPLIES
            reply = random.choice(choices)
            if decision.offline and decision.reason == "high_cost":
                resume = format_resume(decision.resume_at, now) if decision.resume_at else "下班后"
                reply += f" 企鹅物流上班啦，不能陪老板聊，{resume}再来！"
            group_key = str(event.get_group_id() or "")
            if group_key:
                self._pending_trigger[group_key] = (str(event.get_sender_id() or ""), kind)
            await event.send(MessageChain([Plain(reply)]))
            event.stop_event()
            return
        if not decision.offline:
            hour_key = now.strftime("%Y-%m-%dT%H")
            count = self.state.bump_usage(hour_key)
            if self.hourly_model_limit > 0 and count > self.hourly_model_limit:
                decision = Decision(True, "usage_limit", self._next_hour(now), None)
                self._publish_decision(decision)
            else:
                group_key = str(event.get_group_id() or "")
                if group_key:
                    incoming = str(
                        getattr(getattr(event, "message_obj", None), "message_str", "")
                        or event.message_str
                        or ""
                    ).strip()
                    previous = self._last_addressed.get(group_key)
                    user_id = str(event.get_sender_id() or "")
                    carry = bool(
                        previous
                        and previous[0] == user_id
                        and now.timestamp() - previous[1] < 180
                    )
                    keyword = self._keyword_hit(incoming) and self._keyword_allowed(group_key, now.timestamp())
                    trigger = self.engagement.handle_message(
                        GroupMessage(
                            group_id=group_key,
                            user_id=user_id,
                            text=incoming,
                            nickname=str(event.get_sender_name() or ""),
                            at_bot=self._has_at_bot(event),
                            has_media=any(
                                type(component).__name__ in ("Image", "Record", "Video", "File")
                                for component in (getattr(event.message_obj, "message", None) or [])
                            ),
                            timestamp=now.timestamp(),
                        ),
                        wake_matched=bool(event.is_at_or_wake_command) and not self._has_at_bot(event) or keyword or carry,
                    )
                    if trigger:
                        self._pending_trigger[group_key] = (trigger.target_user, trigger.kind)
                        if trigger.kind in ("random", "continuation") or keyword or carry:
                            event.is_at_or_wake_command = True
                            logger.info(f"{trigger.kind} 触发 group={group_key} keyword={keyword} carry={carry}")
                    if (trigger and trigger.kind in ("wake", "mention", "quote", "continuation")) or keyword or carry:
                        self._last_addressed[group_key] = (user_id, now.timestamp())
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
        if not addressed and self._keyword_hit(text) and self._keyword_allowed(group, now.timestamp()):
            addressed = True
        if not addressed:
            previous = self._last_addressed.get(group)
            if previous and previous[0] == user and now.timestamp() - previous[1] < 180:
                addressed = True
        if not addressed:
            # Silence in groups unless directly @-ed, replied to, or continuing.
            event.stop_event()
            return
        self._last_addressed[group] = (user, now.timestamp())
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
        if self.local_model.enabled and reply is not None and detect_intent(text) == "default":
            knowledge = await self._knowledge(text)
            system = LOCAL_SYSTEM
            if decision.offline and resume_text:
                system += (
                    f"\n现在是出勤时间，你在企鹅物流送快递，回消息简短一点；"
                    f"有人问你怎么了、为什么不回，就说在出勤，{resume_text}回来。"
                )
            if knowledge:
                system += "\n\n参考设定（只用来理解，用自己的话简短回答，不要原文照抄）：\n" + knowledge[:1200]
            smart = await self.local_model.chat(system, text)
            if smart:
                reply = smart
                logger.info(f"本地模型兜底 group={group}")
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
            self._publish_mode()
            yield event.plain_result("已强制进入离线模式。发送 /离线 关 强制在线，或 /离线 自动 按时段判断。")
            return
        if command in ("关", "关闭", "off"):
            if not self._is_owner(event):
                yield event.plain_result("只有主人可以切换离线模式。")
                return
            self.state.set_manual("off")
            self._publish_mode()
            yield event.plain_result("已强制退出离线模式。发送 /离线 自动 恢复按时段判断。")
            return
        if command in ("自动", "auto"):
            if not self._is_owner(event):
                yield event.plain_result("只有主人可以切换离线模式。")
                return
            self.state.set_manual(None)
            self._publish_mode()
            yield event.plain_result("已恢复按时段自动判断。")
            return
        yield event.plain_result("用法：/离线 状态 | 开 | 关 | 自动")

    async def terminate(self) -> None:
        mode_timer = self._mode_timer_task
        if mode_timer and not mode_timer.done():
            mode_timer.cancel()
            with suppress(asyncio.CancelledError):
                await mode_timer
        task = self._daily_apple_pie_task
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if self._local_mode_task is not None:
            await self._local_mode_task
        await self.local_model.unload()
        await self.local_model.close()
        logger.info("fatfish offline stopped")
