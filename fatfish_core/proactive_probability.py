"""A probability gate for the existing Proactive Chat scheduling flow."""
import random

from .progressive_probability import MissCounters, progressive_probability
from .voice_policy import _offline

DEFAULTS = {"base": 1.0, "step": 0.0, "max": 1.0}


def proactive_probability_allowed(plugin, session_id, session_config):
    """Called after upstream scope/quiet/limit gates and before model work."""
    if _offline(plugin):
        return False
    key = plugin._normalize_session_id(session_id)
    if key in getattr(plugin, "manual_trigger_sessions", set()):
        return True  # Deliberate upstream manual action, not an automatic roll.
    cfg = {**DEFAULTS, **(session_config.get("probability_settings", {}) or {})}
    if float(cfg["base"]) <= 0 and float(cfg["step"]) <= 0:
        return False
    counters = getattr(plugin, "_fatfish_proactive_misses", None)
    if counters is None:
        counters = plugin._fatfish_proactive_misses = MissCounters()
    probability = progressive_probability(cfg["base"], cfg["step"], counters.get(key), ceiling=cfg["max"])
    hit = random.random() < probability
    # An accepted draw may still fail to generate/send. Delivery resets later.
    counters.record(key, sent=False)
    return hit


def proactive_probability_sent(plugin, session_id):
    counters = getattr(plugin, "_fatfish_proactive_misses", None)
    if counters is not None:
        counters.record(plugin._normalize_session_id(session_id), sent=True)
