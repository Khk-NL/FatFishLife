from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bots"))

from astrbot_plugin_fatfish_offline.daily_apple_pie import DailyApplePie  # noqa: E402
from astrbot_plugin_fatfish_offline.logic import SHANGHAI  # noqa: E402
from astrbot_plugin_fatfish_offline.state import StateStore  # noqa: E402


def moment(hour=18, minute=1, *, day=23, second=0):
    return datetime(2026, 10, day, hour, minute, second, tzinfo=SHANGHAI)


class DailyApplePieTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.store = StateStore(self.path)

    def schedule(self, value):
        rng = Mock()
        rng.random.return_value = value
        return DailyApplePie(self.store, rng=rng), rng

    def test_does_not_draw_before_1801(self):
        schedule, rng = self.schedule(0)
        for now in (moment(0, 0), moment(18, 0, second=59)):
            self.assertFalse(schedule.draw(now))
        rng.random.assert_not_called()
        self.assertEqual(self.store.daily_apple_pie_state(), {})

    def test_starts_at_1801(self):
        schedule, rng = self.schedule(0)
        self.assertTrue(schedule.draw(moment()))
        rng.random.assert_called_once()
        self.assertEqual(self.store.daily_apple_pie_state(), {
            "day": "2026-10-23", "last_slot": 0,
            "claimed": True, "status": "pending",
        })

    def test_probability_uses_strict_boundary(self):
        for hour, probability in ((18, .25), (19, .5), (20, .75)):
            for value, expected in ((probability - .0001, True), (probability, False)):
                with self.subTest(hour=hour, value=value):
                    store = StateStore(self.path / f"{hour}-{value}")
                    rng = Mock(random=Mock(return_value=value))
                    self.assertEqual(DailyApplePie(store, rng).draw(moment(hour)), expected)

    def test_hourly_probability_increases_and_caps_at_one(self):
        schedule, rng = self.schedule(.99)
        for hour in (18, 19, 20):
            self.assertFalse(schedule.draw(moment(hour)))
        self.assertTrue(schedule.draw(moment(21)))
        self.assertEqual(rng.random.call_count, 4)
        for hour in (22, 23):
            store = StateStore(self.path / str(hour))
            self.assertTrue(DailyApplePie(store, rng).draw(moment(hour)))

    def test_failed_draw_is_once_per_current_slot(self):
        schedule, rng = self.schedule(.99)
        self.assertFalse(schedule.draw(moment()))
        for now in (moment(18, 1, second=30), moment(18, 59), moment(19, 0, second=59)):
            self.assertFalse(schedule.draw(now))
        rng.random.assert_called_once()
        self.assertFalse(schedule.draw(moment(19)))
        self.assertEqual(rng.random.call_count, 2)

    def test_failed_draw_is_persisted_across_restart(self):
        schedule, rng = self.schedule(.99)
        self.assertFalse(schedule.draw(moment()))
        restarted_rng = Mock(random=Mock(return_value=0))
        restarted = DailyApplePie(StateStore(self.path), restarted_rng)
        self.assertFalse(restarted.draw(moment(18, 50)))
        restarted_rng.random.assert_not_called()
        self.assertTrue(restarted.draw(moment(19)))

    def test_restart_draws_current_slot_without_catching_up(self):
        schedule, rng = self.schedule(.6)
        self.assertTrue(schedule.draw(moment(20, 37)))
        rng.random.assert_called_once()
        self.assertEqual(self.store.daily_apple_pie_state()["last_slot"], 2)

    def test_claim_blocks_duplicate_even_without_finish(self):
        schedule, rng = self.schedule(0)
        self.assertTrue(schedule.draw(moment()))
        restarted_rng = Mock(random=Mock(return_value=0))
        restarted = DailyApplePie(StateStore(self.path), restarted_rng)
        self.assertFalse(restarted.draw(moment(23, 59)))
        restarted_rng.random.assert_not_called()
        self.assertEqual(restarted.store.daily_apple_pie_state()["status"], "pending")

    def test_finish_success_persists_sent(self):
        schedule, _ = self.schedule(0)
        self.assertTrue(schedule.draw(moment()))
        schedule.finish(moment(), True)
        restarted = DailyApplePie(StateStore(self.path))
        self.assertEqual(restarted.store.daily_apple_pie_state()["status"], "sent")
        self.assertFalse(restarted.draw(moment(19)))

    def test_finish_failure_does_not_mark_sent_or_retry(self):
        schedule, rng = self.schedule(0)
        self.assertTrue(schedule.draw(moment()))
        schedule.finish(moment(), False)
        self.assertEqual(self.store.daily_apple_pie_state()["status"], "failed")
        for now in (moment(19), moment(23, 59)):
            self.assertFalse(schedule.draw(now))
        rng.random.assert_called_once()
        restarted = DailyApplePie(StateStore(self.path))
        self.assertFalse(restarted.draw(moment(23, 59)))
        schedule.finish(moment(), True)
        self.assertEqual(self.store.daily_apple_pie_state()["status"], "failed")

    def test_finish_without_current_pending_claim_is_noop(self):
        schedule, _ = self.schedule(.99)
        schedule.finish(moment(), True)
        self.assertEqual(self.store.daily_apple_pie_state(), {})
        schedule.draw(moment())
        schedule.finish(moment(), True)
        self.assertEqual(self.store.daily_apple_pie_state()["status"], "missed")
        schedule.draw(moment(21))
        schedule.finish(moment(day=24), True)
        self.assertEqual(self.store.daily_apple_pie_state()["status"], "pending")

    def test_next_day_allows_fresh_draw_including_weekends(self):
        schedule, rng = self.schedule(0)
        self.assertTrue(schedule.draw(moment()))
        self.assertFalse(schedule.draw(moment(0, 0, day=24)))
        self.assertFalse(schedule.draw(moment(18, 0, day=24)))
        self.assertTrue(schedule.draw(moment(day=24)))
        self.assertEqual(rng.random.call_count, 2)
        self.assertEqual(self.store.daily_apple_pie_state()["day"], "2026-10-24")

    def test_aware_datetimes_are_converted_to_beijing(self):
        schedule, _ = self.schedule(0)
        self.assertFalse(schedule.draw(datetime(2026, 10, 23, 10, 0, 59, tzinfo=timezone.utc)))
        self.assertTrue(schedule.draw(datetime(2026, 10, 23, 10, 1, tzinfo=timezone.utc)))
        self.assertEqual(self.store.daily_apple_pie_state()["day"], "2026-10-23")
        # UTC is still on the 23rd, but Beijing has already entered the 24th.
        self.assertFalse(schedule.draw(datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)))
        self.assertTrue(schedule.draw(datetime(2026, 10, 24, 10, 1, tzinfo=timezone.utc)))

    def test_naive_datetimes_are_beijing_time(self):
        schedule, _ = self.schedule(0)
        self.assertTrue(schedule.draw(datetime(2026, 10, 23, 18, 1)))

    def test_clock_rollback_does_not_redraw_an_earlier_slot(self):
        schedule, rng = self.schedule(.99)
        self.assertFalse(schedule.draw(moment(20)))
        self.assertFalse(schedule.draw(moment(19)))
        rng.random.assert_called_once()

    def test_save_failure_does_not_authorize_send(self):
        schedule, _ = self.schedule(0)
        self.store._save = Mock(side_effect=OSError("disk unavailable"))
        with self.assertRaises(OSError):
            schedule.draw(moment())

    def test_next_check_before_start_and_after_missed_slots(self):
        schedule, _ = self.schedule(.99)
        cases = (
            (moment(0, 0), moment()),
            (moment(18, 0, second=59), moment()),
            (moment(), moment(19)),
            (moment(18, 59), moment(19)),
            (moment(19, 0), moment(19)),
            (moment(19, 1), moment(20)),
            (moment(23, 0), moment(23)),
            (moment(23, 1), moment(day=24)),
            (moment(23, 59), moment(day=24)),
        )
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(schedule.next_check(now), expected)

    def test_next_check_after_any_claim_is_tomorrow(self):
        schedule, _ = self.schedule(0)
        self.assertTrue(schedule.draw(moment()))
        for success in (None, False):
            if success is not None:
                schedule.finish(moment(), success)
            self.assertEqual(schedule.next_check(moment()), moment(day=24))
            self.assertEqual(schedule.next_check(moment(23, 59)), moment(day=24))
        self.assertEqual(schedule.next_check(moment(0, 0, day=24)), moment(day=24))

    def test_next_check_uses_beijing_timezone(self):
        schedule, _ = self.schedule(0)
        self.assertEqual(
            schedule.next_check(datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)),
            moment(),
        )
        self.assertEqual(schedule.next_check(moment(23, 59)).utcoffset(), timedelta(hours=8))


if __name__ == "__main__":
    unittest.main()
