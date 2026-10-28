"""Receipt-driven media decisions, reusing the existing progressive arithmetic."""
from __future__ import annotations

import json
import random
import time
import re
from threading import RLock
from functools import wraps
from uuid import uuid4

from .media_intent import VOICE_REQUEST, VOICE_OPT_OUT, MEME_REQUEST, MEME_OPT_OUT
from .progressive_probability import MissCounters, progressive_probability


def synchronized(function):
    @wraps(function)
    def run(self, *args, **kwargs):
        with self._lock:
            return function(self, *args, **kwargs)
    return run


class DeliveryPolicy:
    def __init__(self, config: dict, *, rng=None, clock=time.time):
        self.config, self.rng, self.clock = config, rng or random.Random(), clock
        self._lock = RLock()
        self.counts = MissCounters()
        self.pending = {}
        self.last_voice = {}
        for channel in ("voice", "meme"):
            item = config[channel]
            progressive_probability(item["base"], item["step"], 0, ceiling=item["max"])

    @staticmethod
    def _scope(value):
        scope = json.loads(value)
        if (not isinstance(scope, list) or len(scope) != 4 or scope[0] != "qq" or
                not all(isinstance(part, str) and part for part in scope) or
                not re.fullmatch(r'[1-9][0-9]*', scope[2]) or
                not re.fullmatch(r'(?:group|private):[1-9][0-9]*', scope[3])):
            raise ValueError("Full trusted QQ scope required")
        return json.dumps(scope, ensure_ascii=False, separators=(",", ":"))

    @synchronized
    def prepare(self, scope: str, text: str, incoming: str, *, active=True):
        scope = self._scope(scope)
        now = self.clock()
        self.pending = {key: item for key, item in self.pending.items() if now - item["at"] < 120}
        if len(self.pending) >= 512:
            raise RuntimeError("Too many unfinished deliveries")
        result = {"id": uuid4().hex, "scope": scope, "at": now}
        for channel, request, optout in (("voice", VOICE_REQUEST, VOICE_OPT_OUT), ("meme", MEME_REQUEST, MEME_OPT_OUT)):
            cfg = self.config[channel]
            eligible = bool(active and cfg["enabled"] and text.strip() and not optout.search(incoming))
            if channel == "voice":
                limit = cfg.get("max_text_length")
                eligible = eligible and (limit is None or len(text) <= limit)
                eligible = eligible and now - self.last_voice.get(scope, -float("inf")) >= cfg.get("cooldown_seconds", 0)
            probability = progressive_probability(cfg["base"], cfg["step"], self.counts.get((channel, scope)), ceiling=cfg["max"])
            manual = bool(cfg.get("manual_trigger") and request.search(incoming))
            hit = eligible and (manual or self.rng.random() < probability)
            result[channel] = {"eligible": eligible, "probability": probability, "hit": hit, "manual": manual}
        self.pending[result["id"]] = result
        return result

    @synchronized
    def finish(self, plan_id: str, *, replied: bool, voice_sent=False, meme_sent=False):
        plan = self.pending.pop(plan_id, None)
        if plan is None:
            return {"recorded": False}  # Repeated finish never increments twice.
        for channel, sent in (("voice", voice_sent), ("meme", meme_sent)):
            if not plan[channel]["eligible"] or not replied:
                continue
            if sent and not plan[channel]["hit"]:
                raise ValueError("Unselected media cannot be marked delivered")
            self.counts.record((channel, plan["scope"]), sent=bool(sent))
            if channel == "voice" and sent:
                self.last_voice[plan["scope"]] = self.clock()
        return {"recorded": True}
