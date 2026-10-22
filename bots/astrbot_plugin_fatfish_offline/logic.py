"""Pure offline logic: billing windows, resume time, intent matching, throttling.

No AstrBot imports here on purpose: this module is unit-testable and can be
reused if the bot framework changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

try:
    from chinese_calendar import is_workday as _cn_is_workday
except ImportError:  # optional dependency; fall back to weekday rules
    _cn_is_workday = None

try:
    from zoneinfo import ZoneInfo

    SHANGHAI = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - Windows without tzdata
    SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


@dataclass(frozen=True)
class Window:
    start: str
    end: str
    reason: str = "high_cost"


@dataclass
class Decision:
    offline: bool
    reason: str | None = None
    resume_at: datetime | None = None
    window: Window | None = None


def parse_windows(values) -> list[Window]:
    windows: list[Window] = []
    for value in values or []:
        if isinstance(value, Window):
            windows.append(value)
            continue
        if isinstance(value, dict):
            start = str(value.get("start") or "").strip()
            end = str(value.get("end") or "").strip()
            reason = str(value.get("reason") or "high_cost").strip()
        else:
            match = re.match(r"^\s*(\d{1,2}:\d{2})\s*[-~到]\s*(\d{1,2}:\d{2})\s*(?::\s*(\w+))?\s*$", str(value))
            if not match:
                continue
            start, end, reason = match.group(1), match.group(2), match.group(3) or "high_cost"
        try:
            parse_clock(start)
            parse_clock(end)
        except ValueError:
            continue
        windows.append(Window(start.zfill(5), end.zfill(5), reason))
    return windows


def parse_clock(value: str) -> time:
    hour, minute = value.strip().split(":")
    hour, minute = int(hour), int(minute)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(value)
    return time(hour, minute)


class Scheduler:
    def __init__(
        self,
        windows,
        *,
        weekdays=(0, 1, 2, 3, 4),
        holidays=(),
        workdays=(),
        holiday_source="auto",
        tz=SHANGHAI,
    ):
        self.windows = parse_windows(windows)
        self.weekdays = {int(day) for day in weekdays}
        self.holidays = set(holidays or ())
        self.workdays = set(workdays or ())
        self.holiday_source = holiday_source
        self.tz = tz

    def is_workday(self, moment: datetime) -> bool:
        day = moment.date()
        day_text = day.isoformat()
        # Explicit overrides win over both the automatic calendar and weekdays.
        if day_text in self.holidays:
            return False
        if day_text in self.workdays:
            return True
        if self.holiday_source == "auto" and _cn_is_workday is not None:
            try:
                return bool(_cn_is_workday(day))
            except (ValueError, KeyError, NotImplementedError):
                pass
        return moment.weekday() in self.weekdays

    def check(self, now: datetime | None = None) -> Decision:
        moment = (now or datetime.now(self.tz)).astimezone(self.tz)
        if not self.is_workday(moment):
            return Decision(False)
        clock = moment.time()
        for window in self.windows:
            start, end = parse_clock(window.start), parse_clock(window.end)
            if start <= clock < end:
                resume = datetime.combine(moment.date(), end, tzinfo=moment.tzinfo)
                return Decision(True, window.reason, resume, window)
        return Decision(False)

    def next_resume(self, now: datetime | None = None) -> datetime | None:
        """Return the next moment normal AI resumes: always a window end."""
        moment = (now or datetime.now(self.tz)).astimezone(self.tz)
        clock = moment.time()
        if self.is_workday(moment):
            for window in self.windows:
                start, end = parse_clock(window.start), parse_clock(window.end)
                if start <= clock < end:
                    return datetime.combine(moment.date(), end, tzinfo=moment.tzinfo)
        for offset in range(0, 8):
            day = moment.date() + timedelta(days=offset)
            probe = datetime.combine(day, time(0, 0), tzinfo=moment.tzinfo)
            if not self.is_workday(probe):
                continue
            for window in sorted(self.windows, key=lambda item: item.start):
                end_dt = datetime.combine(day, parse_clock(window.end), tzinfo=moment.tzinfo)
                if end_dt > moment:
                    return end_dt
        return None

    def next_window(self, now: datetime | None = None) -> datetime | None:
        moment = (now or datetime.now(self.tz)).astimezone(self.tz)
        for offset in range(0, 8):
            day = moment.date() + timedelta(days=offset)
            probe = datetime.combine(day, time(0, 0), tzinfo=moment.tzinfo)
            if not self.is_workday(probe):
                continue
            for window in sorted(self.windows, key=lambda item: item.start):
                start = datetime.combine(day, parse_clock(window.start), tzinfo=moment.tzinfo)
                if start > moment:
                    return start
        return None


def format_resume(resume: datetime, now: datetime | None = None) -> str:
    if resume is None:
        return "晚点"
    now = (now or datetime.now(resume.tzinfo)).astimezone(resume.tzinfo)
    hour = resume.hour
    if resume.date() == now.date():
        if hour == 12:
            return "中午12点"
        if 1 <= hour < 6:
            return f"凌晨{hour}点"
        if 6 <= hour < 12:
            return f"上午{hour}点"
        if 12 < hour < 19:
            return f"下午{hour - 12}点"
        if 19 <= hour < 24:
            return f"晚上{hour - 12}点"
        return "0点"
    if hour == 12:
        return "明天中午12点"
    if 6 <= hour < 12:
        return f"明天上午{hour}点"
    if 12 < hour < 19:
        return f"明天下午{hour - 12}点"
    if 19 <= hour < 24:
        return f"明天晚上{hour - 12}点"
    return f"明天{hour}点"


INTENT_PATTERNS: list[tuple[str, str]] = [
    ("urgent", r"(救命|急事|出事了|自杀|自残|不想活|难受得快|报警|急救)"),
    ("who_are_you", r"(你是谁|你叫什么|你是什么|介绍一下自己|自我介绍)"),
    ("where_from", r"(你从哪|你从哪里|哪里来的|哪里人|泰拉|拉特兰)"),
    ("relationship", r"(能天使|蕾缪乐|什么关系|同一个人|是不是同)"),
    ("how_online", r"(怎么在QQ|怎么上网|怎么连上|跨世界|互联网|前文明)"),
    ("are_you_ai", r"(你是AI|你是ai|机器人|人工智能|真人吗|是不是人)"),
    ("abilities", r"(你会什么|你能干嘛|能做什么|会做什么|有什么功能)"),
    ("why_apple", r"(为什么是苹果|怎么变成苹果|苹果形态|变成苹果)"),
    ("when_resume", r"(几点|什么时候|啥时候|多久|恢复|回来|上线|营业|复活)"),
    ("why_silent", r"(怎么不回|怎么不说话|为什么不说话|为什么不理|没反应|装死|死机|掉线|卡了|怎么不理)"),
    ("greeting", r"^(你好|您好|在吗|在不在|嗨|hi|hello|哈喽|喂)[!！?？。~～]*$"),
    ("what_doing", r"(在干嘛|在干什么|忙什么|做什么|干啥呢|在忙)"),
    ("praise", r"(可爱|好可爱|厉害|喜欢你|好棒|萌)"),
    ("tease", r"(傻|笨|菜|憨|抽象|滚一个|胖)"),
    ("invite", r"(打游戏|开黑|来玩|上号|开一把|联机|一起玩)"),
    ("apple_form", r"(苹果|果皮|榨汁|削皮|叶子|果梗|果核|好吃|咬一口|吃掉)"),
    ("complex", r"(为什么|怎么理解|解释|分析|写个|帮我写|翻译|代码|论文|政治|股票)"),
]


def detect_intent(text: str, *, addressed: bool = False, follow_up: bool = False) -> str:
    content = (text or "").strip()
    if not content:
        return "none"
    for intent, pattern in INTENT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return intent
    if addressed:
        return "default"
    if follow_up:
        return "follow_up"
    return "none"


class Throttle:
    """In-memory cooldown; restart resets it, which is acceptable for chat."""

    def __init__(self, *, group_cooldown=30, user_cooldown=300, max_per_hour=8):
        self.group_cooldown = max(0, int(group_cooldown))
        self.user_cooldown = max(0, int(user_cooldown))
        self.max_per_hour = max(1, int(max_per_hour))
        self._group_last: dict[str, datetime] = {}
        self._user_last: dict[tuple[str, str], datetime] = {}
        self._hour: dict[str, list[datetime]] = {}

    def allow(self, group: str, user: str, now: datetime | None = None, *, bypass_user: bool = False) -> bool:
        moment = now or datetime.now(SHANGHAI)
        last_group = self._group_last.get(group)
        if last_group and (moment - last_group).total_seconds() < self.group_cooldown:
            return False
        if not bypass_user:
            last_user = self._user_last.get((group, user))
            if last_user and (moment - last_user).total_seconds() < self.user_cooldown:
                return False
        recent = [item for item in self._hour.get(group, []) if (moment - item).total_seconds() < 3600]
        if len(recent) >= self.max_per_hour:
            return False
        return True

    def mark(self, group: str, user: str, now: datetime | None = None) -> None:
        moment = now or datetime.now(SHANGHAI)
        self._group_last[group] = moment
        self._user_last[(group, user)] = moment
        recent = [item for item in self._hour.get(group, []) if (moment - item).total_seconds() < 3600]
        recent.append(moment)
        self._hour[group] = recent

    def reset(self) -> None:
        self._group_last.clear()
        self._user_last.clear()
        self._hour.clear()


class ShortContext:
    """Per-group recent interaction, expires so stale users are not mixed up."""

    def __init__(self, ttl_seconds: int = 600):
        self.ttl = max(30, int(ttl_seconds))
        self._data: dict[str, dict] = {}

    def get(self, group: str, now: datetime | None = None) -> dict | None:
        moment = now or datetime.now(SHANGHAI)
        item = self._data.get(group)
        if not item:
            return None
        if (moment - item["at"]).total_seconds() > self.ttl:
            self._data.pop(group, None)
            return None
        return item

    def set(self, group: str, *, user: str, intent: str, reply: str, now: datetime | None = None) -> None:
        self._data[group] = {"user": user, "intent": intent, "reply": reply, "at": now or datetime.now(SHANGHAI)}

    def is_follow_up(self, group: str, user: str, now: datetime | None = None) -> bool:
        item = self.get(group, now)
        return bool(item and item["user"] == user)
