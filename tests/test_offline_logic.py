from __future__ import annotations

import random
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bots" / "astrbot_plugin_fatfish_offline"))

from logic import (  # noqa: E402
    SHANGHAI,
    Scheduler,
    ShortContext,
    Throttle,
    detect_intent,
    format_resume,
    parse_windows,
)
from templates import pick  # noqa: E402


def moment(day: int, hour: int, minute: int = 0, month: int = 10):
    return datetime(2026, month, day, hour, minute, tzinfo=SHANGHAI)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = Scheduler(["08:00-12:00", "14:00-18:00"])

    def test_weekday_morning_window(self):
        decision = self.scheduler.check(moment(23, 10))
        self.assertTrue(decision.offline)
        self.assertEqual(decision.reason, "high_cost")
        self.assertEqual(decision.resume_at.hour, 12)

    def test_weekday_afternoon_window(self):
        decision = self.scheduler.check(moment(23, 15))
        self.assertTrue(decision.offline)
        self.assertEqual(decision.resume_at.hour, 18)

    def test_window_boundaries(self):
        self.assertFalse(self.scheduler.check(moment(23, 12)).offline)
        self.assertFalse(self.scheduler.check(moment(23, 18)).offline)
        self.assertFalse(self.scheduler.check(moment(23, 7, 59)).offline)
        self.assertTrue(self.scheduler.check(moment(23, 13, 59)).offline is False)

    def test_weekend_is_online(self):
        self.assertFalse(self.scheduler.check(moment(24, 10)).offline)

    def test_holiday_exception(self):
        scheduler = Scheduler(["08:00-12:00"], holidays=["2026-10-23"])
        self.assertFalse(scheduler.check(moment(23, 10)).offline)

    def test_make_up_workday(self):
        scheduler = Scheduler(["08:00-12:00"], workdays=["2026-10-24"])
        self.assertTrue(scheduler.check(moment(24, 10)).offline)

    def test_custom_window(self):
        scheduler = Scheduler(["09:30-10:15"])
        decision = scheduler.check(moment(23, 10))
        self.assertTrue(decision.offline)
        self.assertEqual((decision.resume_at.hour, decision.resume_at.minute), (10, 15))

    def test_next_window(self):
        self.assertEqual(self.scheduler.next_window(moment(23, 12, 30)).hour, 14)
        self.assertEqual(self.scheduler.next_window(moment(23, 19)).hour, 8)
        self.assertEqual(self.scheduler.next_window(moment(23, 19)).day, 26)

    def test_resume_text(self):
        self.assertEqual(format_resume(moment(23, 12), moment(23, 10)), "中午12点")
        self.assertEqual(format_resume(moment(23, 18), moment(23, 15)), "下午6点")
        self.assertEqual(format_resume(moment(26, 8), moment(23, 19)), "明天上午8点")

    def test_parse_windows_rejects_bad_values(self):
        windows = parse_windows(["08:00-12:00", "bad", {"start": "14:00", "end": "18:00"}])
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[1].start, "14:00")


class IntentTests(unittest.TestCase):
    def test_intents(self):
        self.assertEqual(detect_intent("几点回来"), "when_resume")
        self.assertEqual(detect_intent("你什么时候恢复"), "when_resume")
        self.assertEqual(detect_intent("在干嘛呢"), "what_doing")
        self.assertEqual(detect_intent("怎么不说话了"), "why_silent")
        self.assertEqual(detect_intent("你好"), "greeting")
        self.assertEqual(detect_intent("苹果好吃吗"), "apple_form")
        self.assertEqual(detect_intent("来打游戏吗"), "invite")
        self.assertEqual(detect_intent("救命"), "urgent")
        self.assertEqual(detect_intent("苹果乐你好可爱", addressed=True), "praise")
        self.assertEqual(detect_intent("今天天气不错", addressed=False), "none")
        self.assertEqual(detect_intent("今天天气不错", addressed=True), "default")
        self.assertEqual(detect_intent("随便说说", follow_up=True), "follow_up")

    def test_identity_intents(self):
        self.assertEqual(detect_intent("你是谁"), "who_are_you")
        self.assertEqual(detect_intent("你从哪里来"), "where_from")
        self.assertEqual(detect_intent("你和能天使什么关系"), "relationship")
        self.assertEqual(detect_intent("你怎么在QQ上"), "how_online")
        self.assertEqual(detect_intent("你是AI吗"), "are_you_ai")
        self.assertEqual(detect_intent("你会什么"), "abilities")
        self.assertEqual(detect_intent("你为什么是苹果"), "why_apple")


class ThrottleTests(unittest.TestCase):
    def test_group_and_user_cooldown(self):
        throttle = Throttle(group_cooldown=30, user_cooldown=300, max_per_hour=5)
        now = moment(23, 10)
        self.assertTrue(throttle.allow("g1", "u1", now))
        throttle.mark("g1", "u1", now)
        self.assertFalse(throttle.allow("g1", "u2", now + timedelta(seconds=10)))
        self.assertFalse(throttle.allow("g1", "u1", now + timedelta(seconds=60)))
        self.assertTrue(throttle.allow("g1", "u1", now + timedelta(seconds=301)))
        self.assertTrue(throttle.allow("g1", "u1", now + timedelta(seconds=60), bypass_user=True))

    def test_hourly_cap(self):
        throttle = Throttle(group_cooldown=0, user_cooldown=0, max_per_hour=2)
        now = moment(23, 10)
        for index in range(2):
            self.assertTrue(throttle.allow("g1", f"u{index}", now + timedelta(seconds=index)))
            throttle.mark("g1", f"u{index}", now + timedelta(seconds=index))
        self.assertFalse(throttle.allow("g1", "u9", now + timedelta(seconds=10)))

    def test_context_expires(self):
        context = ShortContext(ttl_seconds=60)
        now = moment(23, 10)
        context.set("g1", user="u1", intent="greeting", reply="x", now=now)
        self.assertTrue(context.is_follow_up("g1", "u1", now + timedelta(seconds=30)))
        self.assertFalse(context.is_follow_up("g1", "u1", now + timedelta(seconds=120)))
        self.assertFalse(context.is_follow_up("g1", "u2", now))


class TemplateTests(unittest.TestCase):
    def test_placeholder_and_recent_avoidance(self):
        rng = random.Random(1)
        line = pick("high_cost", "first_notice", name="小明", resume="中午12点", recent=[], rng=rng)
        self.assertIn("中午12点", line)
        self.assertNotIn("{resume}", line)

    def test_unknown_intent_falls_back(self):
        line = pick("high_cost", "unknown_intent", name="x", resume="中午12点", recent=[], rng=random.Random(2))
        self.assertTrue(line)


if __name__ == "__main__":
    unittest.main()
