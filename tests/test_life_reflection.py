from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bots"))

from astrbot_plugin_fatfish_life.reflection import (  # noqa: E402
    DEFAULT_WEIGHTS, DailyLifeState, json_object, number, public_facts,
)


DAY = "2026-10-23"
FACTS = [{"id": "7", "text": "今天和大家聊了苹果派。"}]


def proposal(**changes):
    result = {
        "wants_to_share": True,
        "text": "今天和大家聊了苹果派，老板们还挺有精神嘛。",
        "evidence_ids": ["7"],
        "reason": "今天有一段有趣的公开互动。",
    }
    result.update(changes)
    return result


class DailyLifeStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.rng = Mock()
        self.rng.random.return_value = 0
        self.state = DailyLifeState(self.path, self.rng)

    def fresh(self, name="other.json", *, draw=0, route=0):
        rng = Mock()
        rng.random.side_effect = [draw, route]
        return DailyLifeState(self.path.with_name(name), rng), rng

    def test_unsent_days_increase_twenty_and_cap_at_one_hundred(self):
        start = date.fromisoformat(DAY)
        actual = []
        for offset in range(7):
            day = (start + timedelta(days=offset)).isoformat()
            record = self.state.decide(day, proposal(wants_to_share=False), FACTS)
            actual.append(record["base_probability"])
            self.state.finish(day)
        self.assertEqual(actual, [20, 40, 60, 80, 100, 100, 100])

    def test_missed_calendar_days_raise_the_base_once(self):
        self.state.decide(DAY, proposal(wants_to_share=False), FACTS)
        self.state.finish(DAY)
        restarted = DailyLifeState(self.path)
        self.assertEqual(restarted.begin("2026-10-26")["base_probability"], 80)
        self.assertEqual(restarted.begin("2026-10-26")["base_probability"], 80)

    def test_long_calendar_gap_caps_at_one_hundred(self):
        self.state.decide(DAY, proposal(wants_to_share=False), FACTS)
        self.state.finish(DAY)
        self.assertEqual(self.state.begin("2026-11-23")["base_probability"], 100)

    def test_any_real_success_resets_next_day_to_twenty(self):
        for platform in ("bilibili", "qzone"):
            with self.subTest(platform=platform):
                state, _ = self.fresh(f"{platform}.json")
                state.data["next_probability"] = 80
                state.decide(DAY, proposal(platform_weights={platform: 100}), FACTS)
                self.assertTrue(state.claim(DAY, platform))
                state.result(DAY, platform, {"status": "sent", "id": "receipt"})
                state.finish(DAY)
                self.assertEqual(DailyLifeState(state.path).begin("2026-10-24")["base_probability"], 20)
                self.assertEqual(state.data["last_success_day"], DAY)

    def test_both_platforms_partial_success_also_resets(self):
        self.state.data["next_probability"] = 80
        self.state.decide(DAY, proposal(platform_weights={"both": 100}), FACTS)
        for platform, status in (("bilibili", "sent"), ("qzone", "failed")):
            self.assertTrue(self.state.claim(DAY, platform))
            self.state.result(DAY, platform, {"status": status})
        self.state.finish(DAY)
        self.assertEqual(self.state.begin("2026-10-24")["base_probability"], 20)

    def test_failure_preview_and_uncertain_do_not_reset_probability(self):
        for status in ("failed", "preview", "uncertain", "blocked"):
            with self.subTest(status=status):
                state, _ = self.fresh(f"{status}.json")
                state.data["next_probability"] = 60
                state.decide(DAY, proposal(), FACTS)
                self.assertTrue(state.claim(DAY, "bilibili"))
                state.result(DAY, "bilibili", {"status": status})
                state.finish(DAY)
                self.assertEqual(state.begin("2026-10-24")["base_probability"], 80)
                self.assertNotIn("last_success_day", state.data)

    def test_probability_adjustments_are_bounded_to_twenty_points(self):
        for value, expected in ((99, 20), (-99, -20), (7.5, 7.5), ("bad", 0), (float("nan"), 0)):
            with self.subTest(value=value):
                state, _ = self.fresh(str(len(list(self.path.parent.iterdir()))) + ".json")
                state.data["next_probability"] = 60
                record = state.decide(DAY, proposal(probability_adjustment=value), FACTS)
                self.assertEqual(record["probability_adjustment"], expected)
                self.assertEqual(record["probability"], 60 + expected)

    def test_adjustment_can_suppress_or_cap_today_without_changing_base(self):
        for base, adjustment, expected in ((20, -20, 0), (100, 20, 100)):
            with self.subTest(base=base):
                state, _ = self.fresh(f"base-{base}.json")
                state.data["next_probability"] = base
                record = state.decide(DAY, proposal(probability_adjustment=adjustment), FACTS)
                self.assertEqual(record["probability"], expected)
                self.assertEqual(record["base_probability"], base)
                self.assertEqual(bool(record["targets"]), expected > 0)

    def test_posting_probability_uses_a_strict_boundary(self):
        for draw, expected in ((.199999, True), (.2, False)):
            with self.subTest(draw=draw):
                state, rng = self.fresh(f"boundary-{draw}.json", draw=draw)
                record = state.decide(DAY, proposal(), FACTS)
                self.assertEqual(bool(record["targets"]), expected)
                self.assertEqual(rng.random.call_count, 2 if expected else 1)

    def test_default_routes_have_forty_five_forty_five_ten_boundaries(self):
        for value, expected in ((0, ["bilibili"]), (.449999, ["bilibili"]),
                                (.45, ["qzone"]), (.899999, ["qzone"]),
                                (.9, ["bilibili", "qzone"]), (.999999, ["bilibili", "qzone"])):
            with self.subTest(route_draw=value):
                state, _ = self.fresh(f"route-{value}.json", route=value)
                record = state.decide(DAY, proposal(), FACTS)
                self.assertEqual(record["platform_weights"], DEFAULT_WEIGHTS)
                self.assertEqual(record["targets"], expected)

    def test_model_can_change_platform_weights_and_they_are_normalized(self):
        state, _ = self.fresh(route=.3)
        record = state.decide(DAY, proposal(platform_weights={"bilibili": 1, "qzone": 3, "both": 0}), FACTS)
        self.assertEqual(record["platform_weights"], {"bilibili": 25, "qzone": 75, "both": 0})
        self.assertEqual(record["targets"], ["qzone"])

    def test_invalid_or_zero_weights_use_defaults(self):
        for weights in ({}, {"bilibili": -3, "qzone": "bad", "both": float("inf")}, "bad"):
            with self.subTest(weights=weights):
                state, _ = self.fresh(f"weights-{len(list(self.path.parent.iterdir()))}.json")
                record = state.decide(DAY, proposal(platform_weights=weights), FACTS)
                self.assertEqual(record["platform_weights"], DEFAULT_WEIGHTS)

    def test_model_can_decline_even_when_the_draw_would_succeed(self):
        for wants in (False, "true", 1, None):
            with self.subTest(wants=wants):
                state, rng = self.fresh(f"wants-{str(wants)}.json")
                record = state.decide(DAY, proposal(wants_to_share=wants), FACTS)
                self.assertEqual(record["targets"], [])
                self.assertEqual(record["status"], "skipped")
                self.assertEqual(rng.random.call_count, 1)

    def test_no_facts_or_invalid_evidence_never_authorizes_posting(self):
        for facts, ids in (([], ["7"]), (FACTS, []), (FACTS, ["99"]),
                           (FACTS, ["7", "99"]), (FACTS, "7"), (FACTS, None)):
            with self.subTest(facts=facts, ids=ids):
                state, _ = self.fresh(f"evidence-{len(list(self.path.parent.iterdir()))}.json")
                record = state.decide(DAY, proposal(evidence_ids=ids), facts)
                self.assertFalse(record["draft_safe"])
                self.assertEqual(record["targets"], [])

    def test_long_blank_identity_mentions_and_urls_are_rejected(self):
        for text in ("", "  \n", "好" * 161, "今天遇到 1670515707 了", "老板@苹果乐", "老板＠苹果乐",
                     "看了 https://example.com/a", "看看 www.example.com", "邮箱 test@example.com"):
            with self.subTest(text=text[:24]):
                state, _ = self.fresh(f"unsafe-{len(list(self.path.parent.iterdir()))}.json")
                record = state.decide(DAY, proposal(text=text), FACTS)
                self.assertFalse(record["draft_safe"])
                self.assertEqual(record["targets"], [])

    def test_short_draft_whitespace_is_normalized_and_limit_is_inclusive(self):
        record = self.state.decide(DAY, proposal(text="“" + "好" * 160 + "”"), FACTS)
        self.assertTrue(record["draft_safe"])
        self.assertEqual(record["text"], "好" * 160)

    def test_same_day_decision_survives_reload_without_reroll(self):
        first = self.state.decide(DAY, proposal(), FACTS)
        self.assertEqual(self.rng.random.call_count, 2)
        restarted_rng = Mock(random=Mock(side_effect=AssertionError("must not redraw")))
        restarted = DailyLifeState(self.path, restarted_rng)
        again = restarted.decide(DAY, proposal(text="换一个草稿", platform_weights={"both": 100}), FACTS)
        self.assertEqual(again, first)
        restarted_rng.random.assert_not_called()

    def test_claim_is_persisted_before_authorization_and_cannot_repeat(self):
        self.state.decide(DAY, proposal(), FACTS)
        self.assertTrue(self.state.claim(DAY, "bilibili"))
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["days"][DAY]["results"]["bilibili"], {"status": "sending"})
        self.assertFalse(self.state.claim(DAY, "bilibili"))
        self.assertFalse(self.state.claim(DAY, "qzone"))

    def test_failed_claim_persistence_never_returns_authorization(self):
        self.state.decide(DAY, proposal(), FACTS)
        with patch.object(self.state, "save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.state.claim(DAY, "bilibili")

    def test_inflight_restart_becomes_uncertain_and_pauses_only_that_platform(self):
        self.state.decide(DAY, proposal(platform_weights={"both": 100}), FACTS)
        self.assertTrue(self.state.claim(DAY, "bilibili"))
        restarted = DailyLifeState(self.path)
        self.assertEqual(restarted.data["days"][DAY]["results"]["bilibili"]["status"], "uncertain")
        self.assertIn("bilibili", restarted.data["paused"])
        self.assertNotIn("qzone", restarted.data["paused"])
        self.assertFalse(restarted.claim(DAY, "bilibili"))
        disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(disk["days"][DAY]["results"]["bilibili"]["status"], "uncertain")

    def test_authentication_risk_or_uncertain_receipts_pause_platform(self):
        for code in ("not_logged_in", "auth_expired", "risk_control", "captcha_required"):
            with self.subTest(code=code):
                state, _ = self.fresh(f"pause-{code}.json")
                state.decide(DAY, proposal(), FACTS)
                state.result(DAY, "bilibili", {"status": "failed", "error": {"code": code}})
                self.assertEqual(state.data["paused"]["bilibili"], code)

    def test_resume_does_not_reauthorize_blocked_old_post_but_allows_future(self):
        self.state.data["paused"]["bilibili"] = "auth_expired"
        self.state.decide(DAY, proposal(), FACTS)
        self.assertFalse(self.state.claim(DAY, "bilibili"))
        self.state.finish(DAY)
        self.state.resume("bilibili")
        self.assertFalse(self.state.claim(DAY, "bilibili"))
        self.state.decide("2026-10-24", proposal(), FACTS)
        self.assertTrue(self.state.claim("2026-10-24", "bilibili"))

    def test_completed_day_cannot_authorize_a_previously_unclaimed_target(self):
        self.state.decide(DAY, proposal(platform_weights={"both": 100}), FACTS)
        self.assertTrue(self.state.claim(DAY, "bilibili"))
        self.state.result(DAY, "bilibili", {"status": "sent"})
        self.state.finish(DAY)
        self.state.resume("qzone")
        self.assertFalse(self.state.claim(DAY, "qzone"))

    def test_corrupt_json_is_not_silently_reset_or_overwritten(self):
        self.path.write_text('{"days":', encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(json.JSONDecodeError):
            DailyLifeState(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_and_past_new_dates_are_rejected(self):
        with self.assertRaises(ValueError):
            self.state.begin("not-a-day")
        self.state.decide(DAY, proposal(wants_to_share=False), FACTS)
        self.state.finish(DAY)
        with self.assertRaises(ValueError):
            self.state.begin("2026-10-22")


class PublicFactsTests(unittest.TestCase):
    def row(self, **changes):
        result = {"id": 7, "scope": "public", "kind": "message", "platform": "qq",
                  "actor": "1670515707", "session": "qq:group:1027577412",
                  "created_at": "2026-10-23T18:01:00+08:00", "content": "今天聊了苹果派。"}
        result.update(changes)
        return result

    def test_private_inbox_unread_and_discovered_candidates_are_excluded(self):
        rows = [self.row(scope="private"), self.row(kind="inbox"), self.row(kind="dm"),
                self.row(kind="summary"), self.row(content=" 发现视频候选：某某"),
                self.row(content="发现了视频候选：某某"), self.row(content=" \n ")]
        self.assertEqual(public_facts(rows), [])

    def test_actor_session_contacts_and_mentions_are_removed_from_fact_text(self):
        fact = public_facts([self.row(content=(
            "1670515707 在 qq:group:1027577412 说 @苹果乐 好呀，群号12345678。"
            "[CQ:at,qq=3124904460] 看 https://example.com/a 或 www.example.com "
            "邮箱 test@example.com，＠另一个人 再见。"
        ))])[0]
        self.assertEqual(set(fact), {"id", "day", "platform", "role", "kind", "text"})
        self.assertEqual(fact["day"], "2026-10-23")
        for private_piece in ("1670515707", "1027577412", "qq:group:", "12345678", "3124904460",
                              "@", "＠", "example.com", "[CQ:"):
            self.assertNotIn(private_piece, fact["text"])

    def test_only_real_public_experience_kinds_are_kept_with_bot_role(self):
        rows = [self.row(id=index, kind=kind, actor="bot")
                for index, kind in enumerate(("message", "reply", "video", "interaction"))]
        facts = public_facts(rows)
        self.assertEqual([fact["id"] for fact in facts], ["0", "1", "2", "3"])
        self.assertTrue(all(fact["role"] == "我" for fact in facts))
        self.assertEqual(public_facts([self.row()])[0]["role"], "公开互动")

    def test_fact_text_is_bounded(self):
        self.assertEqual(len(public_facts([self.row(content="聊" * 500)])[0]["text"]), 240)


class ReflectionJsonTests(unittest.TestCase):
    def test_json_model_object_accepts_fence_but_not_array(self):
        self.assertEqual(json_object('```json\n{"wants_to_share":false}\n```'), {"wants_to_share": False})
        with self.assertRaises(ValueError):
            json_object("[]")

    def test_non_finite_numeric_values_use_default(self):
        for value in (float("nan"), float("inf"), "-inf", object(), None):
            with self.subTest(value=str(value)):
                self.assertEqual(number(value, 11), 11)


if __name__ == "__main__":
    unittest.main()
