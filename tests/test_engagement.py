import unittest
from unittest.mock import Mock

from bots.astrbot_plugin_fatfish_offline.engagement import (
    GroupConfig,
    GroupEngagement,
    GroupMessage,
)


def msg(text, *, user="u1", at_bot=False, reply_to="", timestamp=1000.0, is_bot=False):
    return GroupMessage(
        group_id="g1",
        user_id=user,
        text=text,
        nickname="群友",
        reply_to_id=reply_to,
        at_bot=at_bot,
        is_bot=is_bot,
        timestamp=timestamp,
    )


class EngagementTest(unittest.TestCase):
    def setUp(self):
        self.engine = GroupEngagement(
            GroupConfig(random_probability=1.0, random_cooldown=0, random_hourly_limit=10)
        )

    def test_mention_and_wake(self):
        mention = self.engine.handle_message(msg("在吗", at_bot=True))
        self.assertIsNotNone(mention)
        self.assertEqual(mention.kind, "mention")
        wake = self.engine.handle_message(msg("苹果乐", timestamp=1001), wake_matched=True)
        self.assertIsNotNone(wake)
        self.assertEqual(wake.kind, "wake")

    def test_bot_messages_ignored(self):
        self.assertIsNone(self.engine.handle_message(msg("我说完了", is_bot=True)))

    def test_random_needs_activity(self):
        self.assertIsNone(self.engine.handle_message(msg("一", timestamp=1000)))
        self.assertIsNone(self.engine.handle_message(msg("二", timestamp=1001)))
        self.assertIsNone(self.engine.handle_message(msg("三", timestamp=1002)))
        trigger = self.engine.handle_message(msg("今天打什么本", timestamp=1003))
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.kind, "random")

    def test_random_cooldown_blocks(self):
        engine = GroupEngagement(GroupConfig(random_probability=1.0, random_cooldown=300))
        for index in range(3):
            # Warm up activity without making a random-reply candidate yet.
            engine.handle_message(msg(f"聊{index}", timestamp=1000 + index))
        first = engine.handle_message(msg("接着说", timestamp=1010))
        self.assertEqual(first.kind, "random")
        engine.on_bot_sent(
            group_id="g1",
            text="好耶",
            target_user=None,
            trigger_kind="random",
            timestamp=1011,
        )
        for index in range(3):
            engine.handle_message(msg(f"新话题{index}", timestamp=1020 + index))
        self.assertIsNone(engine.handle_message(msg("还有呢", timestamp=1030)))

    def test_continuation_after_bot_reply(self):
        engine = GroupEngagement(GroupConfig(random_probability=0.0))
        engine.handle_message(msg("苹果乐在吗", at_bot=True, timestamp=1000))
        engine.on_bot_sent(
            group_id="g1",
            text="在！",
            target_user="u1",
            trigger_kind="mention",
            timestamp=1001,
        )
        trigger = engine.handle_message(msg("那你刚才说的呢", timestamp=1010))
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.kind, "continuation")

    def test_media_never_triggers(self):
        engine = GroupEngagement(GroupConfig(random_probability=1.0, random_cooldown=0))
        for index in range(3):
            engine.handle_message(msg(f"聊天{index}", timestamp=1000 + index))
        media = msg("看图", timestamp=1004)
        media.has_media = True
        self.assertIsNone(engine.handle_message(media))

    def test_probability_increases_per_unsent_opportunity_and_resets_only_after_send(self):
        engine = GroupEngagement(
            GroupConfig(
                random_probability=0.1,
                random_probability_step=0.1,
                random_probability_max=0.3,
                random_cooldown=0,
                random_hourly_limit=99,
            ), rng=Mock(random=Mock(return_value=.99))
        )
        for index in range(3):
            engine.handle_message(msg(f"聊{index}", timestamp=1000 + index))
        self.assertIsNone(engine.handle_message(msg("继续聊", timestamp=1004)))
        self.assertAlmostEqual(engine._current_probability("g1", 1005), 0.2)
        self.assertAlmostEqual(engine._current_probability("other:GroupMessage:g1", 1005), 0.1)
        engine.handle_message(msg("换个话题", timestamp=1005))
        engine.handle_message(msg("还有别的吗", timestamp=1006))
        self.assertAlmostEqual(engine._current_probability("g1", 1007), 0.3)
        engine.rng.random.return_value = 0
        trigger = engine.handle_message(msg("接着聊呀", timestamp=1007))
        self.assertEqual(trigger.kind, "random")
        self.assertEqual(engine.random_misses.get("g1"), 4)
        engine.on_bot_sent(group_id="g1", text="好耶", target_user=None, trigger_kind="random", timestamp=1008)
        self.assertEqual(engine.random_misses.get("g1"), 0)
        self.assertAlmostEqual(engine._current_probability("g1", 1009), 0.1)

    def test_zero_base_can_progress_but_zero_base_and_step_remain_disabled(self):
        for step in (0, .2):
            rng=Mock(random=Mock(return_value=.99))
            engine=GroupEngagement(GroupConfig(random_probability=0,random_probability_step=step),rng=rng)
            for index in range(3):engine.handle_message(msg(f"聊{index}",timestamp=1000+index))
            engine.handle_message(msg("值得接的话题",timestamp=1004))
            self.assertEqual(engine.random_misses.get("g1"),1 if step else 0)
            self.assertAlmostEqual(engine._current_probability("g1",1005),step)

    def test_cooldown_and_hour_limit_do_not_accumulate_misses(self):
        engine=GroupEngagement(GroupConfig(random_probability=.1,random_probability_step=.1,random_hourly_limit=1))
        engine.on_bot_sent(group_id="g1",text="刚说过",target_user=None,trigger_kind="random",timestamp=1000)
        for index in range(5):engine.handle_message(msg("普通群聊消息",timestamp=1010+index))
        self.assertEqual(engine.random_misses.get("g1"),0)

    def test_hit_reserves_cooldown_and_hour_budget_before_send_without_resetting_n(self):
        engine=GroupEngagement(GroupConfig(random_probability=1,random_cooldown=300,random_hourly_limit=1))
        for index in range(3):engine.handle_message(msg(f"聊{index}",timestamp=1000+index))
        self.assertEqual(engine.handle_message(msg("聊个新话题",timestamp=1004)).kind,'random')
        self.assertIsNone(engine.handle_message(msg("再聊个新话题",timestamp=1005)))
        self.assertEqual(engine.random_misses.get('g1'),1)
        self.assertEqual(len(engine.random_times['g1']),1)
        # Even after cooldown, the reserved hourly allowance is exhausted.
        for index in range(3):engine.handle_message(msg('重新热起来',timestamp=1400+index))
        self.assertIsNone(engine.handle_message(msg('又一个话题',timestamp=1404)))
        self.assertEqual(engine.random_misses.get('g1'),1)
        engine.on_bot_sent(group_id='g1',text='终于回复啦',target_user=None,trigger_kind='random',timestamp=1405)
        self.assertEqual(engine.random_misses.get('g1'),0)
        self.assertEqual(len(engine.random_times['g1']),1)

    def test_recent_context_format(self):
        self.engine.handle_message(msg("今天好累", timestamp=1000))
        context = self.engine.recent_context("g1", now=1001)
        self.assertIn("今天好累", context)
        self.assertIn("群友", context)


if __name__ == "__main__":
    unittest.main()
