"""Shared arithmetic and bounded counters; existing plugins still roll/send."""
from collections import OrderedDict
import math


def progressive_probability(base: float, step: float, misses: int, *, ceiling: float = 1.0) -> float:
    values = tuple(map(float, (base, step, ceiling)))
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError("Probability base, step and ceiling must be between 0 and 1")
    return min(values[2], values[0] + max(0, int(misses)) * values[1])


class MissCounters:
    """Per-process, per-full-conversation counters with no chat content."""
    def __init__(self, limit=512):
        self.limit = limit
        self.counts = OrderedDict()

    def get(self, key):
        return self.counts.get(key, 0)

    def record(self, key, *, sent):
        self.counts[key] = 0 if sent else self.get(key) + 1
        self.counts.move_to_end(key)
        while len(self.counts) > self.limit:
            self.counts.popitem(last=False)
