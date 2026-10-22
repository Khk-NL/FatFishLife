import unittest

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
            engine.handle_message(msg(f"聊天{index}", timestamp=1000 + index))
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

    def test_probability_decays_and_resets_hourly(self):
        engine = GroupEngagement(
            GroupConfig(
                random_probability=1.0,
                random_cooldown=0,
                random_hourly_limit=99,
                decay_factor=0.5,
            )
        )
        for index in range(3):
            engine.handle_message(msg(f"聊{index}", timestamp=1000 + index))
        trigger = engine.handle_message(msg("继续聊", timestamp=1004))
        self.assertEqual(trigger.kind, "random")
        self.assertAlmostEqual(engine._current_probability("g1", 1005), 0.5)
        self.assertAlmostEqual(engine._current_probability("g1", 1005 + 3600), 1.0)

    def test_recent_context_format(self):
        self.engine.handle_message(msg("今天好累", timestamp=1000))
        context = self.engine.recent_context("g1", now=1001)
        self.assertIn("今天好累", context)
        self.assertIn("群友", context)


if __name__ == "__main__":
    unittest.main()
