"""Persistent daily apple-pie draw; contains no messaging or background tasks."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from .logic import SHANGHAI
from .state import StateStore


class DailyApplePie:
    def __init__(self, store: StateStore, rng=None) -> None:
        self.store = store
        self.rng = rng if rng is not None else random.Random()

    @staticmethod
    def _local(now: datetime) -> datetime:
        """Naive input is Beijing time; aware input is converted to Beijing."""
        return now.replace(tzinfo=SHANGHAI) if now.tzinfo is None else now.astimezone(SHANGHAI)

    @staticmethod
    def _start(now: datetime) -> datetime:
        return now.replace(hour=18, minute=1, second=0, microsecond=0)

    def draw(self, now: datetime) -> bool:
        now = self._local(now)
        start = self._start(now)
        if now < start:
            return False

        day = now.date().isoformat()
        slot = int((now - start).total_seconds() // 3600)
        state = self.store.daily_apple_pie_state()
        if state.get("day") == day:
            if state.get("claimed") or int(state.get("last_slot", -1)) >= slot:
                return False

        probability = min(0.25 * (slot + 1), 1.0)
        claimed = self.rng.random() < probability
        # Persist before allowing a send: a crash or failed send must not cause
        # another attempt in the same day after restarting the plugin.
        self.store.set_daily_apple_pie_state({
            "day": day,
            "last_slot": slot,
            "claimed": claimed,
            "status": "pending" if claimed else "missed",
        })
        return claimed

    def finish(self, now: datetime, success: bool) -> None:
        day = self._local(now).date().isoformat()
        state = self.store.daily_apple_pie_state()
        if state.get("day") != day or not state.get("claimed") or state.get("status") != "pending":
            return
        state["status"] = "sent" if success else "failed"
        self.store.set_daily_apple_pie_state(state)

    def next_check(self, now: datetime) -> datetime:
        now = self._local(now)
        start = self._start(now)
        state = self.store.daily_apple_pie_state()
        if state.get("day") == now.date().isoformat() and state.get("claimed"):
            return start + timedelta(days=1)
        if now < start:
            return start
        next_hour = now.replace(minute=1, second=0, microsecond=0) + timedelta(hours=1)
        # At xx:00, the next eligible boundary is still xx:01.
        if now.minute == 0:
            next_hour -= timedelta(hours=1)
        return next_hour if next_hour.date() == now.date() else start + timedelta(days=1)
